"""Unit tests for src/cli.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from src.cli import (
    COMMANDS,
    _load_state,
    _save_state,
    _truncate,
    cmd_next,
    cmd_reset,
    cmd_skip,
    cmd_status,
    notify_telegram,
    run_cli,
)
from src.bot import BotState
from src.config import ForgeConfig
from src.memory import Step
from src.pipeline import StepResult, StepStatus


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_step() -> Step:
    return Step("2.1", "Build something", "- [ ] Step 2.1: Build something")


def _success_result() -> StepResult:
    return StepResult(
        status=StepStatus.SUCCESS,
        step=_make_step(),
        summary="✅ Step 2.1: Build something",
        details="VERDICT: PASS\n\nGreat work.",
    )


def _fail_result() -> StepResult:
    return StepResult(
        status=StepStatus.FAILED,
        step=_make_step(),
        summary="❌ Step 2.1 failed",
        details="Tests broke.",
    )


def _no_steps_result() -> StepResult:
    return StepResult(
        status=StepStatus.NO_STEPS,
        step=None,
        summary="All steps complete!",
    )


@pytest.fixture()
def cfg(forge_config: ForgeConfig) -> ForgeConfig:
    """Re-use the shared conftest ForgeConfig."""
    return forge_config


# ---------------------------------------------------------------------------
# notify_telegram
# ---------------------------------------------------------------------------

class TestNotifyTelegram:
    def test_calls_post_when_token_and_chat_set(self, cfg: ForgeConfig) -> None:
        cfg.telegram.bot_token = "tok123"
        cfg.telegram.chat_id = "999"
        with patch("src.cli.urllib.request.urlopen") as mock_open:
            notify_telegram(cfg, "hello")
        mock_open.assert_called_once()
        # Check the request object has the right URL
        req = mock_open.call_args[0][0]
        assert "tok123" in req.full_url

    def test_no_call_when_token_missing(self, cfg: ForgeConfig) -> None:
        cfg.telegram.bot_token = ""
        cfg.telegram.chat_id = "999"
        with patch("src.cli.urllib.request.urlopen") as mock_open:
            notify_telegram(cfg, "hello")
        mock_open.assert_not_called()

    def test_no_call_when_chat_id_missing(self, cfg: ForgeConfig) -> None:
        cfg.telegram.bot_token = "tok"
        cfg.telegram.chat_id = ""
        with patch("src.cli.urllib.request.urlopen") as mock_open:
            notify_telegram(cfg, "hello")
        mock_open.assert_not_called()

    def test_swallows_request_exceptions(self, cfg: ForgeConfig) -> None:
        cfg.telegram.bot_token = "tok"
        cfg.telegram.chat_id = "1"
        with patch("src.cli.urllib.request.urlopen", side_effect=OSError("offline")):
            # Should not raise
            notify_telegram(cfg, "hello")


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

class TestStateHelpers:
    def test_load_returns_idle_when_no_file(self, tmp_path: Path) -> None:
        with patch("src.cli.STATE_FILE", str(tmp_path / "missing.json")):
            assert _load_state() == BotState.IDLE

    def test_load_returns_saved_state(self, tmp_path: Path) -> None:
        p = tmp_path / "state.json"
        p.write_text(json.dumps({"state": "executing"}))
        with patch("src.cli.STATE_FILE", str(p)):
            assert _load_state() == BotState.EXECUTING

    def test_load_corrupted_defaults_to_idle(self, tmp_path: Path) -> None:
        p = tmp_path / "state.json"
        p.write_text("{{bad json")
        with patch("src.cli.STATE_FILE", str(p)):
            assert _load_state() == BotState.IDLE

    def test_save_writes_json(self, tmp_path: Path) -> None:
        p = tmp_path / "state.json"
        with patch("src.cli.STATE_FILE", str(p)):
            _save_state(BotState.CONFIRMING)
        data = json.loads(p.read_text())
        assert data["state"] == "confirming"


# ---------------------------------------------------------------------------
# cmd_status
# ---------------------------------------------------------------------------

class TestCmdStatus:
    def test_prints_state_and_step(self, cfg: ForgeConfig, capsys: pytest.CaptureFixture) -> None:
        with (
            patch("src.cli._load_state", return_value=BotState.IDLE),
            patch("src.cli.find_next_step", return_value=_make_step()),
        ):
            cmd_status(cfg)
        out = capsys.readouterr().out
        assert "idle" in out
        assert "2.1" in out

    def test_prints_all_complete_when_no_steps(self, cfg: ForgeConfig, capsys: pytest.CaptureFixture) -> None:
        with (
            patch("src.cli._load_state", return_value=BotState.IDLE),
            patch("src.cli.find_next_step", return_value=None),
        ):
            cmd_status(cfg)
        out = capsys.readouterr().out
        assert "complete" in out.lower()


# ---------------------------------------------------------------------------
# cmd_skip
# ---------------------------------------------------------------------------

class TestCmdSkip:
    def test_skips_in_confirming_state(self, cfg: ForgeConfig, capsys: pytest.CaptureFixture) -> None:
        with (
            patch("src.cli._load_state", return_value=BotState.CONFIRMING),
            patch("src.cli._save_state") as mock_save,
            patch("src.cli.abandon_step") as mock_abandon,
            patch("src.cli.notify_telegram") as mock_notify,
        ):
            cmd_skip(cfg, notify=True)
        mock_abandon.assert_called_once_with(cfg)
        mock_save.assert_called_once_with(BotState.IDLE)
        mock_notify.assert_called_once()

    def test_skips_in_failed_state(self, cfg: ForgeConfig) -> None:
        with (
            patch("src.cli._load_state", return_value=BotState.FAILED),
            patch("src.cli._save_state"),
            patch("src.cli.abandon_step") as mock_abandon,
            patch("src.cli.notify_telegram"),
        ):
            cmd_skip(cfg)
        mock_abandon.assert_called_once()

    def test_does_nothing_in_idle(self, cfg: ForgeConfig, capsys: pytest.CaptureFixture) -> None:
        with (
            patch("src.cli._load_state", return_value=BotState.IDLE),
            patch("src.cli.abandon_step") as mock_abandon,
        ):
            cmd_skip(cfg)
        mock_abandon.assert_not_called()
        assert "nothing" in capsys.readouterr().out.lower()

    def test_no_telegram_when_notify_false(self, cfg: ForgeConfig) -> None:
        with (
            patch("src.cli._load_state", return_value=BotState.CONFIRMING),
            patch("src.cli._save_state"),
            patch("src.cli.abandon_step"),
            patch("src.cli.notify_telegram") as mock_notify,
        ):
            cmd_skip(cfg, notify=False)
        mock_notify.assert_not_called()


# ---------------------------------------------------------------------------
# cmd_reset
# ---------------------------------------------------------------------------

class TestCmdReset:
    def test_calls_abandon_and_saves_idle(self, cfg: ForgeConfig) -> None:
        with (
            patch("src.cli.abandon_step") as mock_abandon,
            patch("src.cli._save_state") as mock_save,
            patch("src.cli.notify_telegram"),
        ):
            cmd_reset(cfg)
        mock_abandon.assert_called_once_with(cfg)
        mock_save.assert_called_once_with(BotState.IDLE)

    def test_no_telegram_when_notify_false(self, cfg: ForgeConfig) -> None:
        with (
            patch("src.cli.abandon_step"),
            patch("src.cli._save_state"),
            patch("src.cli.notify_telegram") as mock_notify,
        ):
            cmd_reset(cfg, notify=False)
        mock_notify.assert_not_called()


# ---------------------------------------------------------------------------
# cmd_next
# ---------------------------------------------------------------------------

class TestCmdNext:
    def test_prints_already_running_when_executing(self, cfg: ForgeConfig, capsys: pytest.CaptureFixture) -> None:
        with patch("src.cli._load_state", return_value=BotState.EXECUTING):
            cmd_next(cfg)
        out = capsys.readouterr().out
        assert "running" in out.lower() or "executing" in out.lower()

    def test_no_steps_left(self, cfg: ForgeConfig, capsys: pytest.CaptureFixture) -> None:
        with (
            patch("src.cli._load_state", return_value=BotState.IDLE),
            patch("src.cli.find_next_step", return_value=None),
            patch("src.cli.notify_telegram"),
        ):
            cmd_next(cfg)
        out = capsys.readouterr().out
        assert "complete" in out.lower()

    def test_shows_step_and_prompts_go(self, cfg: ForgeConfig, capsys: pytest.CaptureFixture) -> None:
        """User types 'go' → pipeline runs."""
        with (
            patch("src.cli._load_state", return_value=BotState.IDLE),
            patch("src.cli._save_state"),
            patch("src.cli.find_next_step", return_value=_make_step()),
            patch("src.cli._prompt", return_value="go"),
            patch("src.cli._run_pipeline") as mock_run,
        ):
            cmd_next(cfg)
        mock_run.assert_called_once_with(cfg, notify=True)

    def test_shows_step_and_prompts_skip(self, cfg: ForgeConfig) -> None:
        """User types 'skip' → cmd_skip called."""
        with (
            patch("src.cli._load_state", return_value=BotState.IDLE),
            patch("src.cli._save_state"),
            patch("src.cli.find_next_step", return_value=_make_step()),
            patch("src.cli._prompt", return_value="skip"),
            patch("src.cli.cmd_skip") as mock_skip,
        ):
            cmd_next(cfg)
        mock_skip.assert_called_once_with(cfg, notify=True)

    def test_invalid_reply_loops_then_go(self, cfg: ForgeConfig) -> None:
        """Unknown input is ignored; second input 'go' proceeds."""
        replies = iter(["what", "go"])
        with (
            patch("src.cli._load_state", return_value=BotState.IDLE),
            patch("src.cli._save_state"),
            patch("src.cli.find_next_step", return_value=_make_step()),
            patch("src.cli._prompt", side_effect=replies),
            patch("src.cli._run_pipeline") as mock_run,
        ):
            cmd_next(cfg)
        mock_run.assert_called_once()

    def test_awaiting_commit_redirects_to_prompt_commit(self, cfg: ForgeConfig, capsys: pytest.CaptureFixture) -> None:
        with (
            patch("src.cli._load_state", return_value=BotState.AWAITING_COMMIT),
            patch("src.cli._prompt_commit") as mock_commit,
        ):
            cmd_next(cfg)
        mock_commit.assert_called_once()


# ---------------------------------------------------------------------------
# _run_pipeline (via cmd_next integration)
# ---------------------------------------------------------------------------

class TestRunPipeline:
    def test_success_sets_awaiting_commit(self, cfg: ForgeConfig) -> None:
        with (
            patch("src.cli._save_state") as mock_save,
            patch("src.cli.find_next_step", return_value=_make_step()),
            patch("src.cli.execute_step", return_value=_success_result()),
            patch("src.cli._prompt_commit"),
            patch("src.cli.notify_telegram"),
        ):
            from src.cli import _run_pipeline
            _run_pipeline(cfg, notify=True)
        # Should transition to AWAITING_COMMIT
        states = [c.args[0] for c in mock_save.call_args_list]
        assert BotState.AWAITING_COMMIT in states

    def test_failure_sets_failed(self, cfg: ForgeConfig) -> None:
        with (
            patch("src.cli._save_state") as mock_save,
            patch("src.cli.find_next_step", return_value=_make_step()),
            patch("src.cli.execute_step", return_value=_fail_result()),
            patch("src.cli._prompt_after_failure"),
            patch("src.cli.notify_telegram"),
        ):
            from src.cli import _run_pipeline
            _run_pipeline(cfg, notify=True)
        states = [c.args[0] for c in mock_save.call_args_list]
        assert BotState.FAILED in states

    def test_exception_sets_failed(self, cfg: ForgeConfig) -> None:
        with (
            patch("src.cli._save_state") as mock_save,
            patch("src.cli.find_next_step", return_value=_make_step()),
            patch("src.cli.execute_step", side_effect=RuntimeError("boom")),
            patch("src.cli.notify_telegram"),
        ):
            from src.cli import _run_pipeline
            _run_pipeline(cfg, notify=True)
        states = [c.args[0] for c in mock_save.call_args_list]
        assert BotState.FAILED in states

    def test_notify_telegram_called_on_start(self, cfg: ForgeConfig) -> None:
        cfg.telegram.bot_token = "tok"
        cfg.telegram.chat_id = "1"
        with (
            patch("src.cli._save_state"),
            patch("src.cli.find_next_step", return_value=_make_step()),
            patch("src.cli.execute_step", return_value=_no_steps_result()),
            patch("src.cli.notify_telegram") as mock_notify,
        ):
            from src.cli import _run_pipeline
            _run_pipeline(cfg, notify=True)
        mock_notify.assert_called()

    def test_no_notify_when_notify_false(self, cfg: ForgeConfig) -> None:
        with (
            patch("src.cli._save_state"),
            patch("src.cli.find_next_step", return_value=_make_step()),
            patch("src.cli.execute_step", return_value=_no_steps_result()),
            patch("src.cli.notify_telegram") as mock_notify,
        ):
            from src.cli import _run_pipeline
            _run_pipeline(cfg, notify=False)
        mock_notify.assert_not_called()


# ---------------------------------------------------------------------------
# run_cli dispatch
# ---------------------------------------------------------------------------

class TestRunCli:
    def test_dispatches_status(self, cfg: ForgeConfig) -> None:
        with (
            patch("src.cli.ensure_memory_bank"),
            patch("src.cli.cmd_status") as mock_status,
        ):
            run_cli(cfg, ["status"])
        mock_status.assert_called_once_with(cfg)

    def test_dispatches_skip(self, cfg: ForgeConfig) -> None:
        with (
            patch("src.cli.ensure_memory_bank"),
            patch("src.cli.cmd_skip") as mock_skip,
        ):
            run_cli(cfg, ["skip"])
        mock_skip.assert_called_once_with(cfg)

    def test_dispatches_reset(self, cfg: ForgeConfig) -> None:
        with (
            patch("src.cli.ensure_memory_bank"),
            patch("src.cli.cmd_reset") as mock_reset,
        ):
            run_cli(cfg, ["reset"])
        mock_reset.assert_called_once_with(cfg)

    def test_dispatches_next(self, cfg: ForgeConfig) -> None:
        with (
            patch("src.cli.ensure_memory_bank"),
            patch("src.cli.cmd_next") as mock_next,
        ):
            run_cli(cfg, ["next"])
        mock_next.assert_called_once_with(cfg)

    def test_exits_on_unknown_command(self, cfg: ForgeConfig) -> None:
        with (
            patch("src.cli.ensure_memory_bank"),
            pytest.raises(SystemExit),
        ):
            run_cli(cfg, ["unknown"])

    def test_exits_on_empty_args(self, cfg: ForgeConfig) -> None:
        with (
            patch("src.cli.ensure_memory_bank"),
            pytest.raises(SystemExit),
        ):
            run_cli(cfg, [])


# ---------------------------------------------------------------------------
# _truncate
# ---------------------------------------------------------------------------

class TestTruncate:
    def test_short_unchanged(self) -> None:
        assert _truncate("hi", 100) == "hi"

    def test_long_truncated(self) -> None:
        result = _truncate("x" * 200, 100)
        assert "truncated" in result
        assert result.startswith("x" * 100)
