"""Telegram bot interface for Forge pipeline.

Commands:
  /next  — Show next step and ask for confirmation
  /skip  — Skip current step
  /status — Show pipeline status
  /reset — Reset uncommitted changes

Replies during execution:
  "go"      — Start executing the shown step
  "commit"  — Commit successful step
  "retry"   — Retry failed step
  "skip"    — Skip failed step and move on
  "stop"    — Abandon and reset changes
"""

import asyncio
import json
import logging
import os
from enum import Enum
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.config import ForgeConfig
from src.memory import ensure_memory_bank, find_next_step
from src.pipeline import (
    StepResult,
    StepStatus,
    abandon_step,
    execute_step,
    finalize_step,
)

logger = logging.getLogger(__name__)


class BotState(Enum):
    IDLE = "idle"
    CONFIRMING = "confirming"  # Showed step, waiting for "go"
    EXECUTING = "executing"  # Pipeline running
    AWAITING_COMMIT = "awaiting_commit"  # Success, waiting for "commit"
    FAILED = "failed"  # Failed, waiting for decision


STATE_FILE = "forge_state.json"


class ForgeBot:
    def __init__(self, cfg: ForgeConfig):
        self.cfg = cfg
        self.state = BotState.IDLE
        self.current_result: StepResult | None = None
        self._load_state()

    def _load_state(self) -> None:
        """Load persistent state from disk."""
        state_path = Path(STATE_FILE)
        if state_path.exists():
            try:
                data = json.loads(state_path.read_text())
                self.state = BotState(data.get("state", "idle"))
            except (json.JSONDecodeError, ValueError):
                self.state = BotState.IDLE

    def _save_state(self) -> None:
        """Persist state to disk."""
        state_path = Path(STATE_FILE)
        state_path.write_text(json.dumps({"state": self.state.value}))
        os.chmod(state_path, 0o600)

    def _set_state(self, state: BotState) -> None:
        self.state = state
        self._save_state()

    async def _send(self, update: Update, text: str) -> None:
        """Send a message, splitting if too long for Telegram."""
        max_len = 4000  # Telegram limit is 4096
        if len(text) <= max_len:
            await update.message.reply_text(text)
        else:
            # Split into chunks
            for i in range(0, len(text), max_len):
                await update.message.reply_text(text[i:i + max_len])

    async def cmd_next(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show the next step and ask for confirmation."""
        if self.state == BotState.EXECUTING:
            await self._send(update, "⏳ Pipeline is already running. Wait for it to finish.")
            return

        if self.state == BotState.AWAITING_COMMIT:
            await self._send(update, "📦 There's a completed step waiting for your commit. Reply 'commit' or 'stop'.")
            return

        step = find_next_step(self.cfg.memory_path, self.cfg.unchecked_pattern)
        if not step:
            await self._send(update, "✅ All steps complete! Nothing left in the roadmap.")
            return

        self._set_state(BotState.CONFIRMING)
        await self._send(
            update,
            f"📋 Next step:\n\n"
            f"**Step {step.step_id}:** {step.description}\n\n"
            f"Reply 'go' to start or 'skip' to skip this step.",
        )

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show current pipeline status."""
        step = find_next_step(self.cfg.memory_path, self.cfg.unchecked_pattern)
        step_info = f"Step {step.step_id}: {step.description}" if step else "All steps complete"

        await self._send(
            update,
            f"🔧 Forge Status\n\n"
            f"State: {self.state.value}\n"
            f"Next: {step_info}\n"
            f"Coder: {self.cfg.models.coder}\n"
            f"Reviewer: {self.cfg.models.senior_reviewer}",
        )

    async def cmd_skip(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Skip the current step."""
        if self.state in (BotState.CONFIRMING, BotState.FAILED):
            abandon_step(self.cfg)
            self._set_state(BotState.IDLE)
            await self._send(update, "⏭️ Step skipped. Changes reset. Reply /next for the next step.")
        else:
            await self._send(update, "Nothing to skip right now.")

    async def cmd_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Reset all uncommitted changes and return to idle."""
        abandon_step(self.cfg)
        self._set_state(BotState.IDLE)
        await self._send(update, "🔄 All uncommitted changes reset. Back to idle.")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle free-text replies based on current state."""
        text = update.message.text.strip().lower()

        if self.state == BotState.CONFIRMING:
            if text == "go":
                await self._execute(update)
            elif text == "skip":
                await self.cmd_skip(update, context)
            else:
                await self._send(update, "Reply 'go' to start or 'skip' to skip.")

        elif self.state == BotState.AWAITING_COMMIT:
            if text == "commit":
                await self._commit(update)
            elif text in ("stop", "reset"):
                await self.cmd_reset(update, context)
            else:
                await self._send(update, "Reply 'commit' to save or 'stop' to discard.")

        elif self.state == BotState.FAILED:
            if text == "retry":
                await self._execute(update)
            elif text in ("skip", "next"):
                abandon_step(self.cfg)
                self._set_state(BotState.IDLE)
                await self._send(update, "⏭️ Skipped. Reply /next for the next step.")
            elif text in ("stop", "reset"):
                await self.cmd_reset(update, context)
            else:
                await self._send(update, "Reply 'retry', 'skip', or 'stop'.")

        elif self.state == BotState.EXECUTING:
            await self._send(update, "⏳ Pipeline is running. Please wait.")

        else:
            await self._send(update, "Reply /next to start, or /status to check.")

    async def _execute(self, update: Update) -> None:
        """Run the pipeline for the current step."""
        self._set_state(BotState.EXECUTING)
        await self._send(update, "🚀 Starting... I'll notify you when done.")

        try:
            result = await asyncio.to_thread(execute_step, self.cfg)
        except Exception as e:
            logger.exception("Pipeline execution failed")
            self._set_state(BotState.FAILED)
            await self._send(update, "💥 Pipeline crashed. Check forge.log for details.\n\nReply 'retry' or 'skip'.")
            return

        self.current_result = result

        if result.status == StepStatus.SUCCESS:
            self._set_state(BotState.AWAITING_COMMIT)

            # Build a useful notification
            msg = (
                f"{result.summary}\n\n"
                f"Senior review:\n{_truncate(result.details, 1500)}\n\n"
                f"Reply 'commit' to save or 'stop' to discard."
            )
            await self._send(update, msg)

        elif result.status == StepStatus.NO_STEPS:
            self._set_state(BotState.IDLE)
            await self._send(update, "✅ All steps complete!")

        else:
            self._set_state(BotState.FAILED)
            msg = (
                f"❌ {result.summary}\n\n"
                f"Details:\n{_truncate(result.details, 1500)}\n\n"
                f"Reply 'retry', 'skip', or 'stop'."
            )
            await self._send(update, msg)

    async def _commit(self, update: Update) -> None:
        """Finalize and commit the successful step."""
        if not self.current_result or self.current_result.status != StepStatus.SUCCESS:
            await self._send(update, "Nothing to commit.")
            return

        await self._send(update, "📦 Committing and updating memory bank...")

        try:
            await asyncio.to_thread(finalize_step, self.cfg, self.current_result)
            step = self.current_result.step
            self._set_state(BotState.IDLE)
            self.current_result = None
            await self._send(
                update,
                f"✅ Step {step.step_id} committed and memory bank updated.\n\n"
                f"Reply /next for the next step.",
            )
        except Exception as e:
            logger.exception("Finalization failed")
            await self._send(update, "💥 Commit failed. Check forge.log for details.\n\nReply 'retry' or 'stop'.")


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\n... [truncated]"


def run_bot(cfg: ForgeConfig) -> None:
    """Start the Telegram bot."""
    ensure_memory_bank(cfg.memory_path)

    bot = ForgeBot(cfg)
    app = Application.builder().token(cfg.telegram.bot_token).build()

    # Only respond to messages from the configured chat ID and user ID
    user_filter = filters.Chat(chat_id=int(cfg.telegram.chat_id)) & filters.User(user_id=int(cfg.telegram.chat_id))

    app.add_handler(CommandHandler("next", bot.cmd_next, filters=user_filter))
    app.add_handler(CommandHandler("status", bot.cmd_status, filters=user_filter))
    app.add_handler(CommandHandler("skip", bot.cmd_skip, filters=user_filter))
    app.add_handler(CommandHandler("reset", bot.cmd_reset, filters=user_filter))
    app.add_handler(MessageHandler(user_filter & filters.TEXT, bot.handle_message))

    logger.info("Forge bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
