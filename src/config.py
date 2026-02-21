"""Configuration loader for Forge pipeline."""

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ModelsConfig:
    coder: str = "gemini/gemini-2.5-pro"
    coder_fallback: str = "anthropic/claude-sonnet-4-5-20250929"
    junior_reviewer: str = "deepseek/deepseek-chat"
    senior_reviewer: str = "anthropic/claude-sonnet-4-5-20250929"
    context_updater: str = "deepseek/deepseek-chat"


@dataclass
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""


@dataclass
class PipelineConfig:
    max_hook_retries: int = 3
    max_junior_retries: int = 3
    max_senior_rounds: int = 2
    aider_timeout: int = 900


@dataclass
class PreCommitConfig:
    commands: list[str] = field(default_factory=lambda: [
        "ruff check src/",
        "mypy src/ --config-file mypy.ini",
        "pytest tests/ -x -q --tb=short",
    ])


@dataclass
class ForgeConfig:
    project_path: Path = Path(".")
    memory_dir: str = "memory"
    models: ModelsConfig = field(default_factory=ModelsConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    pre_commit: PreCommitConfig = field(default_factory=PreCommitConfig)
    unchecked_pattern: str = r'^\s*-\s*\[ \]\s*\*{0,2}Step\s+(\d+\.\d+):?\*{0,2}\s*(.*)'
    checked_pattern: str = r'^\s*-\s*\[x\]\s*\*{0,2}Step\s+(\d+\.\d+):?\*{0,2}\s*(.*)'

    @property
    def memory_path(self) -> Path:
        return self.project_path / self.memory_dir


def _resolve_env(value: str) -> str:
    """Resolve ${ENV_VAR} references in config values."""
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        env_var = value[2:-1]
        return os.environ.get(env_var, "")
    return value


def load_config(config_path: str = "config.yaml") -> ForgeConfig:
    """Load config from YAML file, resolving environment variables."""
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    cfg = ForgeConfig()

    if "project" in raw:
        cfg.project_path = Path(raw["project"].get("path", "."))
        cfg.memory_dir = raw["project"].get("memory_dir", "memory")

    if "models" in raw:
        m = raw["models"]
        cfg.models = ModelsConfig(
            coder=m.get("coder", cfg.models.coder),
            coder_fallback=m.get("coder_fallback", cfg.models.coder_fallback),
            junior_reviewer=m.get("junior_reviewer", cfg.models.junior_reviewer),
            senior_reviewer=m.get("senior_reviewer", cfg.models.senior_reviewer),
            context_updater=m.get("context_updater", cfg.models.context_updater),
        )

    if "telegram" in raw:
        t = raw["telegram"]
        cfg.telegram = TelegramConfig(
            bot_token=_resolve_env(t.get("bot_token", "")),
            chat_id=_resolve_env(t.get("chat_id", "")),
        )

    if "pipeline" in raw:
        p = raw["pipeline"]
        cfg.pipeline = PipelineConfig(
            max_hook_retries=p.get("max_hook_retries", 3),
            max_junior_retries=p.get("max_junior_retries", 3),
            max_senior_rounds=p.get("max_senior_rounds", 2),
            aider_timeout=p.get("aider_timeout", 900),
        )

    if "pre_commit" in raw:
        cfg.pre_commit = PreCommitConfig(
            commands=raw["pre_commit"].get("commands", cfg.pre_commit.commands),
        )

    if "roadmap" in raw:
        r = raw["roadmap"]
        cfg.unchecked_pattern = r.get("unchecked_pattern", cfg.unchecked_pattern)
        cfg.checked_pattern = r.get("checked_pattern", cfg.checked_pattern)

    return cfg
