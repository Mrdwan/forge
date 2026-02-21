"""Integration tests for the full pipeline execute_step flow.

Tests the real pipeline orchestration with all external I/O mocked at the boundary:
- subprocess.run (git, pre-commit commands)
- litellm.completion (memory updater)
- run_coder / run_junior_review / run_senior_review / get_senior_guidance
  (aider subprocess wrappers)

This exercises the actual retry logic, escalation cycles, model fallback,
and all edge-case branches in execute_step and finalize_step.
"""

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from src.aider_client import AiderResult
from src.config import ForgeConfig
from src.pipeline import StepResult, StepStatus, execute_step, finalize_step
from src.memory import Step


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok_aider(output: str = "Implemented successfully.", files: list[str] | None = None) -> AiderResult:
    return AiderResult(success=True, output=output, error="", changed_files=files or ["src/foo.py"])


def _empty_aider(error: str = "aider crashed") -> AiderResult:
    """Completely failed — no output, no changed files."""
    return AiderResult(success=False, output="", error=error, changed_files=[])


def _pass_review(summary: str = "Looks good.") -> AiderResult:
    return AiderResult(
        success=True,
        output=f"VERDICT: PASS\n\nSUMMARY: {summary}",
        error="",
        changed_files=[],
    )


def _fail_review(issues: str = "Missing error handling.") -> AiderResult:
    return AiderResult(
        success=True,
        output=f"VERDICT: FAIL\n\nISSUES:\n- {issues}\n\nSUMMARY: Fix it.",
        error="",
        changed_files=[],
    )


def _make_proc(returncode: int = 0, stdout: str = "ok", stderr: str = "") -> MagicMock:
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


# ---------------------------------------------------------------------------
# Full happy path
# ---------------------------------------------------------------------------

class TestExecuteStepHappyPath:
    def test_single_pass_through(self, forge_config: ForgeConfig, memory_path: Path) -> None:
        """Coder → hooks pass → junior pass → senior pass → SUCCESS."""
        with (
            patch("src.pipeline.run_coder", return_value=_ok_aider()) as mock_coder,
            patch("src.pipeline.subprocess.run", return_value=_make_proc(0)),  # hooks
            patch("src.pipeline.run_junior_review", return_value=_pass_review()),
            patch("src.pipeline.run_senior_review", return_value=_pass_review("Excellent.")) as mock_senior,
            patch("src.pipeline.get_diff", return_value="diff text"),
        ):
            result = execute_step(forge_config)

        assert result.status == StepStatus.SUCCESS
        assert result.step is not None
        assert result.step.step_id == "1.1"
        assert "✅" in result.summary
        mock_coder.assert_called_once()
        mock_senior.assert_called_once()


# ---------------------------------------------------------------------------
# No steps
# ---------------------------------------------------------------------------

class TestExecuteStepNoSteps:
    def test_returns_no_steps_when_roadmap_is_complete(self, forge_config: ForgeConfig, memory_path: Path) -> None:
        roadmap = memory_path / "ROADMAP.md"
        roadmap.write_text("# Roadmap\n\n- [x] Step 1.1: Done\n- [x] Step 1.2: Also done\n")
        result = execute_step(forge_config)
        assert result.status == StepStatus.NO_STEPS
        assert result.step is None


# ---------------------------------------------------------------------------
# Model fallback
# ---------------------------------------------------------------------------

class TestExecuteStepModelFallback:
    def test_primary_fails_fallback_succeeds(self, forge_config: ForgeConfig, memory_path: Path) -> None:
        """Primary coder returns no output → switch to fallback → continue pipeline."""
        call_count = {"n": 0}

        def _coder_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _empty_aider("primary model unavailable")
            return _ok_aider()

        with (
            patch("src.pipeline.run_coder", side_effect=_coder_side_effect),
            patch("src.pipeline.subprocess.run", return_value=_make_proc(0)),
            patch("src.pipeline.run_junior_review", return_value=_pass_review()),
            patch("src.pipeline.run_senior_review", return_value=_pass_review()),
            patch("src.pipeline.get_diff", return_value="diff"),
        ):
            result = execute_step(forge_config)

        assert result.status == StepStatus.SUCCESS
        assert call_count["n"] == 2  # primary + fallback

    def test_both_coders_fail_returns_failed(self, forge_config: ForgeConfig, memory_path: Path) -> None:
        with patch("src.pipeline.run_coder", return_value=_empty_aider("model down")):
            result = execute_step(forge_config)

        assert result.status == StepStatus.FAILED
        assert "Coder produced no output" in result.summary


