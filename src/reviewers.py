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

logger = logging.getLogger(__name__)


JUNIOR_REVIEW_PROMPT = """You are a code reviewer doing a quick quality check on recent changes.

## Step Being Implemented
Step {step_id}: {description}

## Changed Files
{changed_files}

## Diff Summary
{diff}

## Your Job

Check these things and be specific:

1. **Tests exist?** Are there actual pytest tests for the new code? Not just the code itself.
2. **Obvious bugs?** Off-by-one errors, unhandled None/empty cases, wrong variable names.
3. **Error handling?** Are exceptions caught specifically (not bare except)? Are API/IO failures handled?
4. **NaN safety?** If there are rolling calculations, is every .where() and division guarded against NaN?
5. **Does it match the step description?** Did the coder actually build what was asked for?

You have access to read project files. If you need to check how something integrates with existing code, use /read to examine relevant files.

Respond in this exact format:

VERDICT: PASS or FAIL

ISSUES (if FAIL):
- [specific issue 1]
- [specific issue 2]

SUMMARY: [2-3 sentences max]"""


SENIOR_REVIEW_PROMPT = """You are a senior engineer doing a thorough review of a completed development step.

## Step Being Implemented
Step {step_id}: {description}

## Changed Files
{changed_files}

## Diff Summary
{diff}

## Your Job

This is the deep review. You have access to read any file in the project. Use it.

Check each of the following. Be specific and cite file names and line numbers:

1. **Acceptance criteria:** Does the implementation actually satisfy what Step {step_id} asked for? Not "mostly" — fully.
2. **Security concerns:** SQL injection, path traversal, hardcoded secrets, unsafe deserialization, missing input validation.
3. **Technical debt:** Copy-pasted code, magic numbers, missing abstractions, things that will hurt in 3 months.
4. **Code design:** Single responsibility? Dependency inversion for external IO? Clean interfaces?
5. **Integration:** Does the new code fit with the existing architecture? Check imports, check how it connects to existing modules.
6. **Test quality:** Are the tests testing behavior or just testing that code runs? Are edge cases covered?

Respond in this exact format:

VERDICT: PASS or FAIL

ISSUES (if FAIL):
- [SEVERITY: HIGH/MEDIUM/LOW] [specific issue with file reference]

SUGGESTIONS (optional, for PASS with notes):
- [suggestion]

SUMMARY: [3-5 sentences covering what was built, quality assessment, and any concerns]"""


SENIOR_GUIDANCE_PROMPT = """You are a senior engineer. The coding agent has been stuck on this step and needs your guidance.

## Step Being Implemented
Step {step_id}: {description}

## What the Coder Tried
{coder_output}

## Error / Failure
{error}

## Junior Reviewer Feedback
{junior_feedback}

You have access to read any file in the project. Investigate the root cause.

Provide specific, actionable guidance for the coder:
1. What is the actual root cause of the failure?
2. What specific changes need to be made (file names, function names, what to change)?
3. Is the coder's approach fundamentally wrong, or is it a small fix?

Be concrete. "Fix the error handling" is useless. "In src/modules/ingest.py, the fetch_data() function catches Exception but should catch requests.HTTPError and handle 429 rate limits with exponential backoff" is useful."""


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

    prompt = JUNIOR_REVIEW_PROMPT.format(
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

    prompt = SENIOR_REVIEW_PROMPT.format(
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
    prompt = SENIOR_GUIDANCE_PROMPT.format(
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
