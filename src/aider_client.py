"""Aider subprocess wrapper for Forge pipeline.

Handles running Aider in both code mode (editing) and ask mode (reviewing).
Each invocation is a separate process. Context is preserved through:
- The files themselves (Aider reads the current state)
- The memory bank files (read-only context)
- The prompt message (includes feedback from previous attempts)
"""

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class AiderResult:
    success: bool
    output: str
    error: str
    changed_files: list[str]


def run_coder(
    model: str,
    message: str,
    project_path: Path,
    read_only_files: list[str] | None = None,
    timeout: int = 900,
) -> AiderResult:
    """Run Aider in code mode to implement changes.

    Args:
        model: Model identifier (e.g., 'gemini/gemini-2.5-pro')
        message: The implementation prompt
        project_path: Path to the project root
        read_only_files: Files to include as read-only context (memory bank)
        timeout: Max seconds before killing the process
    """
    cmd = [
        "aider",
        "--model", model,
        "--message", message,
        "--yes-always",
        "--no-auto-commits",
        "--no-stream",
        "--no-suggest-shell-commands",
    ]

    if read_only_files:
        for f in read_only_files:
            filepath = project_path / f
            if filepath.exists():
                cmd.extend(["--read", f])

    return _run_aider(cmd, project_path, timeout)


def run_reviewer(
    model: str,
    message: str,
    project_path: Path,
    review_files: list[str] | None = None,
    timeout: int = 300,
) -> AiderResult:
    """Run Aider in ask mode for code review.

    The reviewer can read the entire codebase but cannot edit files.

    Args:
        model: Model identifier (e.g., 'deepseek/deepseek-chat')
        message: The review prompt
        project_path: Path to the project root
        review_files: Specific files to focus the review on (read-only)
        timeout: Max seconds before killing the process
    """
    cmd = [
        "aider",
        "--model", model,
        "--chat-mode", "ask",
        "--message", message,
        "--no-stream",
        "--no-suggest-shell-commands",
    ]

    if review_files:
        for f in review_files:
            filepath = project_path / f
            if filepath.exists():
                cmd.extend(["--read", f])

    return _run_aider(cmd, project_path, timeout)


def get_changed_files(project_path: Path) -> list[str]:
    """Get list of files changed since last commit (unstaged + staged)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Also get untracked files
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        files = result.stdout.strip().split("\n") + untracked.stdout.strip().split("\n")
        return [f for f in files if f.strip()]
    except (subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
        logger.warning(f"Failed to get changed files: {e}")
        return []


def get_diff(project_path: Path) -> str:
    """Get the full diff of uncommitted changes."""
    try:
        # Staged + unstaged vs HEAD
        result = subprocess.run(
            ["git", "diff", "HEAD", "--stat"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        stat = result.stdout.strip()

        # Also get short diff for review context (limited to avoid token explosion)
        diff_result = subprocess.run(
            ["git", "diff", "HEAD", "--no-color"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        diff = diff_result.stdout.strip()

        # Truncate if too long (keep first 3000 chars)
        if len(diff) > 3000:
            diff = diff[:3000] + "\n\n... [diff truncated, use Aider /read to see full files]"

        return f"Diff stats:\n{stat}\n\nDiff:\n{diff}"
    except (subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
        logger.warning(f"Failed to get diff: {e}")
        return "[Could not generate diff]"


def commit_changes(project_path: Path, message: str) -> bool:
    """Stage all changes and commit."""
    try:
        subprocess.run(
            ["git", "add", "-A"],
            cwd=project_path,
            capture_output=True,
            timeout=30,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=project_path,
            capture_output=True,
            timeout=30,
            check=True,
        )
        return True
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
        logger.error(f"Commit failed: {e}")
        return False


def reset_changes(project_path: Path) -> bool:
    """Reset all uncommitted changes (used when step fails completely)."""
    try:
        subprocess.run(
            ["git", "checkout", "--", "."],
            cwd=project_path,
            capture_output=True,
            timeout=30,
            check=True,
        )
        subprocess.run(
            ["git", "clean", "-fd"],
            cwd=project_path,
            capture_output=True,
            timeout=30,
            check=True,
        )
        return True
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
        logger.error(f"Reset failed: {e}")
        return False


def _run_aider(cmd: list[str], cwd: Path, timeout: int) -> AiderResult:
    """Execute an Aider command and capture results."""
    logger.info(f"Running aider with model: {cmd[2]}")

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        output = result.stdout.strip()
        error = result.stderr.strip()
        changed = get_changed_files(cwd)

        if result.returncode != 0:
            logger.warning(f"Aider exited with code {result.returncode}")
            return AiderResult(
                success=False,
                output=output,
                error=error or f"Aider exited with code {result.returncode}",
                changed_files=changed,
            )

        return AiderResult(
            success=True,
            output=output,
            error=error,
            changed_files=changed,
        )

    except subprocess.TimeoutExpired:
        logger.error(f"Aider timed out after {timeout}s")
        return AiderResult(
            success=False,
            output="",
            error=f"Aider timed out after {timeout} seconds",
            changed_files=[],
        )
    except FileNotFoundError:
        return AiderResult(
            success=False,
            output="",
            error="Aider not found. Install with: pip install aider-chat",
            changed_files=[],
        )
