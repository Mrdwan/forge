"""Targeted tests to close the remaining coverage gaps.

These tests cover specific branches that weren't hit by the main test suite.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch


from src.aider_client import AiderResult, run_reviewer
from src.memory import Step, get_coder_context, update_memory
from src.pipeline import StepStatus, execute_step
from src.reviewers import parse_verdict


def _make_proc(returncode: int = 0, stdout: str = "ok", stderr: str = "") -> MagicMock:
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


def _ok_aider(output: str = "done", files: list[str] | None = None) -> AiderResult:
    return AiderResult(
        success=True, output=output, error="", changed_files=files or ["src/foo.py"]
    )


def _pass_review() -> AiderResult:
    return AiderResult(
        success=True, output="VERDICT: PASS\n\nSUMMARY: ok", error="", changed_files=[]
    )


def _fail_review() -> AiderResult:
    return AiderResult(
        success=True,
        output="VERDICT: FAIL\n\nISSUES:\n- bug\n\nSUMMARY: fix it",
        error="",
        changed_files=[],
    )


# ---------------------------------------------------------------------------
# reviewers.py — parse_verdict VERDICT:-less text -> defaulting to False
# ---------------------------------------------------------------------------


class TestParseVerdictFallback:
    def test_no_verdict_anywhere_defaults_to_false(self) -> None:
        """Text has no line containing VERDICT: — for loop exhausts, returns False."""
        result = parse_verdict("No verdict here.\nJust some text.\nAll good.")
        assert result is False

    def test_verdict_line_with_neither_pass_nor_fail(self) -> None:
        """Line contains VERDICT: but value is neither PASS nor FAIL."""
        result = parse_verdict("VERDICT: UNCLEAR\n\nSUMMARY: meh")
        assert result is False


# ---------------------------------------------------------------------------
# aider_client.py — nonexistent review file skipped (filepath.exists() False)
# ---------------------------------------------------------------------------


class TestRunReviewerNonexistentFile:
    def test_nonexistent_review_file_not_added(self, tmp_path: Path) -> None:
        """If review file doesn't exist, --read arg is skipped."""
        with patch("src.aider_client.subprocess.run") as mock_run:
            mock_run.side_effect = [
                _make_proc(0, "VERDICT: PASS"),
                _make_proc(0, ""),
                _make_proc(0, ""),
            ]
            run_reviewer(
                "test/model",
                "review this",
                tmp_path,
                review_files=["src/does_not_exist.py"],
            )

        cmd = mock_run.call_args_list[0][0][0]
        assert "--read" not in cmd


# ---------------------------------------------------------------------------
# memory.py — plan_dir exists but NO file matches step_id glob
# ---------------------------------------------------------------------------


class TestGetCoderContextPlanDirNoMatch:
    def test_plan_dir_exists_but_no_matching_plan_file(
        self, memory_path: Path, sample_step: Step
    ) -> None:
        """plan_dir exists but has no file matching *1.1* — loop body never runs."""
        plan_dir = memory_path.parent / "docs" / "plans"
        plan_dir.mkdir(parents=True)
        (plan_dir / "plan_2.5_other.md").write_text("# Other plan\n")

        context = get_coder_context(memory_path, sample_step)
        assert "Other plan" not in context
        assert "Step 1.1" in context


# ---------------------------------------------------------------------------
# memory.py — update_memory with only ARCHITECTURE section (PROGRESS missing)
# ---------------------------------------------------------------------------


class TestUpdateMemoryOnlyArchSection:
    def _mock_response(self, text: str) -> MagicMock:
        msg = MagicMock()
        msg.content = text
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        return resp

    def test_only_architecture_section_in_response(
        self, memory_path: Path, sample_step: Step
    ) -> None:
        """Response has only ===ARCHITECTURE=== — PROGRESS branches not taken."""
        only_arch = "===ARCHITECTURE===\n# Architecture\n\nNew arch content.\n"
        original_progress = (memory_path / "PROGRESS.md").read_text()

        with patch(
            "src.memory.litellm.completion", return_value=self._mock_response(only_arch)
        ):
            update_memory(memory_path, sample_step, "diff", "review", "test/model")

        assert (
            (memory_path / "ARCHITECTURE.md").read_text().startswith("# Architecture")
        )
        assert (memory_path / "PROGRESS.md").read_text() == original_progress


# ---------------------------------------------------------------------------
# pipeline.py — max_hook_retries=0 skips hook loop (hooks_passed defaults True)
# ---------------------------------------------------------------------------


