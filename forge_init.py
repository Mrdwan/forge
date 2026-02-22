#!/usr/bin/env python3
"""Generate a skeleton project that Forge can work with.

Usage:
    python forge_init.py <project_name> [--path /where/to/create]

Creates the directory structure, memory bank templates, config files,
and a sample ROADMAP.md that Forge knows how to parse.
"""

import argparse
import subprocess
from pathlib import Path


def create_project(name: str, base_path: Path) -> Path:
    root = base_path / name
    root.mkdir(parents=True, exist_ok=True)

    # --- Source and test directories ---
    (root / "src" / name.replace("-", "_")).mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(exist_ok=True)

    # --- Git init ---
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)

    # --- Memory bank ---
    memory = root / "memory"
    memory.mkdir(exist_ok=True)

    (memory / "ARCHITECTURE.md").write_text(f"""# Architecture

## Overview

{name} is a [describe your system in one sentence].

## Components

Describe your major components here as you build them. Forge updates this
file automatically when a step changes the system structure.

## Data Flow

Describe how data moves through the system.

## Schemas

Document key data structures and database schemas here.
""")

    (memory / "ROADMAP.md").write_text("""# Roadmap

## Phase 1: Foundation
- [ ] Step 1.1: Set up project skeleton with package structure, pyproject.toml, and dev tooling
- [ ] Step 1.2: [Your second step here]
- [ ] Step 1.3: [Your third step here]

## Phase 2: Core Features
- [ ] Step 2.1: [Describe the feature, not the implementation]
- [ ] Step 2.2: [Another feature]

## Phase 3: Polish
- [ ] Step 3.1: [Integration, testing, hardening]
""")

    (memory / "DECISIONS.md").write_text("""# Design Decisions

Record significant choices here so the coder doesn't re-litigate them.

Format:
### [Date or Step] Decision Title
**Context:** Why this came up.
**Decision:** What we chose.
**Reason:** Why.
""")

    (memory / "PROGRESS.md").write_text("""# Progress Log

Updated automatically by Forge after each completed step.
""")

    (memory / "CHANGELOG.md").write_text(f"""# Changelog

All notable changes to {name}.
""")

    # --- Python project config ---
    pkg = name.replace("-", "_")

    (root / "pyproject.toml").write_text(f"""[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "ruff>=0.8.0",
    "mypy>=1.13",
]

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]

[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
check_untyped_defs = true

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q --tb=short"
""")

    # mypy.ini (Forge pre-commit hooks reference this)
    (root / "mypy.ini").write_text("""[mypy]
python_version = 3.11
warn_return_any = True
warn_unused_configs = True
disallow_untyped_defs = True
check_untyped_defs = True

[mypy-tests.*]
disallow_untyped_defs = False
""")

    # --- Source package init ---
    src_pkg = root / "src" / pkg
    (src_pkg / "__init__.py").write_text(f'"""Top-level package for {name}."""\n')

    # --- Test placeholder ---
    (root / "tests" / "__init__.py").write_text("")
    (
        root / "tests" / "test_placeholder.py"
    ).write_text(f"""\"\"\"Placeholder test to verify the test suite runs.\"\"\"


def test_import() -> None:
    import {pkg}
    assert {pkg} is not None
""")

    # --- Gitignore ---
    (root / ".gitignore").write_text("""__pycache__/
*.pyc
*.egg-info/
dist/
build/
.mypy_cache/
.pytest_cache/
.ruff_cache/
*.log
.env
.venv/
venv/
""")

    # --- Optional: docs/plans directory for detailed step plans ---
    (root / "docs" / "plans").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "plans" / ".gitkeep").write_text("")

    # --- Initial commit ---
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init: project skeleton"], cwd=root, check=True
    )

    return root


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a Forge-compatible project skeleton"
    )
    parser.add_argument("name", help="Project name (e.g., wealth-ops)")
    parser.add_argument(
        "--path", default=".", help="Where to create the project (default: current dir)"
    )
    args = parser.parse_args()

    project_path = create_project(args.name, Path(args.path))
    print(f"Created {project_path}")
    print()
    print("Next steps:")
    print("  1. Edit memory/ROADMAP.md with your actual steps")
    print("  2. Edit memory/ARCHITECTURE.md with your system description")
    print("  3. Add any known design decisions to memory/DECISIONS.md")
    print(f"  4. Point Forge's config.yaml at {project_path}")
    print("  5. Message /next on Telegram")


if __name__ == "__main__":  # pragma: no cover
    main()  # pragma: no cover
