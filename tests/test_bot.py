"""Unit tests for src/bot.py."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot import BotState, ForgeBot, _truncate, run_bot
from src.config import ForgeConfig
from src.pipeline import StepResult, StepStatus
from src.memory import Step


def _make_update(text: str = "go") -> MagicMock:
    update = MagicMock()
    update.message = AsyncMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def _make_step() -> Step:
    return Step("1.1", "Build first thing", "- [ ] Step 1.1: Build first thing")


def _success_result() -> StepResult:
    return StepResult(
        status=StepStatus.SUCCESS,
        step=_make_step(),
        summary="✅ Step 1.1: Build first thing",
        details="VERDICT: PASS\n\nSUMMARY: Good work.",
    )


def _fail_result() -> StepResult:
    return StepResult(
        status=StepStatus.FAILED,
        step=_make_step(),
        summary="❌ Step 1.1 failed",
        details="Tests failed.",
    )


def _no_steps_result() -> StepResult:
    return StepResult(
        status=StepStatus.NO_STEPS,
        step=None,
        summary="All steps complete!",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestTruncate:
    def test_short_string_unchanged(self) -> None:
        assert _truncate("hello", 100) == "hello"

    def test_long_string_truncated(self) -> None:
        result = _truncate("x" * 200, 100)
        assert len(result) > 100  # includes "... [truncated]"
        assert "truncated" in result
        assert result.startswith("x" * 100)


# ---------------------------------------------------------------------------
# ForgeBot state persistence
# ---------------------------------------------------------------------------

class TestForgeBotStatePersistence:
    def test_loads_idle_state_when_no_file(self, tmp_path: Path, forge_config: ForgeConfig) -> None:
        with patch("src.bot.Path") as mock_path_cls:
            mock_path_cls.return_value.exists.return_value = False
            bot = ForgeBot(forge_config)
        assert bot.state == BotState.IDLE

    def test_loads_state_from_valid_file(self, tmp_path: Path, forge_config: ForgeConfig) -> None:
        state_path = tmp_path / "forge_state.json"
        state_path.write_text(json.dumps({"state": "confirming"}))
        with patch("src.bot.STATE_FILE", str(state_path)):
            bot = ForgeBot(forge_config)
        assert bot.state == BotState.CONFIRMING

    def test_corrupted_state_file_defaults_to_idle(self, tmp_path: Path, forge_config: ForgeConfig) -> None:
        state_path = tmp_path / "forge_state.json"
        state_path.write_text("not valid json {{{{")
        with patch("src.bot.STATE_FILE", str(state_path)):
            bot = ForgeBot(forge_config)
        assert bot.state == BotState.IDLE

    def test_invalid_state_value_defaults_to_idle(self, tmp_path: Path, forge_config: ForgeConfig) -> None:
        state_path = tmp_path / "forge_state.json"
        state_path.write_text(json.dumps({"state": "nonexistent_state"}))
        with patch("src.bot.STATE_FILE", str(state_path)):
            bot = ForgeBot(forge_config)
        assert bot.state == BotState.IDLE

    def test_save_state_writes_json(self, tmp_path: Path, forge_config: ForgeConfig) -> None:
        state_path = tmp_path / "forge_state.json"
        with patch("src.bot.STATE_FILE", str(state_path)):
            bot = ForgeBot(forge_config)
            bot._set_state(BotState.EXECUTING)

        data = json.loads(state_path.read_text())
        assert data["state"] == "executing"


# ---------------------------------------------------------------------------
# _send
# ---------------------------------------------------------------------------

class TestSend:
    @pytest.mark.asyncio
    async def test_short_message_sent_once(self, forge_config: ForgeConfig) -> None:
        state_path_str = "/tmp/test_state.json"
        with patch("src.bot.STATE_FILE", state_path_str), \
             patch("src.bot.Path") as mock_path_cls:
            mock_path_cls.return_value.exists.return_value = False
            bot = ForgeBot(forge_config)

        update = _make_update()
        await bot._send(update, "Hello!")
        update.message.reply_text.assert_awaited_once_with("Hello!")

    @pytest.mark.asyncio
    async def test_long_message_split_into_chunks(self, forge_config: ForgeConfig) -> None:
        with patch("src.bot.STATE_FILE", "/tmp/test_state2.json"), \
             patch("src.bot.Path") as mock_path_cls:
            mock_path_cls.return_value.exists.return_value = False
            bot = ForgeBot(forge_config)

        update = _make_update()
        long_msg = "A" * 8100
        await bot._send(update, long_msg)
        # 8100 / 4000 = 3 chunks
        assert update.message.reply_text.await_count >= 2


# We'll use a context manager helper to create a bot with mocked state file
def _make_bot(forge_config: ForgeConfig, state: BotState = BotState.IDLE) -> ForgeBot:
    with patch("src.bot.STATE_FILE", "/tmp/forge_test_state.json"), \
         patch("src.bot.Path") as mock_path_cls:
        mock_path_cls.return_value.exists.return_value = False
        bot = ForgeBot(forge_config)
    bot.state = state
    bot._save_state = MagicMock()  # prevent actual file writes
    return bot


# ---------------------------------------------------------------------------
# cmd_next
# ---------------------------------------------------------------------------

class TestCmdNext:
    @pytest.mark.asyncio
    async def test_while_executing_sends_busy_message(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.EXECUTING)
        update = _make_update()
        await bot.cmd_next(update, MagicMock())
        update.message.reply_text.assert_awaited_once()
        assert "running" in update.message.reply_text.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_while_awaiting_commit_sends_commit_message(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.AWAITING_COMMIT)
        update = _make_update()
        await bot.cmd_next(update, MagicMock())
        update.message.reply_text.assert_awaited_once()
        assert "commit" in update.message.reply_text.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_no_steps_left(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.IDLE)
        update = _make_update()
        with patch("src.bot.find_next_step", return_value=None):
            await bot.cmd_next(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "complete" in reply.lower() or "nothing" in reply.lower()

    @pytest.mark.asyncio
    async def test_shows_next_step_and_transitions_to_confirming(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.IDLE)
        update = _make_update()
        with patch("src.bot.find_next_step", return_value=_make_step()):
            await bot.cmd_next(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "1.1" in reply
        assert bot.state == BotState.CONFIRMING


# ---------------------------------------------------------------------------
# cmd_status
# ---------------------------------------------------------------------------

class TestCmdStatus:
    @pytest.mark.asyncio
    async def test_shows_status(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.IDLE)
        update = _make_update()
        with patch("src.bot.find_next_step", return_value=_make_step()):
            await bot.cmd_status(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "idle" in reply.lower()
        assert "1.1" in reply

    @pytest.mark.asyncio
    async def test_shows_all_complete_when_no_steps(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.IDLE)
        update = _make_update()
        with patch("src.bot.find_next_step", return_value=None):
            await bot.cmd_status(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "complete" in reply.lower()


# ---------------------------------------------------------------------------
# cmd_skip
# ---------------------------------------------------------------------------

class TestCmdSkip:
    @pytest.mark.asyncio
    async def test_skip_in_confirming(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.CONFIRMING)
        update = _make_update()
        with patch("src.bot.abandon_step") as mock_abandon:
            await bot.cmd_skip(update, MagicMock())
        mock_abandon.assert_called_once()
        assert bot.state == BotState.IDLE

    @pytest.mark.asyncio
    async def test_skip_in_failed(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.FAILED)
        update = _make_update()
        with patch("src.bot.abandon_step") as mock_abandon:
            await bot.cmd_skip(update, MagicMock())
        mock_abandon.assert_called_once()

    @pytest.mark.asyncio
    async def test_skip_in_idle_sends_nothing_to_skip(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.IDLE)
        update = _make_update()
        await bot.cmd_skip(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "nothing" in reply.lower() or "skip" in reply.lower()


# ---------------------------------------------------------------------------
# cmd_reset
# ---------------------------------------------------------------------------

class TestCmdReset:
    @pytest.mark.asyncio
    async def test_reset_calls_abandon_and_goes_idle(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.EXECUTING)
        update = _make_update()
        with patch("src.bot.abandon_step") as mock_abandon:
            await bot.cmd_reset(update, MagicMock())
        mock_abandon.assert_called_once()
        assert bot.state == BotState.IDLE


# ---------------------------------------------------------------------------
# handle_message — all states
# ---------------------------------------------------------------------------

class TestHandleMessage:
    @pytest.mark.asyncio
    async def test_confirming_go_starts_execute(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.CONFIRMING)
        update = _make_update("go")
        with patch.object(bot, "_execute", new_callable=AsyncMock) as mock_exec:
            await bot.handle_message(update, MagicMock())
        mock_exec.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_confirming_skip_calls_cmd_skip(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.CONFIRMING)
        update = _make_update("skip")
        with patch.object(bot, "cmd_skip", new_callable=AsyncMock) as mock_skip:
            await bot.handle_message(update, MagicMock())
        mock_skip.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_confirming_unknown_sends_hint(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.CONFIRMING)
        update = _make_update("what?")
        await bot.handle_message(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "go" in reply.lower()

    @pytest.mark.asyncio
    async def test_awaiting_commit_commit_triggers_commit(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.AWAITING_COMMIT)
        update = _make_update("commit")
        with patch.object(bot, "_commit", new_callable=AsyncMock) as mock_commit:
            await bot.handle_message(update, MagicMock())
        mock_commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_awaiting_commit_stop_resets(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.AWAITING_COMMIT)
        update = _make_update("stop")
        with patch.object(bot, "cmd_reset", new_callable=AsyncMock) as mock_reset:
            await bot.handle_message(update, MagicMock())
        mock_reset.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_awaiting_commit_reset_resets(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.AWAITING_COMMIT)
        update = _make_update("reset")
        with patch.object(bot, "cmd_reset", new_callable=AsyncMock) as mock_reset:
            await bot.handle_message(update, MagicMock())
        mock_reset.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_awaiting_commit_unknown_sends_hint(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.AWAITING_COMMIT)
        update = _make_update("hmm")
        await bot.handle_message(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "commit" in reply.lower()

    @pytest.mark.asyncio
    async def test_failed_retry_calls_execute(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.FAILED)
        update = _make_update("retry")
        with patch.object(bot, "_execute", new_callable=AsyncMock) as mock_exec:
            await bot.handle_message(update, MagicMock())
        mock_exec.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_failed_skip_abandons_step(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.FAILED)
        update = _make_update("skip")
        with patch("src.bot.abandon_step") as mock_abandon:
            await bot.handle_message(update, MagicMock())
        mock_abandon.assert_called_once()

    @pytest.mark.asyncio
    async def test_failed_next_abandons_step(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.FAILED)
        update = _make_update("next")
        with patch("src.bot.abandon_step") as mock_abandon:
            await bot.handle_message(update, MagicMock())
        mock_abandon.assert_called_once()

    @pytest.mark.asyncio
    async def test_failed_stop_resets(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.FAILED)
        update = _make_update("stop")
        with patch.object(bot, "cmd_reset", new_callable=AsyncMock) as mock_reset:
            await bot.handle_message(update, MagicMock())
        mock_reset.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_failed_unknown_sends_hint(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.FAILED)
        update = _make_update("please help")
        await bot.handle_message(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "retry" in reply.lower()

    @pytest.mark.asyncio
    async def test_executing_sends_wait_message(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.EXECUTING)
        update = _make_update("go")
        await bot.handle_message(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "running" in reply.lower() or "wait" in reply.lower()

    @pytest.mark.asyncio
    async def test_idle_sends_hint(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.IDLE)
        update = _make_update("hello")
        await bot.handle_message(update, MagicMock())
        reply = update.message.reply_text.call_args[0][0]
        assert "/next" in reply or "next" in reply.lower()


# ---------------------------------------------------------------------------
# _execute
# ---------------------------------------------------------------------------

class TestExecute:
    @pytest.mark.asyncio
    async def test_success_path(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.CONFIRMING)
        update = _make_update()
        with patch("src.bot.asyncio.to_thread", return_value=_success_result()):
            await bot._execute(update)
        assert bot.state == BotState.AWAITING_COMMIT
        assert bot.current_result is not None

    @pytest.mark.asyncio
    async def test_no_steps_path(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.CONFIRMING)
        update = _make_update()
        with patch("src.bot.asyncio.to_thread", return_value=_no_steps_result()):
            await bot._execute(update)
        assert bot.state == BotState.IDLE

    @pytest.mark.asyncio
    async def test_failure_path(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.CONFIRMING)
        update = _make_update()
        with patch("src.bot.asyncio.to_thread", return_value=_fail_result()):
            await bot._execute(update)
        assert bot.state == BotState.FAILED

    @pytest.mark.asyncio
    async def test_exception_path(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.CONFIRMING)
        update = _make_update()
        with patch("src.bot.asyncio.to_thread", side_effect=RuntimeError("crash")):
            await bot._execute(update)
        assert bot.state == BotState.FAILED
        reply = update.message.reply_text.call_args[0][0]
        assert "crashed" in reply.lower() or "pipeline" in reply.lower()


# ---------------------------------------------------------------------------
# _commit
# ---------------------------------------------------------------------------

class TestCommit:
    @pytest.mark.asyncio
    async def test_happy_path(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.AWAITING_COMMIT)
        bot.current_result = _success_result()
        update = _make_update()
        with patch("src.bot.asyncio.to_thread", return_value=None):
            await bot._commit(update)
        assert bot.state == BotState.IDLE
        assert bot.current_result is None

    @pytest.mark.asyncio
    async def test_nothing_to_commit(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.AWAITING_COMMIT)
        bot.current_result = None
        update = _make_update()
        await bot._commit(update)
        reply = update.message.reply_text.call_args[0][0]
        assert "nothing" in reply.lower() or "commit" in reply.lower()

    @pytest.mark.asyncio
    async def test_wrong_status_nothing_to_commit(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.AWAITING_COMMIT)
        bot.current_result = _fail_result()  # status is FAILED, not SUCCESS
        update = _make_update()
        await bot._commit(update)
        reply = update.message.reply_text.call_args[0][0]
        assert "nothing" in reply.lower() or "commit" in reply.lower()

    @pytest.mark.asyncio
    async def test_finalize_exception(self, forge_config: ForgeConfig) -> None:
        bot = _make_bot(forge_config, BotState.AWAITING_COMMIT)
        bot.current_result = _success_result()
        update = _make_update()
        with patch("src.bot.asyncio.to_thread", side_effect=RuntimeError("disk full")):
            await bot._commit(update)
        reply = update.message.reply_text.call_args[0][0]
        assert "failed" in reply.lower() or "commit" in reply.lower()


# ---------------------------------------------------------------------------
# run_bot
# ---------------------------------------------------------------------------

class TestRunBot:
    def test_registers_all_handlers_and_starts_polling(self, forge_config: ForgeConfig) -> None:
        mock_app = MagicMock()
        mock_builder = MagicMock()
        mock_builder.token.return_value.build.return_value = mock_app

        with (
            patch("src.bot.ensure_memory_bank"),
            patch("src.bot.Application") as mock_application_cls,
            patch("src.bot.STATE_FILE", "/tmp/run_bot_state.json"),
            patch("src.bot.Path") as mock_path_cls,
        ):
            mock_application_cls.builder.return_value = mock_builder
            mock_path_cls.return_value.exists.return_value = False
            run_bot(forge_config)

        # 4 CommandHandlers + 1 MessageHandler = 5 handler registrations
        assert mock_app.add_handler.call_count == 5
        mock_app.run_polling.assert_called_once()
