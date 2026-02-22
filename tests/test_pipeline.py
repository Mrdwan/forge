"""Unit tests for src/pipeline.py (non-integration)."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.aider_client import AiderResult
from src.config import ForgeConfig
from src.memory import Step
from src.pipeline import (
    StepResult,
    StepStatus,
    abandon_step,
    execute_step,
    finalize_step,
    run_pre_commit,
)


def _ok_aider(output: str = "done", files: list[str] | None = None) -> AiderResult:
    return AiderResult(success=True, output=output, error="", changed_files=files or ["src/foo.py"])


def _fail_aider(error: str = "aider failed", files: list[str] | None = None) -> AiderResult:
    return AiderResult(success=False, output="", error=error, changed_files=files or [])


def _pass_review(output: str = "VERDICT: PASS\n\nSUMMARY: Great work.") -> AiderResult:
    return AiderResult(success=True, output=output, error="", changed_files=[])


def _fail_review(output: str = "VERDICT: FAIL\n\nISSUES:\n- Bug found.\n\nSUMMARY: Needs work.") -> AiderResult:
    return AiderResult(success=True, output=output, error="", changed_files=[])


def _make_proc(returncode: int = 0, stdout: str = "ok", stderr: str = "") -> MagicMock:
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


# ---------------------------------------------------------------------------
# run_pre_commit
# ---------------------------------------------------------------------------

class TestRunPreCommit:
    def test_all_commands_pass(self, tmp_path: Path) -> None:
        with patch("src.pipeline.subprocess.run", return_value=_make_proc(0)):
            passed, errors = run_pre_commit(tmp_path, ["echo ok", "echo also ok"])
        assert passed is True
        assert errors == ""

    def test_one_command_fails(self, tmp_path: Path) -> None:
        with patch("src.pipeline.subprocess.run") as mock_run:
            mock_run.side_effect = [_make_proc(1, "lint error", "more details"), _make_proc(0)]
            passed, errors = run_pre_commit(tmp_path, ["ruff check src/", "echo ok"])
        assert passed is False
        assert "ruff check src/" in errors

    def test_timeout_recorded_as_error(self, tmp_path: Path) -> None:
        with patch("src.pipeline.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 120)):
            passed, errors = run_pre_commit(tmp_path, ["slow-cmd"])
        assert passed is False
        assert "timed out" in errors

    def test_error_message_truncated_at_1500(self, tmp_path: Path) -> None:
        long_output = "e" * 2000
        with patch("src.pipeline.subprocess.run", return_value=_make_proc(1, long_output, "")):
            passed, errors = run_pre_commit(tmp_path, ["cmd"])
        assert "truncated" in errors

    def test_empty_commands_list_passes(self, tmp_path: Path) -> None:
        passed, errors = run_pre_commit(tmp_path, [])
        assert passed is True
        assert errors == ""

    def test_multiple_failures_combined(self, tmp_path: Path) -> None:
        with patch("src.pipeline.subprocess.run") as mock_run:
            mock_run.side_effect = [_make_proc(1, "err1", ""), _make_proc(1, "err2", "")]
            passed, errors = run_pre_commit(tmp_path, ["cmd1", "cmd2"])
        assert passed is False
        assert "cmd1" in errors
        assert "cmd2" in errors


# ---------------------------------------------------------------------------
# finalize_step
# ---------------------------------------------------------------------------

class TestFinalizeStep:
    def test_happy_path(self, forge_config: ForgeConfig, memory_path: Path, sample_step: Step) -> None:
        result = StepResult(status=StepStatus.SUCCESS, step=sample_step, summary="ok", details="senior review")
        with (
            patch("src.pipeline.commit_changes", return_value=True),
            patch("src.pipeline.get_diff", return_value="diff text"),
            patch("src.pipeline.update_memory") as mock_mem,
        ):
            finalize_step(forge_config, result)
        mock_mem.assert_called_once()

    def test_skips_when_not_success(self, forge_config: ForgeConfig, sample_step: Step) -> None:
        result = StepResult(status=StepStatus.FAILED, step=sample_step, summary="fail")
        with patch("src.pipeline.commit_changes") as mock_commit:
            finalize_step(forge_config, result)
        mock_commit.assert_not_called()

    def test_skips_when_step_is_none(self, forge_config: ForgeConfig) -> None:
        result = StepResult(status=StepStatus.SUCCESS, step=None, summary="ok")
        with patch("src.pipeline.commit_changes") as mock_commit:
            finalize_step(forge_config, result)
        mock_commit.assert_not_called()

    def test_commit_failure_stops_early(self, forge_config: ForgeConfig, sample_step: Step) -> None:
        result = StepResult(status=StepStatus.SUCCESS, step=sample_step, summary="ok", details="d")
        with (
            patch("src.pipeline.commit_changes", return_value=False),
            patch("src.pipeline.update_memory") as mock_mem,
        ):
            finalize_step(forge_config, result)
        mock_mem.assert_not_called()


# ---------------------------------------------------------------------------
# abandon_step
# ---------------------------------------------------------------------------

class TestAbandonStep:
    def test_calls_reset_changes(self, forge_config: ForgeConfig) -> None:
        with patch("src.pipeline.reset_changes") as mock_reset:
            abandon_step(forge_config)
        mock_reset.assert_called_once_with(forge_config.project_path)
