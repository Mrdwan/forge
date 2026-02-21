"""Memory bank management for Forge pipeline.

Manages the project memory files that give the coder context:
- ARCHITECTURE.md — current system design
- ROADMAP.md — step list with checkboxes
- DECISIONS.md — past design decisions
- PROGRESS.md — running log of completed work
- CHANGELOG.md — human-readable summary (output only)
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import litellm

logger = logging.getLogger(__name__)


@dataclass
class Step:
    step_id: str  # e.g., "2.3"
    description: str  # e.g., "Build momentum composite scoring module"
    raw_line: str  # Original markdown line


def ensure_memory_bank(memory_path: Path) -> None:
    """Create memory bank directory and template files if they don't exist."""
    memory_path.mkdir(parents=True, exist_ok=True)

    templates = {
        "ARCHITECTURE.md": "# Architecture\n\nDescribe your system components, data flows, and schemas here.\n",
        "ROADMAP.md": "# Roadmap\n\nAdd steps as checkboxes:\n\n- [ ] Step 1.1: Example step\n",
        "DECISIONS.md": "# Design Decisions\n\nRecord why things are the way they are.\n",
        "PROGRESS.md": "# Progress Log\n\nUpdated automatically after each completed step.\n",
        "CHANGELOG.md": "# Changelog\n\nAll notable changes to this project.\n",
    }

    for filename, content in templates.items():
        filepath = memory_path / filename
        if not filepath.exists():
            filepath.write_text(content)
            logger.info(f"Created template: {filepath}")


def find_next_step(memory_path: Path, pattern: str) -> Step | None:
    """Find the first unchecked step in ROADMAP.md."""
    roadmap = memory_path / "ROADMAP.md"
    if not roadmap.exists():
        logger.error("ROADMAP.md not found")
        return None

    content = roadmap.read_text()
    for line in content.split("\n"):
        match = re.match(pattern, line)
        if match:
            return Step(
                step_id=match.group(1),
                description=match.group(2).strip(),
                raw_line=line.strip(),
            )

    return None  # All steps completed


def mark_step_complete(memory_path: Path, step: Step) -> None:
    """Check off a step in ROADMAP.md."""
    roadmap = memory_path / "ROADMAP.md"
    content = roadmap.read_text()

    # Replace the unchecked line with a checked version
    old_line = step.raw_line
    new_line = old_line.replace("- [ ]", "- [x]", 1)
    content = content.replace(old_line, new_line, 1)

    roadmap.write_text(content)
    logger.info(f"Marked Step {step.step_id} complete in ROADMAP.md")


def get_coder_context(memory_path: Path, step: Step) -> str:
    """Build the full context prompt for the coder.

    Reads ARCHITECTURE, DECISIONS, and PROGRESS to give the coder
    everything it needs to understand the project and implement the step.
    """
    parts = []

    # Architecture context
    arch = memory_path / "ARCHITECTURE.md"
    if arch.exists():
        parts.append(f"## Current Architecture\n\n{arch.read_text()}")

    # Design decisions
    decisions = memory_path / "DECISIONS.md"
    if decisions.exists():
        parts.append(f"## Design Decisions\n\n{decisions.read_text()}")

    # Progress log
    progress = memory_path / "PROGRESS.md"
    if progress.exists():
        parts.append(f"## What's Been Built So Far\n\n{progress.read_text()}")

    # Check for a detailed plan file
    plan_dir = memory_path.parent / "docs" / "plans"
    if plan_dir.exists():
        for plan_file in plan_dir.glob(f"*{step.step_id}*"):
            parts.append(f"## Detailed Plan\n\n{plan_file.read_text()}")
            break

    context = "\n\n---\n\n".join(parts)

    # The actual task prompt
    task = f"""## Your Task

Implement Step {step.step_id}: {step.description}

Read the architecture and progress above to understand the current state of the project.
Figure out what files need to be created or modified. Write clean, well-tested code.

Requirements:
- Write pytest tests for your implementation (in tests/ directory)
- Use type hints on all function signatures
- Use Google-style docstrings on public methods
- Catch specific exceptions, never bare except
- If this step involves rolling calculations, guard every .where() and division against NaN
- Run your new tests to verify they pass before finishing

After implementing, briefly summarize what you built and which files you created/modified."""

    return f"{context}\n\n{task}"


