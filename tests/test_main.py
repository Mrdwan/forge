"""Unit tests for src/__main__.py."""

import sys
import logging
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest


class TestMain:
    """Tests for main() entry point.

    Strategy: We cannot easily reload __main__ (module-level FileHandler).
    Instead we directly call the `main` function with all side-effectful
    calls mocked at the source level.
    """

    def _run_main(self, argv: list[str], mock_cfg: MagicMock | None = None) -> MagicMock:
        """Helper: run main() with mocked load_config, run_bot, and FileHandler."""
        if mock_cfg is None:
            mock_cfg = MagicMock()
            mock_cfg.project_path = "/fake/project"
            mock_cfg.models.coder = "test/coder"
            mock_cfg.models.junior_reviewer = "test/junior"
            mock_cfg.models.senior_reviewer = "test/senior"

        with (
            patch("logging.FileHandler", return_value=MagicMock()),
            patch("src.__main__.load_config", return_value=mock_cfg) as mock_load,
            patch("src.__main__.run_bot") as mock_run_bot,
            patch.object(sys, "argv", argv),
        ):
            from src.__main__ import main
            main()
            return mock_load, mock_run_bot, mock_cfg

    def test_default_config_path(self) -> None:
        with (
            patch("logging.FileHandler", return_value=MagicMock()),
            patch("src.__main__.load_config", return_value=MagicMock()) as mock_load,
            patch("src.__main__.run_bot"),
            patch.object(sys, "argv", ["forge"]),
        ):
            from src.__main__ import main
            main()
        mock_load.assert_called_once_with("config.yaml")

    def test_custom_config_path_from_argv(self) -> None:
        with (
            patch("logging.FileHandler", return_value=MagicMock()),
            patch("src.__main__.load_config", return_value=MagicMock()) as mock_load,
            patch("src.__main__.run_bot"),
            patch.object(sys, "argv", ["forge", "/custom/path/config.yaml"]),
        ):
            from src.__main__ import main
            main()
        mock_load.assert_called_once_with("/custom/path/config.yaml")

    def test_run_bot_called_with_config(self) -> None:
        mock_cfg = MagicMock()
        with (
            patch("logging.FileHandler", return_value=MagicMock()),
            patch("src.__main__.load_config", return_value=mock_cfg),
            patch("src.__main__.run_bot") as mock_run_bot,
            patch.object(sys, "argv", ["forge"]),
        ):
            from src.__main__ import main
            main()
        mock_run_bot.assert_called_once_with(mock_cfg)

    def test_prints_startup_info(self, capsys: pytest.CaptureFixture) -> None:
        mock_cfg = MagicMock()
        mock_cfg.project_path = "/my/project"
        mock_cfg.models.coder = "gemini/test"
        mock_cfg.models.junior_reviewer = "deepseek/test"
        mock_cfg.models.senior_reviewer = "anthropic/test"

        with (
            patch("logging.FileHandler", return_value=MagicMock()),
            patch("src.__main__.load_config", return_value=mock_cfg),
            patch("src.__main__.run_bot"),
            patch.object(sys, "argv", ["forge"]),
        ):
            from src.__main__ import main
            main()

        captured = capsys.readouterr()
        assert "Forge" in captured.out
        assert "/my/project" in captured.out
        assert "gemini/test" in captured.out
