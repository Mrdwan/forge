"""Two-tier review system for Forge pipeline.

Junior Reviewer: Fast, cheap (DeepSeek). Runs in a tight loop with the coder.
  Has Aider read access to dig into files when needed.
  Checks: tests pass, obvious bugs, missing error handling, basic correctness.

Senior Reviewer: Thorough (Sonnet). Runs once or twice per step.
  Has Aider read access for deep codebase exploration.
  Checks: acceptance criteria, security, technical debt, design quality,
  architecture compliance.
"""

import logging
from pathlib import Path

from src.aider_client import AiderResult, get_changed_files, get_diff, run_reviewer
from src.prompts import load_prompt

logger = logging.getLogger(__name__)


def run_junior_review(
    model: str,
    step_id: str,
    description: str,
    project_path: Path,
    timeout: int = 300,
) -> AiderResult:
    """Run junior review with Aider read access."""
    changed = get_changed_files(project_path)
    diff = get_diff(project_path)

    prompt_template = load_prompt("junior_reviewer")
    prompt = prompt_template.format(
        step_id=step_id,
        description=description,
        changed_files="\n".join(f"- {f}" for f in changed)
        if changed
        else "No files detected",
        diff=diff,
    )

    # Give reviewer read access to changed files + memory
    review_files = changed.copy()

    return run_reviewer(
        model=model,
        message=prompt,
        project_path=project_path,
        review_files=review_files,
        timeout=timeout,
    )


def run_senior_review(
    model: str,
    step_id: str,
    description: str,
    project_path: Path,
    timeout: int = 600,
) -> AiderResult:
    """Run senior review with Aider read access."""
    changed = get_changed_files(project_path)
    diff = get_diff(project_path)

    prompt_template = load_prompt("senior_reviewer")
    prompt = prompt_template.format(
        step_id=step_id,
        description=description,
        changed_files="\n".join(f"- {f}" for f in changed)
        if changed
        else "No files detected",
        diff=diff,
    )

    review_files = changed.copy()

    return run_reviewer(
        model=model,
        message=prompt,
        project_path=project_path,
        review_files=review_files,
        timeout=timeout,
    )


def get_senior_guidance(
    model: str,
    step_id: str,
    description: str,
    coder_output: str,
    error: str,
    junior_feedback: str,
    project_path: Path,
    timeout: int = 600,
) -> AiderResult:
    """Ask senior reviewer for guidance when the coder is stuck."""
    prompt_template = load_prompt("senior_guidance")
    prompt = prompt_template.format(
        step_id=step_id,
        description=description,
        coder_output=coder_output[:1500],  # Truncate to manage tokens
        error=error[:1000],
        junior_feedback=junior_feedback[:1000],
    )

    changed = get_changed_files(project_path)

    return run_reviewer(
        model=model,
        message=prompt,
        project_path=project_path,
        review_files=changed,
        timeout=timeout,
    )


def parse_verdict(review_output: str) -> bool:
    """Extract PASS/FAIL verdict from reviewer output."""
    output_upper = review_output.upper()
    # Look for explicit VERDICT line
    for line in output_upper.split("\n"):
        if "VERDICT:" in line:
            return "PASS" in line
    # Fallback: look for PASS/FAIL anywhere (dead code in practice — the for loop
    # always finds any line containing "VERDICT:", but kept as a safety net)
    if "VERDICT: PASS" in output_upper:  # pragma: no cover
        return True  # pragma: no cover
    if "VERDICT: FAIL" in output_upper:  # pragma: no cover
        return False  # pragma: no cover
    # If no clear verdict, assume fail (safer)
    logger.warning("Could not parse verdict from review, defaulting to FAIL")
    return False


def extract_issues(review_output: str) -> str:
    """Extract the issues section from a review for feeding back to the coder."""
    lines = review_output.split("\n")
    issues = []
    capturing = False

    for line in lines:
        if "ISSUES" in line.upper():
            capturing = True
            continue
        if capturing:
            if line.strip().startswith("-"):
                issues.append(line.strip())
            elif line.strip() == "" and issues:
                continue
            elif any(
                keyword in line.upper()
                for keyword in ["SUMMARY", "SUGGESTIONS", "VERDICT"]
            ):
                break

    return "\n".join(issues) if issues else review_output[:500]