# ---------------------------------------------------------------------------
# Hook retry cycles
# ---------------------------------------------------------------------------

class TestExecuteStepHookRetries:
    def test_hooks_fail_once_then_pass(self, forge_config: ForgeConfig, memory_path: Path) -> None:
        """Hooks fail on first run, coder fixes, hooks pass on second run."""
        hook_count = {"n": 0}

        def _hook_side_effect(*args, **kwargs):
            hook_count["n"] += 1
            if hook_count["n"] == 1:
                return _make_proc(1, "lint error", "")
            return _make_proc(0)

        with (
            patch("src.pipeline.run_coder", return_value=_ok_aider()),
            patch("src.pipeline.subprocess.run", side_effect=_hook_side_effect),
            patch("src.pipeline.run_junior_review", return_value=_pass_review()),
            patch("src.pipeline.run_senior_review", return_value=_pass_review()),
            patch("src.pipeline.get_diff", return_value="diff"),
        ):
            result = execute_step(forge_config)

        assert result.status == StepStatus.SUCCESS

    def test_hooks_exhaust_all_retries_returns_failed(self, forge_config: ForgeConfig, memory_path: Path) -> None:
        """Hooks always fail → returns FAILED after max_hook_retries."""
        forge_config.pipeline.max_hook_retries = 2

        with (
            patch("src.pipeline.run_coder", return_value=_ok_aider()),
            patch("src.pipeline.subprocess.run", return_value=_make_proc(1, "always fails")),
        ):
            result = execute_step(forge_config)

        assert result.status == StepStatus.FAILED
        assert "Pre-commit hooks failed" in result.summary


# ---------------------------------------------------------------------------
# Junior retry cycles
# ---------------------------------------------------------------------------

class TestExecuteStepJuniorRetries:
    def test_junior_fails_once_coder_fixes_junior_passes(
        self, forge_config: ForgeConfig, memory_path: Path
    ) -> None:
        """Junior reviews FAIL, coder fixes, junior passes on second try."""
        junior_count = {"n": 0}

        def _junior_side_effect(*args, **kwargs):
            junior_count["n"] += 1
            if junior_count["n"] == 1:
                return _fail_review("Missing tests.")
            return _pass_review()

        with (
            patch("src.pipeline.run_coder", return_value=_ok_aider()),
            patch("src.pipeline.subprocess.run", return_value=_make_proc(0)),
            patch("src.pipeline.run_junior_review", side_effect=_junior_side_effect),
            patch("src.pipeline.run_senior_review", return_value=_pass_review()),
            patch("src.pipeline.get_diff", return_value="diff"),
        ):
            result = execute_step(forge_config)

        assert result.status == StepStatus.SUCCESS
        assert junior_count["n"] == 2

    def test_junior_hooks_fail_after_coder_fix(self, forge_config: ForgeConfig, memory_path: Path) -> None:
        """During junior loop: junior fails → coder fixes → hooks STILL fail → coder fixes again."""
        hook_count = {"n": 0}
        junior_count = {"n": 0}

        def _junior_side_effect(*args, **kwargs):
            junior_count["n"] += 1
            if junior_count["n"] <= 1:
                return _fail_review()
            return _pass_review()

        def _hook_side_effect(*args, **kwargs):
            hook_count["n"] += 1
            # first two hook runs: pass (initial check), then fail (after junior fix), then pass
            if hook_count["n"] == 2:
                return _make_proc(1, "hook error")
            return _make_proc(0)

        with (
            patch("src.pipeline.run_coder", return_value=_ok_aider()),
            patch("src.pipeline.subprocess.run", side_effect=_hook_side_effect),
            patch("src.pipeline.run_junior_review", side_effect=_junior_side_effect),
            patch("src.pipeline.run_senior_review", return_value=_pass_review()),
            patch("src.pipeline.get_diff", return_value="diff"),
        ):
            result = execute_step(forge_config)

        # Should still succeed eventually
        assert result.status == StepStatus.SUCCESS