def get_memory_file_paths(memory_path: Path) -> list[str]:
    """Return relative paths to memory bank files for Aider --read."""
    memory_dir = memory_path.name
    files = ["ARCHITECTURE.md", "DECISIONS.md", "PROGRESS.md"]
    return [f"{memory_dir}/{f}" for f in files if (memory_path / f).exists()]


async def update_memory(
    memory_path: Path,
    step: Step,
    diff_summary: str,
    senior_review: str,
    model: str,
) -> None:
    """Update memory bank files after a successful step.

    Uses a cheap model to read current memory state + what was done,
    then produces updated versions of files that need changing.
    """
    progress = memory_path / "PROGRESS.md"
    arch = memory_path / "ARCHITECTURE.md"
    decisions = memory_path / "DECISIONS.md"
    changelog = memory_path / "CHANGELOG.md"

    # Always append to PROGRESS.md
    current_progress = progress.read_text() if progress.exists() else ""
    current_arch = arch.read_text() if arch.exists() else ""
    current_decisions = decisions.read_text() if decisions.exists() else ""

    prompt = f"""You are updating a project's memory bank after completing a development step.

## Completed Step
Step {step.step_id}: {step.description}

## Changes Made
{diff_summary}

## Senior Review Summary
{senior_review}

## Current Memory Files

### PROGRESS.md (current)
{current_progress}

### ARCHITECTURE.md (current)
{current_arch}

### DECISIONS.md (current)
{current_decisions}

## Instructions

Output exactly three sections, separated by "===SECTION===" markers:

1. PROGRESS.md — Append a new entry for this step. Include: what was built, key files, test count if mentioned in the review. Keep existing entries unchanged.

2. ARCHITECTURE.md — Update ONLY if the system structure changed (new components, new data flows, schema changes). If no structural changes, output the existing content unchanged. Do NOT add information about implementation details that don't affect architecture.

3. DECISIONS.md — Add an entry ONLY if a significant design decision was made during this step (e.g., chose a specific pattern, rejected an approach). If no new decisions, output existing content unchanged.

Keep all files concise. Under 50 lines each. Remove outdated information.

Format:
===PROGRESS===
[updated progress content]
===ARCHITECTURE===
[updated architecture content]
===DECISIONS===
[updated decisions content]"""

    try:
        response = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
        )

        result = response.choices[0].message.content

        # Parse sections
        sections = {}
        for section_name in ["PROGRESS", "ARCHITECTURE", "DECISIONS"]:
            marker = f"==={section_name}==="
            if marker in result:
                start = result.index(marker) + len(marker)
                # Find next marker or end
                next_markers = [f"==={s}===" for s in ["PROGRESS", "ARCHITECTURE", "DECISIONS"] if s != section_name]
                end = len(result)
                for nm in next_markers:
                    if nm in result[start:]:
                        candidate = result.index(nm, start)
                        if candidate < end:
                            end = candidate
                sections[section_name] = result[start:end].strip()

        if "PROGRESS" in sections:
            progress.write_text(sections["PROGRESS"] + "\n")
        if "ARCHITECTURE" in sections:
            arch.write_text(sections["ARCHITECTURE"] + "\n")
        if "DECISIONS" in sections:
            decisions.write_text(sections["DECISIONS"] + "\n")

        # Append to CHANGELOG (simple, no model needed)
        changelog_entry = f"\n## Step {step.step_id}: {step.description}\n\n{diff_summary[:500]}\n"
        with open(changelog, "a") as f:
            f.write(changelog_entry)

        logger.info("Memory bank updated successfully")

    except Exception as e:
        logger.error(f"Failed to update memory bank: {e}")
        # Fallback: just append to progress
        with open(progress, "a") as f:
            f.write(f"\n### Step {step.step_id}: {step.description}\n\n{diff_summary[:300]}\n")