class TestExecuteStepZeroHookRetries:
    def test_zero_hook_retries_passes_through(
        self, forge_config, memory_path: Path
    ) -> None:
        """max_hook_retries=0 → while loop exits immediately; hooks_passed=True."""
        forge_config.pipeline.max_hook_retries = 0

        with (
            patch("src.pipeline.run_coder", return_value=_ok_aider()),
            patch("src.pipeline.run_pre_commit"),
            patch("src.pipeline.run_junior_review", return_value=_pass_review()),
            patch("src.pipeline.run_senior_review", return_value=_pass_review()),
        ):
            result = execute_step(forge_config)

        # run_pre_commit at module-level is the interface; the while loop didn't run
        # so the main loop's pre_commit was not called (only senior escalation might call it)
        assert result.status == StepStatus.SUCCESS


# ---------------------------------------------------------------------------
# pipeline.py — max_junior_retries=0: jr_result defaults to PASS (source bug fixed),
# while loop exits immediately, escalation skipped
# ---------------------------------------------------------------------------


class TestExecuteStepZeroJuniorRetries:
    def test_zero_junior_retries_uses_default_pass(
        self, forge_config, memory_path: Path
    ) -> None:
        """max_junior_retries=0 → while loop never runs → jr_result defaults to PASS
        → escalation condition is False → goes straight to senior review."""
        forge_config.pipeline.max_junior_retries = 0

        with (
            patch("src.pipeline.run_coder", return_value=_ok_aider()),
            patch("src.pipeline.run_pre_commit", return_value=(True, "")),
            patch("src.pipeline.run_junior_review") as mock_junior,
            patch("src.pipeline.run_senior_review", return_value=_pass_review()),
        ):
            result = execute_step(forge_config)

        # Junior review loop never ran
        mock_junior.assert_not_called()
        assert result.status == StepStatus.SUCCESS


# ---------------------------------------------------------------------------
# pipeline.py:261→271 — hooks pass after senior guidance but junior recheck FAILS
# → senior_rounds incremented (second iteration of senior while loop)
# This tests the branch: hooks_passed=True → jr_recheck=FAIL → continue
# ---------------------------------------------------------------------------


class TestSeniorEscalationJuniorRecheckFails:
    def test_junior_recheck_fails_inside_senior_loop(
        self, forge_config, memory_path: Path
    ) -> None:
        """Senior guidance given, coder retries, hooks pass, junior recheck FAILS
        → senior_rounds incremented, exhausted → FAILED."""
        forge_config.pipeline.max_junior_retries = 1
        forge_config.pipeline.max_senior_rounds = 1

        junior_count = {"n": 0}

        def _junior(*args, **kwargs):
            junior_count["n"] += 1
            # First call (main loop): FAIL to trigger escalation
            # Second call (senior recheck inside loop): FAIL to NOT break
            return _fail_review()

        with (
            patch("src.pipeline.run_coder", return_value=_ok_aider()),
            # hooks always pass (main loop + senior guidance loop)
            patch("src.pipeline.run_pre_commit", return_value=(True, "")),
            patch("src.pipeline.run_junior_review", side_effect=_junior),
            patch(
                "src.pipeline.get_senior_guidance", return_value=_ok_aider("try this")
            ),
        ):
            result = execute_step(forge_config)

        assert result.status == StepStatus.FAILED
        assert "senior escalation" in result.summary
        # Verify recheck was called inside the senior loop
        assert junior_count["n"] >= 2

    def test_hooks_fail_inside_senior_loop(
        self, forge_config, memory_path: Path
    ) -> None:
        """After senior guidance: coder runs, but HOOKS FAIL → jr_recheck skipped
        → senior_rounds incremented → exhausted → FAILED.
        This covers the 264→274 false branch (if hooks_passed: ... skipped)."""
        forge_config.pipeline.max_junior_retries = 1
        forge_config.pipeline.max_senior_rounds = 1

        hook_count = {"n": 0}

        def _hooks(*args, **kwargs):
            hook_count["n"] += 1
            # First call: main loop hooks pass (to proceed to junior)
            if hook_count["n"] == 1:
                return (True, "")
            # Second call: inside senior escalation loop → FAIL
            return (False, "lint error in senior loop")

        with (
            patch("src.pipeline.run_coder", return_value=_ok_aider()),
            patch("src.pipeline.run_pre_commit", side_effect=_hooks),
            patch("src.pipeline.run_junior_review", return_value=_fail_review()),
            patch("src.pipeline.get_senior_guidance", return_value=_ok_aider("fix it")),
        ):
            result = execute_step(forge_config)

        assert result.status == StepStatus.FAILED
        assert "senior escalation" in result.summary


# Note: the `if __name__ == "__main__"` blocks in forge_init.py and src/__main__.py
# are marked with `# pragma: no cover` since they are standard entry-point guards
# that cannot be exercised via import/mock and are not meaningful to test.
