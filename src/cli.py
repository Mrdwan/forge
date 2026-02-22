"""Command-line interface for Forge pipeline.

Mirrors all Telegram commands so you can control Forge from your terminal.
When TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set (via .env / config),
every significant action and result is also sent to your Telegram chat.

Usage:
    python -m src next      # show next step, then interactively run it
    python -m src status    # print current state and next step
    python -m src skip      # skip the current queued step
    python -m src reset     # discard all uncommitted changes

Interactive prompts (after `next` shows a step):
    go      → start pipeline execution
    skip    → skip the step

After pipeline succeeds:
    commit  → commit and update memory bank
    stop    → discard changes

After pipeline fails:
    retry   → re-run the same step
    skip    → discard changes and move on
    stop    → discard changes and go idle
"""

import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from src.bot import BotState, STATE_FILE
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

COMMANDS = {"next", "status", "skip", "reset"}


# ---------------------------------------------------------------------------
# Telegram helper — synchronous, fire-and-forget
# ---------------------------------------------------------------------------


def notify_telegram(cfg: ForgeConfig, text: str) -> None:
    """Send *text* to Telegram via the Bot API (sync HTTP POST).

    Silently swallows errors so a Telegram outage never breaks the CLI flow.
    """
    token = cfg.telegram.bot_token
    chat_id = cfg.telegram.chat_id
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({"chat_id": chat_id, "text": text}).encode()
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Telegram notify failed: %s", exc)


# ---------------------------------------------------------------------------
# Shared state helpers (share the same forge_state.json as the Telegram bot)
# ---------------------------------------------------------------------------


def _load_state() -> BotState:
    path = Path(STATE_FILE)
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return BotState(data.get("state", "idle"))
        except (json.JSONDecodeError, ValueError):
            pass
    return BotState.IDLE


def _save_state(state: BotState) -> None:
    path = Path(STATE_FILE)
    path.write_text(json.dumps({"state": state.value}))
    os.chmod(path, 0o600)


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


def cmd_status(cfg: ForgeConfig) -> None:
    """Print the current pipeline state and next step."""
    state = _load_state()
    step = find_next_step(cfg.memory_path, cfg.unchecked_pattern)
    step_info = (
        f"Step {step.step_id}: {step.description}" if step else "All steps complete"
    )

    print("\n🔧 Forge Status")
    print(f"  State : {state.value}")
    print(f"  Next  : {step_info}")
    print(f"  Coder : {cfg.models.coder}")
    print(f"  Senior: {cfg.models.senior_reviewer}\n")


def cmd_skip(cfg: ForgeConfig, *, notify: bool = True) -> None:
    """Skip the current step and reset uncommitted changes."""
    state = _load_state()
    if state in (BotState.CONFIRMING, BotState.FAILED):
        abandon_step(cfg)
        _save_state(BotState.IDLE)
        msg = "⏭️ Step skipped. Changes reset."
        print(msg)
        if notify:
            notify_telegram(cfg, msg)
    else:
        print(f"Nothing to skip right now (state: {state.value}).")


def cmd_reset(cfg: ForgeConfig, *, notify: bool = True) -> None:
    """Discard all uncommitted changes and return to idle."""
    abandon_step(cfg)
    _save_state(BotState.IDLE)
    msg = "🔄 All uncommitted changes reset. Back to idle."
    print(msg)
    if notify:
        notify_telegram(cfg, msg)


def cmd_next(cfg: ForgeConfig, *, notify: bool = True) -> None:
    """Show the next roadmap step and run it interactively."""
    state = _load_state()

    if state == BotState.EXECUTING:
        print("⏳ Pipeline is already running (state file shows 'executing').")
        print("   If this is stale, run: python -m src reset")
        return

    if state == BotState.AWAITING_COMMIT:
        print("📦 There is a completed step waiting for your decision.")
        _prompt_commit(cfg, result=None, notify=notify)
        return

    step = find_next_step(cfg.memory_path, cfg.unchecked_pattern)
    if not step:
        msg = "✅ All steps complete! Nothing left in the roadmap."
        print(msg)
        if notify:
            notify_telegram(cfg, msg)
        return

    print("\n📋 Next step:")
    print(f"   Step {step.step_id}: {step.description}\n")
    _save_state(BotState.CONFIRMING)

    while True:
        reply = _prompt("Type 'go' to start, 'skip' to skip: ").lower().strip()
        if reply == "go":
            _run_pipeline(cfg, notify=notify)
            return
        elif reply == "skip":
            cmd_skip(cfg, notify=notify)
            return
        else:
            print("  Please type 'go' or 'skip'.")


# ---------------------------------------------------------------------------
# Internal pipeline helpers
# ---------------------------------------------------------------------------


def _run_pipeline(cfg: ForgeConfig, *, notify: bool) -> None:
    """Execute the pipeline step, then handle the result interactively."""
    _save_state(BotState.EXECUTING)
    print("\n🚀 Starting pipeline... (this may take a while)\n")

    if notify:
        step = find_next_step(cfg.memory_path, cfg.unchecked_pattern)
        label = f"Step {step.step_id}: {step.description}" if step else "next step"
        notify_telegram(cfg, f"⚡ CLI is running {label}...")

    try:
        result = execute_step(cfg)
    except Exception as exc:
        logger.exception("Pipeline execution crashed")
        _save_state(BotState.FAILED)
        msg = f"💥 Pipeline crashed: {exc}\n\nCheck forge.log for details."
        print(f"\n{msg}\n")
        if notify:
            notify_telegram(cfg, msg)
        return

    _handle_result(cfg, result, notify=notify)


