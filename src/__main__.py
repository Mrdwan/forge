"""Forge — Autonomous coding pipeline with Telegram control."""

import logging
import sys

from src.config import load_config
from src.bot import run_bot

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
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    cfg = load_config(config_path)

    print(f"Forge starting")
    print(f"  Project: {cfg.project_path}")
    print(f"  Coder: {cfg.models.coder}")
    print(f"  Junior: {cfg.models.junior_reviewer}")
    print(f"  Senior: {cfg.models.senior_reviewer}")

    run_bot(cfg)


if __name__ == "__main__":
    main()