# ---------------------------------------------------------------------------
# Senior escalation
# ---------------------------------------------------------------------------

class TestExecuteStepSeniorEscalation:
    def test_junior_exhausted_senior_guides_coder_to_success(
        self, forge_config: ForgeConfig, memory_path: Path
    ) -> None:
        """Junior loop exhausted → senior guidance → coder fixes → hooks + junior pass."""
        forge_config.pipeline.max_junior_retries = 2

        junior_count = {"n": 0}

        def _junior_side_effect(*args, **kwargs):
            junior_count["n"] += 1
            # First 2 fail (exhaust loop), then recheck after senior guidance passes
            if junior_count["n"] <= 2:
                return _fail_review("deep issues")
            return _pass_review()

        with (
            patch("src.pipeline.run_coder", return_value=_ok_aider()),
            patch("src.pipeline.subprocess.run", return_value=_make_proc(0)),
            patch("src.pipeline.run_junior_review", side_effect=_junior_side_effect),
            patch("src.pipeline.get_senior_guidance", return_value=_ok_aider("Fix the interface")),
            patch("src.pipeline.run_senior_review", return_value=_pass_review("Excellent.")),
            patch("src.pipeline.get_diff", return_value="diff"),
        ):
            result = execute_step(forge_config)

        assert result.status == StepStatus.SUCCESS

    def test_senior_escalation_exhausted_returns_failed(
        self, forge_config: ForgeConfig, memory_path: Path
    ) -> None:
        """Junior loop exhausted + all senior rounds exhausted → FAILED."""
        forge_config.pipeline.max_junior_retries = 2
        forge_config.pipeline.max_senior_rounds = 2

        with (
            patch("src.pipeline.run_coder", return_value=_ok_aider()),
            patch("src.pipeline.subprocess.run", return_value=_make_proc(0)),
            patch("src.pipeline.run_junior_review", return_value=_fail_review("never happy")),
            patch("src.pipeline.get_senior_guidance", return_value=_ok_aider("try this")),
        ):
            result = execute_step(forge_config)

        assert result.status == StepStatus.FAILED
        assert "senior escalation" in result.summary


# ---------------------------------------------------------------------------
# Final senior review paths
# ---------------------------------------------------------------------------

