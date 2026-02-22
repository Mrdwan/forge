"""Shared fixtures for Forge tests."""

from pathlib import Path

import pytest

from src.config import (
    ForgeConfig,
    ModelsConfig,
    PipelineConfig,
    PreCommitConfig,
    TelegramConfig,
)
from src.memory import Step


@pytest.fixture
def memory_path(tmp_path: Path) -> Path:
    """Create a temp memory bank with all 5 files pre-populated."""
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "ARCHITECTURE.md").write_text("# Architecture\n\nSystem description.\n")
    (mem / "ROADMAP.md").write_text(
        "# Roadmap\n\n"
        "- [ ] Step 1.1: Build the first thing\n"
        "- [ ] Step 1.2: Build the second thing\n"
    )
    (mem / "DECISIONS.md").write_text("# Decisions\n\nSome decisions.\n")
    (mem / "PROGRESS.md").write_text("# Progress\n\nInitial state.\n")
    (mem / "CHANGELOG.md").write_text("# Changelog\n")
    return mem


@pytest.fixture
def sample_step() -> Step:
    """A simple Step dataclass instance."""
    return Step(
        step_id="1.1",
        description="Build the first thing",
        raw_line="- [ ] Step 1.1: Build the first thing",
    )


@pytest.fixture
def forge_config(tmp_path: Path, memory_path: Path) -> ForgeConfig:
    """Minimal ForgeConfig pointing at tmp_path."""
    cfg = ForgeConfig()
    cfg.project_path = tmp_path
    cfg.memory_dir = "memory"
    cfg.models = ModelsConfig(
        coder="test/coder-model",
        coder_fallback="test/fallback-model",
        junior_reviewer="test/junior-model",
        senior_reviewer="test/senior-model",
        context_updater="test/updater-model",
    )
    cfg.telegram = TelegramConfig(bot_token="fake-token", chat_id="12345")
    cfg.pipeline = PipelineConfig(
        max_hook_retries=3,
        max_junior_retries=3,
        max_senior_rounds=2,
        aider_timeout=30,
    )
    cfg.pre_commit = PreCommitConfig(commands=["echo ok"])
    return cfg


@pytest.fixture
def state_file(tmp_path: Path) -> Path:
    """A temporary state JSON file path."""
    return tmp_path / "forge_state.json"
