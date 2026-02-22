"""Unit tests for src/aider_client.py."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.aider_client import (
    AiderFatalError,
    commit_changes,
    get_changed_files,
    get_diff,
    reset_changes,
    run_coder,
    run_reviewer,
)


def _make_proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


# ---------------------------------------------------------------------------
# run_coder
# ---------------------------------------------------------------------------


class TestRunCoder:
    def test_success(self, tmp_path: Path) -> None:
        with patch("src.aider_client.subprocess.run") as mock_run:
            mock_run.side_effect = [
                _make_proc(0, "Done editing."),  # aider
                _make_proc(0, "src/foo.py\n"),  # git diff --name-only HEAD
                _make_proc(0, ""),  # git ls-files untracked
            ]
            result = run_coder("test/model", "do stuff", tmp_path)

        assert result.success is True
        assert result.output == "Done editing."
        assert "src/foo.py" in result.changed_files

    def test_with_read_only_files(self, tmp_path: Path) -> None:
        existing = tmp_path / "memory" / "ARCHITECTURE.md"
        existing.parent.mkdir()
        existing.write_text("arch\n")

        with patch("src.aider_client.subprocess.run") as mock_run:
            mock_run.side_effect = [
                _make_proc(0, "Done."),
                _make_proc(0, ""),
                _make_proc(0, ""),
            ]
            run_coder(
                "test/model",
                "do stuff",
                tmp_path,
                read_only_files=["memory/ARCHITECTURE.md"],
            )

        cmd = mock_run.call_args_list[0][0][0]
        assert "--read" in cmd

    def test_nonexistent_read_only_file_skipped(self, tmp_path: Path) -> None:
        with patch("src.aider_client.subprocess.run") as mock_run:
            mock_run.side_effect = [
                _make_proc(0, "Done."),
                _make_proc(0, ""),
                _make_proc(0, ""),
            ]
            run_coder(
                "test/model", "do stuff", tmp_path, read_only_files=["nonexistent.md"]
            )

        cmd = mock_run.call_args_list[0][0][0]
        assert "--read" not in cmd

    def test_non_zero_exit_raises_fatal_error(self, tmp_path: Path) -> None:
        with patch("src.aider_client.subprocess.run") as mock_run:
            mock_run.side_effect = [
                _make_proc(1, "", "some error"),
                _make_proc(0, ""),
                _make_proc(0, ""),
            ]
            with pytest.raises(AiderFatalError) as exc_info:
                run_coder("test/model", "do stuff", tmp_path)

        assert "some error" in str(exc_info.value)

    def test_non_zero_exit_no_stderr_formats_message(self, tmp_path: Path) -> None:
        with patch("src.aider_client.subprocess.run") as mock_run:
            mock_run.side_effect = [
                _make_proc(2, "", ""),
                _make_proc(0, ""),
                _make_proc(0, ""),
            ]
            result = run_coder("test/model", "do stuff", tmp_path)

        assert result.success is False
        assert "exited with code 2" in result.error

    def test_timeout_returns_failure(self, tmp_path: Path) -> None:
        with patch(
            "src.aider_client.subprocess.run",
            side_effect=subprocess.TimeoutExpired("aider", 30),
        ):
            result = run_coder("test/model", "do stuff", tmp_path, timeout=30)

        assert result.success is False
        assert "timed out" in result.error

    def test_aider_not_found_returns_failure(self, tmp_path: Path) -> None:
        with patch("src.aider_client.subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(AiderFatalError) as exc_info:
                run_coder("test/model", "do stuff", tmp_path)

        assert "not found" in str(exc_info.value).lower() or "Aider not found" in str(
            exc_info.value
        )


# ---------------------------------------------------------------------------
# run_reviewer
# ---------------------------------------------------------------------------


class TestRunReviewer:
    def test_uses_ask_mode(self, tmp_path: Path) -> None:
        with patch("src.aider_client.subprocess.run") as mock_run:
            mock_run.side_effect = [
                _make_proc(0, "VERDICT: PASS"),
                _make_proc(0, ""),
                _make_proc(0, ""),
            ]
            run_reviewer("test/model", "review this", tmp_path)

        cmd = mock_run.call_args_list[0][0][0]
        assert "--chat-mode" in cmd
        assert "ask" in cmd

    def test_with_review_files(self, tmp_path: Path) -> None:
        review_file = tmp_path / "src" / "foo.py"
        review_file.parent.mkdir()
        review_file.write_text("# code\n")

        with patch("src.aider_client.subprocess.run") as mock_run:
            mock_run.side_effect = [
                _make_proc(0, "VERDICT: PASS"),
                _make_proc(0, ""),
                _make_proc(0, ""),
            ]
            run_reviewer(
                "test/model", "review this", tmp_path, review_files=["src/foo.py"]
            )

        cmd = mock_run.call_args_list[0][0][0]
        assert "--read" in cmd


# ---------------------------------------------------------------------------
# get_changed_files
# ---------------------------------------------------------------------------


class TestGetChangedFiles:
    def test_merges_diff_and_untracked(self, tmp_path: Path) -> None:
        with patch("src.aider_client.subprocess.run") as mock_run:
            mock_run.side_effect = [
                _make_proc(0, "src/changed.py\n"),
                _make_proc(0, "src/new_file.py\n"),
            ]
            files = get_changed_files(tmp_path)

        assert "src/changed.py" in files
        assert "src/new_file.py" in files

    def test_empty_results_returns_empty_list(self, tmp_path: Path) -> None:
        with patch("src.aider_client.subprocess.run") as mock_run:
            mock_run.side_effect = [
                _make_proc(0, ""),
                _make_proc(0, ""),
            ]
            files = get_changed_files(tmp_path)

        assert files == []

    def test_subprocess_error_returns_empty(self, tmp_path: Path) -> None:
        with patch(
            "src.aider_client.subprocess.run", side_effect=subprocess.SubprocessError
        ):
            files = get_changed_files(tmp_path)
        assert files == []

    def test_timeout_returns_empty(self, tmp_path: Path) -> None:
        with patch(
            "src.aider_client.subprocess.run",
            side_effect=subprocess.TimeoutExpired("git", 30),
        ):
            files = get_changed_files(tmp_path)
        assert files == []


# ---------------------------------------------------------------------------
# get_diff
# ---------------------------------------------------------------------------


class TestGetDiff:
    def test_returns_stat_and_diff(self, tmp_path: Path) -> None:
        with patch("src.aider_client.subprocess.run") as mock_run:
            mock_run.side_effect = [
                _make_proc(0, "1 file changed"),
                _make_proc(0, "+added line\n-removed line"),
            ]
            result = get_diff(tmp_path)

        assert "1 file changed" in result
        assert "+added line" in result

    def test_truncates_long_diff(self, tmp_path: Path) -> None:
        big_diff = "x" * 4000
        with patch("src.aider_client.subprocess.run") as mock_run:
            mock_run.side_effect = [
                _make_proc(0, "stats"),
                _make_proc(0, big_diff),
            ]
            result = get_diff(tmp_path)

        assert "truncated" in result
        assert len(result) < 5000

    def test_subprocess_error_returns_placeholder(self, tmp_path: Path) -> None:
        with patch(
            "src.aider_client.subprocess.run", side_effect=subprocess.SubprocessError
        ):
            result = get_diff(tmp_path)
        assert "Could not generate diff" in result

    def test_timeout_returns_placeholder(self, tmp_path: Path) -> None:
        with patch(
            "src.aider_client.subprocess.run",
            side_effect=subprocess.TimeoutExpired("git", 30),
        ):
            result = get_diff(tmp_path)
        assert "Could not generate diff" in result


# ---------------------------------------------------------------------------
# commit_changes
# ---------------------------------------------------------------------------


class TestCommitChanges:
    def test_success(self, tmp_path: Path) -> None:
        with patch("src.aider_client.subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(0)
            result = commit_changes(tmp_path, "feat(1.1): built thing")
        assert result is True

    def test_called_process_error_returns_false(self, tmp_path: Path) -> None:
        with patch(
            "src.aider_client.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "git"),
        ):
            result = commit_changes(tmp_path, "feat(1.1): built thing")
        assert result is False

    def test_timeout_returns_false(self, tmp_path: Path) -> None:
        with patch(
            "src.aider_client.subprocess.run",
            side_effect=subprocess.TimeoutExpired("git", 30),
        ):
            result = commit_changes(tmp_path, "feat(1.1): built thing")
        assert result is False


# ---------------------------------------------------------------------------
# reset_changes
# ---------------------------------------------------------------------------


class TestResetChanges:
    def test_success(self, tmp_path: Path) -> None:
        with patch("src.aider_client.subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(0)
            result = reset_changes(tmp_path)
        assert result is True

    def test_called_process_error_returns_false(self, tmp_path: Path) -> None:
        with patch(
            "src.aider_client.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "git"),
        ):
            result = reset_changes(tmp_path)
        assert result is False

    def test_timeout_returns_false(self, tmp_path: Path) -> None:
        with patch(
            "src.aider_client.subprocess.run",
            side_effect=subprocess.TimeoutExpired("git", 30),
        ):
            result = reset_changes(tmp_path)
        assert result is False
