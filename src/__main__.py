"""Forge — Autonomous coding pipeline with Telegram control."""

import logging
import sys

from src.config import load_config
from src.bot import run_bot
from src.cli import COMMANDS, run_cli

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("forge.log"),
    ],
)
# Only log WARNING+ to the file to avoid leaking sensitive prompt content
logging.getLogger().handlers[1].setLevel(logging.WARNING)


def main() -> None:
    # If the first argument is a CLI sub-command, dispatch to the CLI instead
    # of starting the Telegram polling bot.
    args = sys.argv[1:]
    if args and args[0] in COMMANDS:
        config_path = "config.yaml"
        cfg = load_config(config_path)
        run_cli(cfg, args)
        return

    config_path = args[0] if args else "config.yaml"
    cfg = load_config(config_path)

    print("Forge starting")
    print(f"  Project: {cfg.project_path}")
    print(f"  Coder: {cfg.models.coder}")
    print(f"  Junior: {cfg.models.junior_reviewer}")
    print(f"  Senior: {cfg.models.senior_reviewer}")

    run_bot(cfg)


if __name__ == "__main__":  # pragma: no cover
    main()  # pragma: no cover