def _handle_result(cfg: ForgeConfig, result: StepResult, *, notify: bool) -> None:
    """Print result summary and prompt for follow-up action."""
    if result.status == StepStatus.NO_STEPS:
        _save_state(BotState.IDLE)
        msg = "✅ All steps complete!"
        print(f"\n{msg}\n")
        if notify:
            notify_telegram(cfg, msg)
        return

    if result.status == StepStatus.SUCCESS:
        _save_state(BotState.AWAITING_COMMIT)
        print(f"\n{result.summary}\n")
        print("Senior review:")
        print(_truncate(result.details, 1500))
        if notify:
            tg_msg = (
                f"{result.summary}\n\n"
                f"Senior review:\n{_truncate(result.details, 800)}\n\n"
                f"Run `python -m src next` and type 'commit' or 'stop'."
            )
            notify_telegram(cfg, tg_msg)
        _prompt_commit(cfg, result=result, notify=notify)

    elif result.status == StepStatus.ERROR:
        abandon_step(cfg)
        _save_state(BotState.IDLE)
        print(f"\n❌ {result.summary}\n")
        print("Details:")
        print(_truncate(result.details, 1500))
        if notify:
            tg_msg = (
                f"💥 {result.summary}\n\n"
                f"Details:\n{_truncate(result.details, 800)}\n\n"
                f"Pipeline aborted. Changes reset."
            )
            notify_telegram(cfg, tg_msg)
        print(
            "\nPipeline aborted due to a fatal error. Uncommitted changes have been reset."
        )
        return

    else:
        _save_state(BotState.FAILED)
        print(f"\n❌ {result.summary}\n")
        print("Details:")
        print(_truncate(result.details, 1500))
        if notify:
            tg_msg = (
                f"❌ {result.summary}\n\n"
                f"Details:\n{_truncate(result.details, 800)}\n\n"
                f"Run `python -m src next` and type 'retry', 'skip', or 'stop'."
            )
            notify_telegram(cfg, tg_msg)
        _prompt_after_failure(cfg, result, notify=notify)


def _prompt_commit(
    cfg: ForgeConfig, result: StepResult | None, *, notify: bool
) -> None:
    """Ask user to commit or discard a successful step."""
    while True:
        reply = _prompt("\nType 'commit' to save, 'stop' to discard: ").lower().strip()
        if reply == "commit":
            if result is None:
                print("No pending result to commit (state is stale).")
                return
            print("\n📦 Committing and updating memory bank...")
            if notify:
                notify_telegram(cfg, "📦 Committing step and updating memory bank...")
            try:
                finalize_step(cfg, result)
                _save_state(BotState.IDLE)
                step = result.step
                msg = (
                    f"✅ Step {step.step_id} committed and memory bank updated.\n"
                    f"Run `python -m src next` for the next step."
                )
                print(f"\n{msg}\n")
                if notify:
                    notify_telegram(cfg, msg)
            except Exception as exc:
                logger.exception("Commit failed")
                msg = f"💥 Commit failed: {exc}\n\nCheck forge.log for details."
                print(f"\n{msg}\n")
                if notify:
                    notify_telegram(cfg, msg)
            return
        elif reply in ("stop", "reset"):
            cmd_reset(cfg, notify=notify)
            return
        else:
            print("  Please type 'commit' or 'stop'.")


def _prompt_after_failure(
    cfg: ForgeConfig, result: StepResult, *, notify: bool
) -> None:
    """Ask user what to do after a pipeline failure."""
    while True:
        reply = _prompt("\nType 'retry', 'skip', or 'stop': ").lower().strip()
        if reply == "retry":
            _run_pipeline(cfg, notify=notify)
            return
        elif reply == "skip":
            cmd_skip(cfg, notify=notify)
            return
        elif reply in ("stop", "reset"):
            cmd_reset(cfg, notify=notify)
            return
        else:
            print("  Please type 'retry', 'skip', or 'stop'.")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\n... [truncated]"


def _prompt(message: str) -> str:
    """Thin wrapper around input() — easy to mock in tests."""
    return input(message)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_cli(cfg: ForgeConfig, args: list[str]) -> None:
    """Dispatch a CLI command.

    Args:
        cfg:  Loaded ForgeConfig.
        args: Remaining argv after stripping the program name (e.g. ``["next"]``).
    """
    ensure_memory_bank(cfg.memory_path)

    if not args or args[0] not in COMMANDS:
        print("Usage: python -m src <command>")
        print(f"Commands: {', '.join(sorted(COMMANDS))}")
        sys.exit(1)

    cmd = args[0]
    if cmd == "status":
        cmd_status(cfg)
    elif cmd == "skip":
        cmd_skip(cfg)
    elif cmd == "reset":
        cmd_reset(cfg)
    elif cmd == "next":
        cmd_next(cfg)
