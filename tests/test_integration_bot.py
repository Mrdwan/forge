"""Integration tests for the bot state machine.

Tests the full ForgeBot state machine end-to-end with real state file I/O.
All pipeline calls and Telegram API calls are mocked.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot import BotState, ForgeBot
from src.pipeline import StepResult, StepStatus
from src.memory import Step


def _make_step(step_id: str = "1.1", desc: str = "Build first thing") -> Step:
    return Step(step_id, desc, f"- [ ] Step {step_id}: {desc}")


def _make_update(text: str = "go") -> MagicMock:
    update = MagicMock()
    update.message = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def _success_result(step: Step | None = None) -> StepResult:
    s = step or _make_step()
    return StepResult(
        status=StepStatus.SUCCESS,
        step=s,
        summary=f"✅ Step {s.step_id}: {s.description}",
        details="VERDICT: PASS\n\nSUMMARY: All good.",
    )


def _fail_result() -> StepResult:
    return StepResult(
        status=StepStatus.FAILED,
        step=_make_step(),
        summary="❌ Step 1.1 failed",
        details="Tests failed.",
    )


def _no_steps_result() -> StepResult:
    return StepResult(status=StepStatus.NO_STEPS, step=None, summary="All done.")


def _make_bot(
    state_dir: Path, initial_state: BotState = BotState.IDLE, forge_config=None
):
    """Create a ForgeBot with state file in tmp_path, skip actual state read."""
    state_file = state_dir / "forge_state.json"
    with patch("src.bot.STATE_FILE", str(state_file)):
        bot = ForgeBot(forge_config)
    bot.state = initial_state
    # Real _save_state so we can verify persistence

    def _patched_save():
        state_file.write_text(json.dumps({"state": bot.state.value}))

    bot._save_state = _patched_save
    bot._state_file = state_file
    return bot


# ---------------------------------------------------------------------------
# Complete success flow: /next → go → commit
# ---------------------------------------------------------------------------


class TestBotSuccessFlow:
    @pytest.mark.asyncio
    async def test_next_go_success_commit_flow(
        self, tmp_path: Path, forge_config
    ) -> None:
        """/next → go → step succeeds → commit → back to IDLE."""
        bot = _make_bot(tmp_path, BotState.IDLE, forge_config)
        step = _make_step()

        # Step 1: /next
        update = _make_update()
        with patch("src.bot.find_next_step", return_value=step):
            await bot.cmd_next(update, MagicMock())
        assert bot.state == BotState.CONFIRMING

        # Step 2: 'go' reply
        update2 = _make_update("go")
        with patch("src.bot.asyncio.to_thread", return_value=_success_result(step)):
            await bot.handle_message(update2, MagicMock())
        assert bot.state == BotState.AWAITING_COMMIT
        assert bot.current_result is not None
        assert bot.current_result.status == StepStatus.SUCCESS

        # Step 3: 'commit' reply
        update3 = _make_update("commit")
        with (
            patch("src.bot.asyncio.to_thread", return_value=None),  # finalize_step
        ):
            await bot.handle_message(update3, MagicMock())
        assert bot.state == BotState.IDLE
        assert bot.current_result is None

        # Verify final reply contains step ID
        reply = update3.message.reply_text.call_args[0][0]
        assert "1.1" in reply

    @pytest.mark.asyncio
    async def test_state_persists_to_disk_during_flow(
        self, tmp_path: Path, forge_config
    ) -> None:
        """State file should be updated at each transition."""
        bot = _make_bot(tmp_path, BotState.IDLE, forge_config)
        update = _make_update()

        with patch("src.bot.find_next_step", return_value=_make_step()):
            await bot.cmd_next(update, MagicMock())

        state_data = json.loads(bot._state_file.read_text())
        assert state_data["state"] == "confirming"


# ---------------------------------------------------------------------------
# Failure + retry flow
# ---------------------------------------------------------------------------


class TestBotFailureAndRetry:
    @pytest.mark.asyncio
    async def test_failure_then_retry_then_commit(
        self, tmp_path: Path, forge_config
    ) -> None:
        """Execute fails → retry → success → commit."""
        bot = _make_bot(tmp_path, BotState.CONFIRMING, forge_config)

        # First execute: fails
        update1 = _make_update("go")
        with patch("src.bot.asyncio.to_thread", return_value=_fail_result()):
            await bot.handle_message(update1, MagicMock())
        assert bot.state == BotState.FAILED

        # Retry
        update2 = _make_update("retry")
        step = _make_step()
        with patch("src.bot.asyncio.to_thread", return_value=_success_result(step)):
            await bot.handle_message(update2, MagicMock())
        assert bot.state == BotState.AWAITING_COMMIT

        # Commit
        update3 = _make_update("commit")
        with patch("src.bot.asyncio.to_thread", return_value=None):
            await bot.handle_message(update3, MagicMock())
        assert bot.state == BotState.IDLE

    @pytest.mark.asyncio
    async def test_failure_then_skip(self, tmp_path: Path, forge_config) -> None:
        """Execute fails → 'skip' discards changes → idle."""
        bot = _make_bot(tmp_path, BotState.FAILED, forge_config)
        update = _make_update("skip")
        with patch("src.bot.abandon_step") as mock_abandon:
            await bot.handle_message(update, MagicMock())
        mock_abandon.assert_called_once()
        assert bot.state == BotState.IDLE

    @pytest.mark.asyncio
    async def test_failure_then_stop(self, tmp_path: Path, forge_config) -> None:
        """Execute fails → 'stop' resets → idle."""
        bot = _make_bot(tmp_path, BotState.FAILED, forge_config)
        update = _make_update("stop")
        with patch("src.bot.abandon_step") as mock_abandon:
            await bot.handle_message(update, MagicMock())
        mock_abandon.assert_called_once()
        assert bot.state == BotState.IDLE


# ---------------------------------------------------------------------------
# Skip before execution + no steps
# ---------------------------------------------------------------------------


class TestBotSkipAndNoSteps:
    @pytest.mark.asyncio
    async def test_skip_before_execution(self, tmp_path: Path, forge_config) -> None:
        """Show step → user types 'skip' instead of 'go'."""
        bot = _make_bot(tmp_path, BotState.CONFIRMING, forge_config)
        update = _make_update("skip")
        with patch("src.bot.abandon_step") as mock_abandon:
            await bot.handle_message(update, MagicMock())
        mock_abandon.assert_called_once()
        assert bot.state == BotState.IDLE

    @pytest.mark.asyncio
    async def test_execute_no_steps(self, tmp_path: Path, forge_config) -> None:
        """Pipeline returns NO_STEPS → back to idle."""
        bot = _make_bot(tmp_path, BotState.CONFIRMING, forge_config)
        update = _make_update("go")
        with patch("src.bot.asyncio.to_thread", return_value=_no_steps_result()):
            await bot.handle_message(update, MagicMock())
        assert bot.state == BotState.IDLE


# ---------------------------------------------------------------------------
# State persistence across restart
# ---------------------------------------------------------------------------


class TestBotStatePersistence:
    def test_state_survives_restart(self, tmp_path: Path, forge_config) -> None:
        """Simulates a process restart: state written by bot1 is loaded by bot2."""
        state_file = tmp_path / "forge_state.json"
        state_file.write_text(json.dumps({"state": "awaiting_commit"}))

        with patch("src.bot.STATE_FILE", str(state_file)):
            bot2 = ForgeBot(forge_config)

        assert bot2.state == BotState.AWAITING_COMMIT


# ---------------------------------------------------------------------------
# Invalid replies in each state
# ---------------------------------------------------------------------------


class TestBotInvalidReplies:
    @pytest.mark.asyncio
    async def test_invalid_reply_in_confirming(
        self, tmp_path: Path, forge_config
    ) -> None:
        bot = _make_bot(tmp_path, BotState.CONFIRMING, forge_config)
        update = _make_update("what is happening")
        await bot.handle_message(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "go" in reply.lower() or "skip" in reply.lower()
        assert bot.state == BotState.CONFIRMING  # state unchanged

    @pytest.mark.asyncio
    async def test_invalid_reply_in_awaiting_commit(
        self, tmp_path: Path, forge_config
    ) -> None:
        bot = _make_bot(tmp_path, BotState.AWAITING_COMMIT, forge_config)
        update = _make_update("yes please")
        await bot.handle_message(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "commit" in reply.lower()
        assert bot.state == BotState.AWAITING_COMMIT

    @pytest.mark.asyncio
    async def test_invalid_reply_in_failed(self, tmp_path: Path, forge_config) -> None:
        bot = _make_bot(tmp_path, BotState.FAILED, forge_config)
        update = _make_update("dunno")
        await bot.handle_message(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "retry" in reply.lower()
        assert bot.state == BotState.FAILED
