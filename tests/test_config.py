"""Unit tests for src/config.py."""

from pathlib import Path

import pytest
import yaml

from src.config import (
    ForgeConfig,
    ModelsConfig,
    PipelineConfig,
    PreCommitConfig,
    TelegramConfig,
    _env_int,
    _env_list,
    _env_str,
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

    def test_env_var_missing_returns_empty_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
        assert _resolve_env("${NONEXISTENT_VAR}") == ""

    def test_partial_env_syntax_not_resolved(self) -> None:
        assert _resolve_env("${PARTIAL") == "${PARTIAL"
        assert _resolve_env("NO_BRACES") == "NO_BRACES"


# ---------------------------------------------------------------------------
# _env_str
# ---------------------------------------------------------------------------


class TestEnvStr:
    def test_env_set_returns_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FORGE_X", "from-env")
        assert _env_str("FORGE_X", "fallback") == "from-env"

    def test_env_empty_returns_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FORGE_X", "")
        assert _env_str("FORGE_X", "fallback") == "fallback"

    def test_env_missing_returns_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FORGE_X", raising=False)
        assert _env_str("FORGE_X", "fallback") == "fallback"


# ---------------------------------------------------------------------------
# _env_int
# ---------------------------------------------------------------------------


class TestEnvInt:
    def test_env_set_returns_int(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FORGE_N", "42")
        assert _env_int("FORGE_N", 10) == 42

    def test_env_empty_returns_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FORGE_N", "")
        assert _env_int("FORGE_N", 10) == 10

    def test_env_invalid_returns_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FORGE_N", "not-a-number")
        assert _env_int("FORGE_N", 10) == 10

    def test_env_missing_returns_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FORGE_N", raising=False)
        assert _env_int("FORGE_N", 7) == 7


# ---------------------------------------------------------------------------
# _env_list
# ---------------------------------------------------------------------------


class TestEnvList:
    def test_env_set_parses_csv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FORGE_CMDS", "ruff check src/,pytest tests/")
        assert _env_list("FORGE_CMDS", []) == ["ruff check src/", "pytest tests/"]

    def test_env_strips_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FORGE_CMDS", " cmd1 , cmd2 ")
        assert _env_list("FORGE_CMDS", []) == ["cmd1", "cmd2"]

    def test_env_empty_returns_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FORGE_CMDS", "")
        assert _env_list("FORGE_CMDS", ["default"]) == ["default"]

    def test_env_missing_returns_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FORGE_CMDS", raising=False)
        assert _env_list("FORGE_CMDS", ["default"]) == ["default"]


# ---------------------------------------------------------------------------
# load_config — helper
# ---------------------------------------------------------------------------


def _write_yaml(tmp_path: Path, content: dict) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(content))
    return p


class TestLoadConfig:
    def test_full_config_from_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BOT_TOKEN", "test-bot-token")
        monkeypatch.setenv("CHAT_ID", "99999")
        # Make sure no FORGE_ overrides interfere
        for var in [
            "FORGE_MODEL_CODER",
            "FORGE_PROJECT_PATH",
            "FORGE_MAX_HOOK_RETRIES",
        ]:
            monkeypatch.delenv(var, raising=False)

        config_path = _write_yaml(
            tmp_path,
            {
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
            },
        )

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

    def test_empty_yaml_uses_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text("{}\n")
        # Ensure no FORGE_ vars override anything
        for var in [
            "FORGE_PROJECT_PATH",
            "FORGE_MEMORY_DIR",
            "FORGE_MODEL_CODER",
            "FORGE_MAX_HOOK_RETRIES",
            "FORGE_PRECOMMIT_COMMANDS",
        ]:
            monkeypatch.delenv(var, raising=False)

        cfg = load_config(str(config_path))

        assert cfg.project_path == Path(".")
        assert cfg.memory_dir == "memory"
        # Models are empty by default — no hardcoded names
        assert cfg.models.coder == ""
        assert cfg.models.coder_fallback == ""
        assert cfg.models.junior_reviewer == ""
        assert cfg.models.senior_reviewer == ""
        assert cfg.models.context_updater == ""
        assert cfg.pipeline.max_hook_retries == 3
        assert len(cfg.pre_commit.commands) == 3

    def test_partial_project_section(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FORGE_PROJECT_PATH", raising=False)
        monkeypatch.delenv("FORGE_MEMORY_DIR", raising=False)
        config_path = _write_yaml(tmp_path, {"project": {"path": "/myproject"}})
        cfg = load_config(str(config_path))
        assert cfg.project_path == Path("/myproject")
        assert cfg.memory_dir == "memory"

    def test_partial_models_section(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for var in ["FORGE_MODEL_CODER", "FORGE_MODEL_JUNIOR_REVIEWER"]:
            monkeypatch.delenv(var, raising=False)
        config_path = _write_yaml(tmp_path, {"models": {"coder": "gemini/new-model"}})
        cfg = load_config(str(config_path))
        assert cfg.models.coder == "gemini/new-model"
        # Other model fields are empty (no hardcoded defaults)
        assert cfg.models.junior_reviewer == ""

    def test_telegram_empty_env_vars(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TG_TOKEN", raising=False)
        config_path = _write_yaml(
            tmp_path,
            {
                "telegram": {"bot_token": "${TG_TOKEN}", "chat_id": "000"},
            },
        )
        cfg = load_config(str(config_path))
        assert cfg.telegram.bot_token == ""
        assert cfg.telegram.chat_id == "000"

    # ── FORGE_* env var override tests ──────────────────────────────────────

    def test_env_overrides_project_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FORGE_PROJECT_PATH", "/override/path")
        config_path = _write_yaml(tmp_path, {"project": {"path": "/yaml/path"}})
        cfg = load_config(str(config_path))
        assert cfg.project_path == Path("/override/path")

    def test_env_overrides_memory_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FORGE_MEMORY_DIR", "bank")
        config_path = _write_yaml(tmp_path, {"project": {"memory_dir": "memory"}})
        cfg = load_config(str(config_path))
        assert cfg.memory_dir == "bank"

    def test_env_overrides_all_models(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FORGE_MODEL_CODER", "openai/gpt-4o")
        monkeypatch.setenv("FORGE_MODEL_CODER_FALLBACK", "gemini/gemini-2.5-pro")
        monkeypatch.setenv("FORGE_MODEL_JUNIOR_REVIEWER", "openai/gpt-4o-mini")
        monkeypatch.setenv("FORGE_MODEL_SENIOR_REVIEWER", "anthropic/claude-opus-4")
        monkeypatch.setenv("FORGE_MODEL_CONTEXT_UPDATER", "deepseek/deepseek-chat")
        config_path = _write_yaml(tmp_path, {"models": {"coder": "yaml/model"}})
        cfg = load_config(str(config_path))
        assert cfg.models.coder == "openai/gpt-4o"
        assert cfg.models.coder_fallback == "gemini/gemini-2.5-pro"
        assert cfg.models.junior_reviewer == "openai/gpt-4o-mini"
        assert cfg.models.senior_reviewer == "anthropic/claude-opus-4"
        assert cfg.models.context_updater == "deepseek/deepseek-chat"

    def test_env_overrides_pipeline_settings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FORGE_MAX_HOOK_RETRIES", "7")
        monkeypatch.setenv("FORGE_MAX_JUNIOR_RETRIES", "5")
        monkeypatch.setenv("FORGE_MAX_SENIOR_ROUNDS", "4")
        monkeypatch.setenv("FORGE_AIDER_TIMEOUT", "1200")
        config_path = _write_yaml(tmp_path, {})
        cfg = load_config(str(config_path))
        assert cfg.pipeline.max_hook_retries == 7
        assert cfg.pipeline.max_junior_retries == 5
        assert cfg.pipeline.max_senior_rounds == 4
        assert cfg.pipeline.aider_timeout == 1200

    def test_env_overrides_precommit_commands(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "FORGE_PRECOMMIT_COMMANDS", "ruff check src/,pytest tests/ -x"
        )
        config_path = _write_yaml(tmp_path, {})
        cfg = load_config(str(config_path))
        assert cfg.pre_commit.commands == ["ruff check src/", "pytest tests/ -x"]

    def test_env_overrides_roadmap_patterns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FORGE_UNCHECKED_PATTERN", r"^\s*-\s*\[ \]\s*(.+)")
        monkeypatch.setenv("FORGE_CHECKED_PATTERN", r"^\s*-\s*\[x\]\s*(.+)")
        config_path = _write_yaml(tmp_path, {})
        cfg = load_config(str(config_path))
        assert cfg.unchecked_pattern == r"^\s*-\s*\[ \]\s*(.+)"
        assert cfg.checked_pattern == r"^\s*-\s*\[x\]\s*(.+)"

    def test_env_takes_precedence_over_yaml_for_models(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FORGE_MODEL_CODER", "env/model")
        config_path = _write_yaml(tmp_path, {"models": {"coder": "yaml/model"}})
        cfg = load_config(str(config_path))
        # Env var wins
        assert cfg.models.coder == "env/model"

    def test_yaml_used_when_env_not_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FORGE_MODEL_CODER", raising=False)
        config_path = _write_yaml(tmp_path, {"models": {"coder": "yaml/model"}})
        cfg = load_config(str(config_path))
        # YAML value is used when env not set
        assert cfg.models.coder == "yaml/model"


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
    def test_models_config_defaults_are_empty(self) -> None:
        """Models have no hardcoded defaults — must be set via config or env."""
        m = ModelsConfig()
        assert m.coder == ""
        assert m.coder_fallback == ""
        assert m.junior_reviewer == ""
        assert m.senior_reviewer == ""
        assert m.context_updater == ""

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
        assert len(pc.commands) == 3
        assert "ruff check src/" in pc.commands