class TestExecuteStepFinalSeniorReview:
    def test_senior_fails_coder_retry_junior_pass_senior_pass(
        self, forge_config: ForgeConfig, memory_path: Path
    ) -> None:
        """Senior review fails → one more coder attempt → hooks pass → junior pass → senior pass."""
        senior_count = {"n": 0}

        def _senior_side_effect(*args, **kwargs):
            senior_count["n"] += 1
            if senior_count["n"] == 1:
                return _fail_review("Security issue.")
            return _pass_review("All good now.")

        with (
            patch("src.pipeline.run_coder", return_value=_ok_aider()),
            patch("src.pipeline.subprocess.run", return_value=_make_proc(0)),
            patch("src.pipeline.run_junior_review", return_value=_pass_review()),
            patch("src.pipeline.run_senior_review", side_effect=_senior_side_effect),
            patch("src.pipeline.get_diff", return_value="diff"),
        ):
            result = execute_step(forge_config)

        assert result.status == StepStatus.SUCCESS
        assert senior_count["n"] == 2

    def test_senior_fails_hooks_fail_after_retry(
        self, forge_config: ForgeConfig, memory_path: Path
    ) -> None:
        """Senior review fails → coder fix → hooks fail → FAILED."""
        hook_count = {"n": 0}

        def _hook_side_effect(*args, **kwargs):
            hook_count["n"] += 1
            # First hook run passes (before junior/senior), second fails after senior fix
            if hook_count["n"] <= 1:
                return _make_proc(0)
            return _make_proc(1, "ruff error")

        with (
            patch("src.pipeline.run_coder", return_value=_ok_aider()),
            patch("src.pipeline.subprocess.run", side_effect=_hook_side_effect),
            patch("src.pipeline.run_junior_review", return_value=_pass_review()),
            patch("src.pipeline.run_senior_review", return_value=_fail_review("Security issue.")),
        ):
            result = execute_step(forge_config)

        assert result.status == StepStatus.FAILED
        assert "pre-commit" in result.summary.lower()

    def test_senior_fails_coder_retry_junior_fails_after_retry(
        self, forge_config: ForgeConfig, memory_path: Path
    ) -> None:
        """Senior fails → coder fix → hooks pass → junior fails → FAILED."""
        junior_count = {"n": 0}

        def _junior_side_effect(*args, **kwargs):
            junior_count["n"] += 1
            # First junior pass (normal path), second junior after senior fix fails
            if junior_count["n"] == 1:
                return _pass_review()
            return _fail_review("still bad")

        with (
            patch("src.pipeline.run_coder", return_value=_ok_aider()),
            patch("src.pipeline.subprocess.run", return_value=_make_proc(0)),
            patch("src.pipeline.run_junior_review", side_effect=_junior_side_effect),
            patch("src.pipeline.run_senior_review", return_value=_fail_review("Design issue.")),
        ):
            result = execute_step(forge_config)

        assert result.status == StepStatus.FAILED
        assert "junior re-check" in result.summary

    def test_senior_fails_final_senior_also_fails(
        self, forge_config: ForgeConfig, memory_path: Path
    ) -> None:
        """Senior fails → coder fix → hooks pass → junior pass → final senior fails → FAILED."""
        junior_count = {"n": 0}

        def _junior_side_effect(*args, **kwargs):
            junior_count["n"] += 1
            # First junior pass, second after senior retry also pass (to reach final senior check)
            return _pass_review()

        senior_count = {"n": 0}

        def _senior_side_effect(*args, **kwargs):
            senior_count["n"] += 1
            return _fail_review(f"senior failure round {senior_count['n']}")

        with (
            patch("src.pipeline.run_coder", return_value=_ok_aider()),
            patch("src.pipeline.subprocess.run", return_value=_make_proc(0)),
            patch("src.pipeline.run_junior_review", side_effect=_junior_side_effect),
            patch("src.pipeline.run_senior_review", side_effect=_senior_side_effect),
        ):
            result = execute_step(forge_config)

        assert result.status == StepStatus.FAILED
        assert "final senior review" in result.summary


# ---------------------------------------------------------------------------
# finalize_step integration
# ---------------------------------------------------------------------------

class TestFinalizeStepIntegration:
    def test_full_finalize_marks_step_complete(
        self, forge_config: ForgeConfig, memory_path: Path
    ) -> None:
        """Commit + memory update + mark step complete — verify ROADMAP.md is updated."""
        step = Step("1.1", "Build the first thing", "- [ ] Step 1.1: Build the first thing")
        result = StepResult(
            status=StepStatus.SUCCESS,
            step=step,
            summary="✅ Step 1.1",
            details="VERDICT: PASS\n\nSUMMARY: Great.",
        )

        with (
            patch("src.pipeline.commit_changes", return_value=True),
            patch("src.pipeline.get_diff", return_value=""),
            patch("src.pipeline.update_memory"),
        ):
            finalize_step(forge_config, result)

        roadmap_content = (memory_path / "ROADMAP.md").read_text()
        assert "- [x] Step 1.1" in roadmap_content
        assert "- [ ] Step 1.1" not in roadmap_content
