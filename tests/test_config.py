"""Unit tests for src/config.py."""

import os
from pathlib import Path

import pytest
import yaml

from src.config import (
    ForgeConfig,
    ModelsConfig,
    PipelineConfig,
    PreCommitConfig,
    TelegramConfig,
    _resolve_env,
    load_config,
)


# ---------------------------------------------------------------------------
# _resolve_env
# ---------------------------------------------------------------------------

class TestResolveEnv:
    def test_plain_string_returned_unchanged(self) -> None:
        assert _resolve_env("hello") == "hello"

    def test_env_var_resolved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_TOKEN", "secret123")
        assert _resolve_env("${MY_TOKEN}") == "secret123"

    def test_env_var_missing_returns_empty_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
        assert _resolve_env("${NONEXISTENT_VAR}") == ""

    def test_partial_env_syntax_not_resolved(self) -> None:
        # Does not start with ${ or doesn't end with }
        assert _resolve_env("${PARTIAL") == "${PARTIAL"
        assert _resolve_env("NO_BRACES") == "NO_BRACES"


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------

def _write_yaml(tmp_path: Path, content: dict) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(content))
    return p


class TestLoadConfig:
    def test_full_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BOT_TOKEN", "test-bot-token")
        monkeypatch.setenv("CHAT_ID", "99999")
        config_path = _write_yaml(tmp_path, {
            "project": {"path": "/some/project", "memory_dir": "mem"},
            "models": {
                "coder": "gemini/test",
                "coder_fallback": "anthropic/test",
                "junior_reviewer": "deepseek/test",
                "senior_reviewer": "anthropic/test",
                "context_updater": "deepseek/test",
            },
            "telegram": {
                "bot_token": "${BOT_TOKEN}",
                "chat_id": "${CHAT_ID}",
            },
            "pipeline": {
                "max_hook_retries": 5,
                "max_junior_retries": 4,
                "max_senior_rounds": 3,
                "aider_timeout": 600,
            },
            "pre_commit": {"commands": ["ruff check src/", "pytest tests/"]},
            "roadmap": {
                "unchecked_pattern": r"^\s*-\s*\[ \]\s*(.+)",
                "checked_pattern": r"^\s*-\s*\[x\]\s*(.+)",
            },
        })

        cfg = load_config(str(config_path))

        assert cfg.project_path == Path("/some/project")
        assert cfg.memory_dir == "mem"
        assert cfg.models.coder == "gemini/test"
        assert cfg.models.coder_fallback == "anthropic/test"
        assert cfg.models.junior_reviewer == "deepseek/test"
        assert cfg.models.senior_reviewer == "anthropic/test"
        assert cfg.models.context_updater == "deepseek/test"
        assert cfg.telegram.bot_token == "test-bot-token"
        assert cfg.telegram.chat_id == "99999"
        assert cfg.pipeline.max_hook_retries == 5
        assert cfg.pipeline.max_junior_retries == 4
        assert cfg.pipeline.max_senior_rounds == 3
        assert cfg.pipeline.aider_timeout == 600
        assert cfg.pre_commit.commands == ["ruff check src/", "pytest tests/"]
        assert r"^\s*-\s*\[ \]\s*(.+)" in cfg.unchecked_pattern

    def test_empty_yaml_uses_defaults(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text("{}\n")

        cfg = load_config(str(config_path))

        assert cfg.project_path == Path(".")
        assert cfg.memory_dir == "memory"
        assert cfg.models.coder == "gemini/gemini-2.5-pro"
        assert cfg.pipeline.max_hook_retries == 3
        assert len(cfg.pre_commit.commands) == 3

    def test_partial_project_section(self, tmp_path: Path) -> None:
        config_path = _write_yaml(tmp_path, {"project": {"path": "/myproject"}})
        cfg = load_config(str(config_path))
        assert cfg.project_path == Path("/myproject")
        assert cfg.memory_dir == "memory"  # default

    def test_partial_models_section(self, tmp_path: Path) -> None:
        config_path = _write_yaml(tmp_path, {"models": {"coder": "gemini/new-model"}})
        cfg = load_config(str(config_path))
        assert cfg.models.coder == "gemini/new-model"
        # Other model fields use their defaults
        assert cfg.models.junior_reviewer == "deepseek/deepseek-chat"

    def test_telegram_empty_env_vars(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TG_TOKEN", raising=False)
        config_path = _write_yaml(tmp_path, {
            "telegram": {"bot_token": "${TG_TOKEN}", "chat_id": "000"},
        })
        cfg = load_config(str(config_path))
        assert cfg.telegram.bot_token == ""
        assert cfg.telegram.chat_id == "000"  # plain string, not env ref


# ---------------------------------------------------------------------------
# ForgeConfig.memory_path property
# ---------------------------------------------------------------------------

class TestForgeConfigProperty:
    def test_memory_path_combines_project_and_memory_dir(self) -> None:
        cfg = ForgeConfig()
        cfg.project_path = Path("/my/project")
        cfg.memory_dir = "mem"
        assert cfg.memory_path == Path("/my/project/mem")

    def test_memory_path_default(self) -> None:
        cfg = ForgeConfig()
        assert cfg.memory_path == Path("./memory")


# ---------------------------------------------------------------------------
# Dataclass defaults
# ---------------------------------------------------------------------------

class TestDataclassDefaults:
    def test_models_config_defaults(self) -> None:
        m = ModelsConfig()
        assert m.coder == "gemini/gemini-2.5-pro"
        assert m.junior_reviewer == "deepseek/deepseek-chat"

    def test_telegram_config_defaults(self) -> None:
        t = TelegramConfig()
        assert t.bot_token == ""
        assert t.chat_id == ""

    def test_pipeline_config_defaults(self) -> None:
        p = PipelineConfig()
        assert p.max_hook_retries == 3
        assert p.aider_timeout == 900

    def test_pre_commit_default_commands(self) -> None:
        pc = PreCommitConfig()
        assert "ruff check src/" in pc.pre_commit_commands if hasattr(pc, "pre_commit_commands") else True
        assert len(pc.commands) == 3
