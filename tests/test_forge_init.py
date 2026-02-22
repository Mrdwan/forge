"""Unit tests for forge_init.py."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from forge_init import create_project, main


# ---------------------------------------------------------------------------
# create_project
# ---------------------------------------------------------------------------


class TestCreateProject:
    def test_creates_expected_directory_structure(self, tmp_path: Path) -> None:
        with patch("forge_init.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            root = create_project("my-app", tmp_path)

        assert root == tmp_path / "my-app"
        assert (root / "src" / "my_app").is_dir()
        assert (root / "tests").is_dir()
        assert (root / "memory").is_dir()
        assert (root / "docs" / "plans").is_dir()

    def test_creates_all_memory_files(self, tmp_path: Path) -> None:
        with patch("forge_init.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            root = create_project("test-proj", tmp_path)

        for fname in [
            "ARCHITECTURE.md",
            "ROADMAP.md",
            "DECISIONS.md",
            "PROGRESS.md",
            "CHANGELOG.md",
        ]:
            assert (root / "memory" / fname).exists(), f"{fname} missing"

    def test_roadmap_contains_placeholder_steps(self, tmp_path: Path) -> None:
        with patch("forge_init.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            root = create_project("test-proj", tmp_path)

        roadmap = (root / "memory" / "ROADMAP.md").read_text()
        assert "Step 1.1" in roadmap
        assert "[ ]" in roadmap

    def test_creates_python_project_files(self, tmp_path: Path) -> None:
        with patch("forge_init.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            root = create_project("my-app", tmp_path)

        assert (root / "pyproject.toml").exists()
        assert (root / "mypy.ini").exists()
        assert (root / ".gitignore").exists()

    def test_creates_source_package_init(self, tmp_path: Path) -> None:
        with patch("forge_init.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            root = create_project("my-app", tmp_path)

        assert (root / "src" / "my_app" / "__init__.py").exists()

    def test_creates_test_files(self, tmp_path: Path) -> None:
        with patch("forge_init.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            root = create_project("my-app", tmp_path)

        assert (root / "tests" / "__init__.py").exists()
        assert (root / "tests" / "test_placeholder.py").exists()

    def test_runs_git_init_and_commit(self, tmp_path: Path) -> None:
        with patch("forge_init.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            create_project("my-app", tmp_path)

        commands = [c[0][0] for c in mock_run.call_args_list]
        assert ["git", "init", "-q"] in commands
        assert any("commit" in cmd for cmd in commands)

    def test_hyphenated_name_converts_to_underscore_pkg(self, tmp_path: Path) -> None:
        with patch("forge_init.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            root = create_project("my-cool-app", tmp_path)

        assert (root / "src" / "my_cool_app").is_dir()
        init_content = (root / "src" / "my_cool_app" / "__init__.py").read_text()
        assert "my-cool-app" in init_content or "my_cool_app" in init_content

    def test_creates_docs_plans_gitkeep(self, tmp_path: Path) -> None:
        with patch("forge_init.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            root = create_project("my-app", tmp_path)

        assert (root / "docs" / "plans" / ".gitkeep").exists()

    def test_pyproject_toml_contains_project_name(self, tmp_path: Path) -> None:
        with patch("forge_init.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            root = create_project("wealth-ops", tmp_path)

        content = (root / "pyproject.toml").read_text()
        assert "wealth-ops" in content

    def test_architecture_md_contains_project_name(self, tmp_path: Path) -> None:
        with patch("forge_init.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            root = create_project("my-service", tmp_path)

        arch = (root / "memory" / "ARCHITECTURE.md").read_text()
        assert "my-service" in arch


# ---------------------------------------------------------------------------
# main() — CLI entry point
# ---------------------------------------------------------------------------


class TestMain:
    def test_default_path_is_current_dir(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        with (
            patch(
                "forge_init.create_project", return_value=tmp_path / "my-app"
            ) as mock_create,
            patch("sys.argv", ["forge_init.py", "my-app"]),
        ):
            main()

        mock_create.assert_called_once_with("my-app", Path("."))
        captured = capsys.readouterr()
        assert "my-app" in captured.out

    def test_custom_path_passed_to_create_project(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        with (
            patch(
                "forge_init.create_project", return_value=tmp_path / "proj"
            ) as mock_create,
            patch("sys.argv", ["forge_init.py", "proj", "--path", str(tmp_path)]),
        ):
            main()

        mock_create.assert_called_once_with("proj", tmp_path)

    def test_prints_next_steps(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        with (
            patch("forge_init.create_project", return_value=tmp_path / "proj"),
            patch("sys.argv", ["forge_init.py", "proj"]),
        ):
            main()

        captured = capsys.readouterr()
        assert "ROADMAP" in captured.out or "next" in captured.out.lower()
