"""Configuration loader for Forge pipeline.

Every setting in config.yaml can be overridden via a FORGE_* environment
variable. Priority (highest → lowest):

    1. FORGE_* environment variable
    2. config.yaml value
    3. Dataclass default (code-level fallback)

Model names are intentionally left empty by default — you MUST provide them
via config.yaml or FORGE_MODEL_* env vars. This avoids shipping outdated
model identifiers in code that are hard to update.

FORGE_* environment variable reference:

    Path / memory
    -------------
    FORGE_PROJECT_PATH          → project.path
    FORGE_MEMORY_DIR            → project.memory_dir  (default: "memory")

    Models  (use litellm format: "provider/model-name")
    ------
    FORGE_MODEL_CODER           → models.coder
    FORGE_MODEL_CODER_FALLBACK  → models.coder_fallback
    FORGE_MODEL_JUNIOR_REVIEWER → models.junior_reviewer
    FORGE_MODEL_SENIOR_REVIEWER → models.senior_reviewer
    FORGE_MODEL_CONTEXT_UPDATER → models.context_updater

    Pipeline limits
    ---------------
    FORGE_MAX_HOOK_RETRIES      → pipeline.max_hook_retries   (default: 3)
    FORGE_MAX_JUNIOR_RETRIES    → pipeline.max_junior_retries (default: 3)
    FORGE_MAX_SENIOR_ROUNDS     → pipeline.max_senior_rounds  (default: 2)
    FORGE_AIDER_TIMEOUT         → pipeline.aider_timeout      (default: 900)

    Pre-commit
    ----------
    FORGE_PRECOMMIT_COMMANDS    → pre_commit.commands
                                  Comma-separated list of shell commands.
                                  e.g. "ruff check src/,pytest tests/ -x -q"

    Roadmap patterns (Python regex)
    --------------------------------
    FORGE_UNCHECKED_PATTERN     → roadmap.unchecked_pattern
    FORGE_CHECKED_PATTERN       → roadmap.checked_pattern
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ModelsConfig:
    """Model identifiers in litellm format: "provider/model-name".

    Defaults are intentionally empty so stale model names are never
    silently shipped in code. Set via config.yaml or FORGE_MODEL_* env vars.
    """

    coder: str = ""
    coder_fallback: str = ""
    junior_reviewer: str = ""
    senior_reviewer: str = ""
    context_updater: str = ""


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
    project_path: Path = field(default_factory=lambda: Path("."))
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_env(value: str) -> str:
    """Resolve ${ENV_VAR} references embedded in YAML string values."""
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        env_var = value[2:-1]
        return os.environ.get(env_var, "")
    return value


def _env_str(env_var: str, fallback: str) -> str:
    """Return FORGE_* env var if set and non-empty, else fallback."""
    return os.environ.get(env_var) or fallback


def _env_int(env_var: str, fallback: int) -> int:
    """Return FORGE_* env var as int if set and non-empty, else fallback."""
    raw = os.environ.get(env_var, "")
    if raw.strip():
        try:
            return int(raw.strip())
        except ValueError:
            pass
    return fallback


def _env_list(env_var: str, fallback: list[str]) -> list[str]:
    """Return FORGE_* env var as comma-separated list if set, else fallback."""
    raw = os.environ.get(env_var, "")
    if raw.strip():
        return [item.strip() for item in raw.split(",") if item.strip()]
    return fallback


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------

def load_config(config_path: str = "config.yaml") -> ForgeConfig:
    """Load config from YAML, then apply FORGE_* environment variable overrides.

    Priority: FORGE_* env var > config.yaml > dataclass default.
    """
    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    cfg = ForgeConfig()

    # --- project ---
    proj = raw.get("project", {})
    yaml_path = proj.get("path", ".")
    yaml_memory_dir = proj.get("memory_dir", "memory")
    cfg.project_path = Path(_env_str("FORGE_PROJECT_PATH", yaml_path))
    cfg.memory_dir = _env_str("FORGE_MEMORY_DIR", yaml_memory_dir)

    # --- models ---
    m = raw.get("models", {})
    cfg.models = ModelsConfig(
        coder=_env_str("FORGE_MODEL_CODER", _resolve_env(m.get("coder", ""))),
        coder_fallback=_env_str("FORGE_MODEL_CODER_FALLBACK", _resolve_env(m.get("coder_fallback", ""))),
        junior_reviewer=_env_str("FORGE_MODEL_JUNIOR_REVIEWER", _resolve_env(m.get("junior_reviewer", ""))),
        senior_reviewer=_env_str("FORGE_MODEL_SENIOR_REVIEWER", _resolve_env(m.get("senior_reviewer", ""))),
        context_updater=_env_str("FORGE_MODEL_CONTEXT_UPDATER", _resolve_env(m.get("context_updater", ""))),
    )

    # --- telegram ---
    t = raw.get("telegram", {})
    cfg.telegram = TelegramConfig(
        bot_token=_resolve_env(t.get("bot_token", "")),
        chat_id=_resolve_env(t.get("chat_id", "")),
    )

    # --- pipeline ---
    p = raw.get("pipeline", {})
    cfg.pipeline = PipelineConfig(
        max_hook_retries=_env_int(
            "FORGE_MAX_HOOK_RETRIES", p.get("max_hook_retries", 3)
        ),
        max_junior_retries=_env_int(
            "FORGE_MAX_JUNIOR_RETRIES", p.get("max_junior_retries", 3)
        ),
        max_senior_rounds=_env_int(
            "FORGE_MAX_SENIOR_ROUNDS", p.get("max_senior_rounds", 2)
        ),
        aider_timeout=_env_int(
            "FORGE_AIDER_TIMEOUT", p.get("aider_timeout", 900)
        ),
    )

    # --- pre_commit ---
    pc = raw.get("pre_commit", {})
    default_commands = pc.get("commands", cfg.pre_commit.commands)
    cfg.pre_commit = PreCommitConfig(
        commands=_env_list("FORGE_PRECOMMIT_COMMANDS", default_commands),
    )

    # --- roadmap ---
    r = raw.get("roadmap", {})
    cfg.unchecked_pattern = _env_str(
        "FORGE_UNCHECKED_PATTERN",
        r.get("unchecked_pattern", cfg.unchecked_pattern),
    )
    cfg.checked_pattern = _env_str(
        "FORGE_CHECKED_PATTERN",
        r.get("checked_pattern", cfg.checked_pattern),
    )

    return cfg
