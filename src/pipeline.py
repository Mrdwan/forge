"""Main pipeline orchestrator for Forge.

Manages the step execution flow:
1. Find next step from ROADMAP
2. Run coder (Aider + coding model)
3. Run pre-commit hooks
4. Junior review loop
5. Senior review
6. Update memory bank
7. Notify via Telegram
"""

import logging
import shlex
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from src.aider_client import (
    commit_changes,
    reset_changes,
    run_coder,
)
from src.config import ForgeConfig
from src.memory import (
    Step,
    find_next_step,
    get_coder_context,
    get_memory_file_paths,
    update_memory,
)
from src.reviewers import (
    extract_issues,
    get_senior_guidance,
    parse_verdict,
    run_junior_review,
    run_senior_review,
)

logger = logging.getLogger(__name__)


class StepStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    NO_STEPS = "no_steps"
    ERROR = "error"


@dataclass
class StepResult:
    status: StepStatus
    step: Step | None
    summary: str
    details: str = ""


def run_pre_commit(project_path: Path, commands: list[str]) -> tuple[bool, str]:
    """Run pre-commit hook commands. Returns (passed, error_output)."""
    errors = []
    for cmd in commands:
        try:
            result = subprocess.run(
                shlex.split(cmd),
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                error_msg = result.stdout + result.stderr
                # Truncate to avoid token explosion when feeding back to coder
                if len(error_msg) > 1500:
                    error_msg = error_msg[:1500] + "\n... [truncated]"
                errors.append(f"Command `{cmd}` failed:\n{error_msg}")
        except subprocess.TimeoutExpired:
            errors.append(f"Command `{cmd}` timed out after 120s")

    if errors:
        return False, "\n\n".join(errors)
    return True, ""


def execute_step(cfg: ForgeConfig) -> StepResult:
    """Execute the next step in the roadmap. This is the main pipeline loop."""

    # 1. Find next step
    step = find_next_step(cfg.memory_path, cfg.unchecked_pattern)
    if not step:
        return StepResult(
            status=StepStatus.NO_STEPS,
            step=None,
            summary="All steps in ROADMAP.md are complete. Nothing to do.",
        )

    logger.info(f"Starting Step {step.step_id}: {step.description}")

    # 2. Build coder context from memory bank
    context = get_coder_context(cfg.memory_path, step)
    memory_files = get_memory_file_paths(cfg.memory_path)
    current_model = cfg.models.coder

    # 3. Run coder
    coder_result = run_coder(
        model=current_model,
        message=context,
        project_path=cfg.project_path,
        read_only_files=memory_files,
        timeout=cfg.pipeline.aider_timeout,
    )

    if not coder_result.success and not coder_result.changed_files:
        # Coder completely failed to produce anything, try fallback model
        logger.warning(f"Primary coder ({current_model}) failed, trying fallback")
        current_model = cfg.models.coder_fallback
        coder_result = run_coder(
            model=current_model,
            message=context,
            project_path=cfg.project_path,
            read_only_files=memory_files,
            timeout=cfg.pipeline.aider_timeout,
        )

        if not coder_result.success and not coder_result.changed_files:
            return StepResult(
                status=StepStatus.FAILED,
                step=step,
                summary=f"Step {step.step_id} failed: Coder produced no output",
                details=coder_result.error,
            )

    # 4. Pre-commit hooks
    hook_retries = 0
    hooks_passed, hook_errors = (
        True,
        "",
    )  # default: pass (if max_hook_retries=0, skip loop)
    while hook_retries < cfg.pipeline.max_hook_retries:
        hooks_passed, hook_errors = run_pre_commit(
            cfg.project_path, cfg.pre_commit.commands
        )
        if hooks_passed:
            break

        hook_retries += 1
        logger.info(
            f"Pre-commit failed, retry {hook_retries}/{cfg.pipeline.max_hook_retries}"
        )

        if hook_retries >= cfg.pipeline.max_hook_retries:
            break

        # Feed hook errors back to coder
        retry_msg = f"""The pre-commit hooks failed on your code. Fix these specific issues:

{hook_errors}

Do NOT rewrite files from scratch. Fix only the specific issues above."""

        coder_result = run_coder(
            model=current_model,
            message=retry_msg,
            project_path=cfg.project_path,
            read_only_files=memory_files,
            timeout=cfg.pipeline.aider_timeout,
        )

    if not hooks_passed:
        return StepResult(
            status=StepStatus.FAILED,
            step=step,
            summary=f"Step {step.step_id} failed: Pre-commit hooks failed after {cfg.pipeline.max_hook_retries} retries",
            details=hook_errors,
        )

    # 5. Junior review loop
    junior_retries = 0
    junior_feedback = ""
    # Default: treat as PASS so escalation is skipped when max_junior_retries=0
    jr_result = type("_JrResult", (), {"output": "VERDICT: PASS"})()  # noqa: E501

    while junior_retries < cfg.pipeline.max_junior_retries:
        jr_result = run_junior_review(
            model=cfg.models.junior_reviewer,
            step_id=step.step_id,
            description=step.description,
            project_path=cfg.project_path,
        )

        if parse_verdict(jr_result.output):
            logger.info("Junior review: PASS")
            break

        junior_retries += 1
        junior_feedback = jr_result.output
        issues = extract_issues(jr_result.output)
        logger.info(
            f"Junior review: FAIL (retry {junior_retries}/{cfg.pipeline.max_junior_retries})"
        )

        if junior_retries >= cfg.pipeline.max_junior_retries:
            break

        # Feed junior issues back to coder
        retry_msg = f"""The code reviewer found issues with your implementation:

{issues}

Fix these specific issues. Do NOT rewrite files from scratch."""

        coder_result = run_coder(
            model=current_model,
            message=retry_msg,
            project_path=cfg.project_path,
            read_only_files=memory_files,
            timeout=cfg.pipeline.aider_timeout,
        )

        # Re-run hooks after coder fix
        hooks_passed, hook_errors = run_pre_commit(
            cfg.project_path, cfg.pre_commit.commands
        )
        if not hooks_passed:
            retry_msg = (
                f"Pre-commit hooks failed again:\n{hook_errors}\nFix these issues."
            )
            run_coder(
                model=current_model,
                message=retry_msg,
                project_path=cfg.project_path,
                read_only_files=memory_files,
                timeout=cfg.pipeline.aider_timeout,
            )

    # 6. If junior loop exhausted, escalate to senior for guidance
    senior_rounds = 0
    if junior_retries >= cfg.pipeline.max_junior_retries and not parse_verdict(
        jr_result.output
    ):
        logger.info("Junior loop exhausted, escalating to senior for guidance")

        while senior_rounds < cfg.pipeline.max_senior_rounds:
            guidance = get_senior_guidance(
                model=cfg.models.senior_reviewer,
                step_id=step.step_id,
                description=step.description,
                coder_output=coder_result.output[:1500],
                error=hook_errors if not hooks_passed else "",
                junior_feedback=junior_feedback,
                project_path=cfg.project_path,
            )

            # Feed senior guidance to coder
            retry_msg = f"""A senior engineer reviewed your stuck implementation and gave this guidance:

{guidance.output}

Follow this guidance precisely. Fix the issues described above."""

            coder_result = run_coder(
                model=current_model,
                message=retry_msg,
                project_path=cfg.project_path,
                read_only_files=memory_files,
                timeout=cfg.pipeline.aider_timeout,
            )

            # Quick hook + junior check
            hooks_passed, hook_errors = run_pre_commit(
                cfg.project_path, cfg.pre_commit.commands
            )
            if hooks_passed:
                jr_recheck = run_junior_review(
                    model=cfg.models.junior_reviewer,
                    step_id=step.step_id,
                    description=step.description,
                    project_path=cfg.project_path,
                )
                if parse_verdict(jr_recheck.output):
                    break

            senior_rounds += 1

        if senior_rounds >= cfg.pipeline.max_senior_rounds:
            return StepResult(
                status=StepStatus.FAILED,
                step=step,
                summary=f"Step {step.step_id} failed after senior escalation ({senior_rounds} rounds)",
                details=f"Last junior feedback:\n{junior_feedback}\n\nLast senior guidance:\n{guidance.output[:500]}",
            )

    # 7. Senior deep review (the quality gate)
    sr_result = run_senior_review(
        model=cfg.models.senior_reviewer,
        step_id=step.step_id,
        description=step.description,
        project_path=cfg.project_path,
    )

    if not parse_verdict(sr_result.output):
        # Senior found issues — one more coder attempt with senior's feedback
        issues = extract_issues(sr_result.output)
        logger.info("Senior review: FAIL — giving coder one more attempt")

        retry_msg = f"""The senior reviewer found issues with your implementation:

{issues}

This is the final review round. Fix these issues precisely."""

        coder_result = run_coder(
            model=current_model,
            message=retry_msg,
            project_path=cfg.project_path,
            read_only_files=memory_files,
            timeout=cfg.pipeline.aider_timeout,
        )

        # Re-run hooks
        hooks_passed, _ = run_pre_commit(cfg.project_path, cfg.pre_commit.commands)

        if hooks_passed:
            # Junior quick check
            jr_final = run_junior_review(
                model=cfg.models.junior_reviewer,
                step_id=step.step_id,
                description=step.description,
                project_path=cfg.project_path,
            )

            if parse_verdict(jr_final.output):
                # Senior final check
                sr_final = run_senior_review(
                    model=cfg.models.senior_reviewer,
                    step_id=step.step_id,
                    description=step.description,
                    project_path=cfg.project_path,
                )

                if not parse_verdict(sr_final.output):
                    return StepResult(
                        status=StepStatus.FAILED,
                        step=step,
                        summary=f"Step {step.step_id} failed final senior review",
                        details=sr_final.output[:1000],
                    )

                sr_result = sr_final  # Use final review as the summary
            else:
                return StepResult(
                    status=StepStatus.FAILED,
                    step=step,
                    summary=f"Step {step.step_id} failed junior re-check after senior feedback",
                    details=jr_final.output[:1000],
                )
        else:
            return StepResult(
                status=StepStatus.FAILED,
                step=step,
                summary=f"Step {step.step_id} failed pre-commit after senior feedback",
                details=hook_errors[:1000],
            )

    # 8. Success path — prepare for commit
    senior_summary = sr_result.output

    return StepResult(
        status=StepStatus.SUCCESS,
        step=step,
        summary=f"✅ Step {step.step_id}: {step.description}",
        details=senior_summary,
    )


def finalize_step(cfg: ForgeConfig, result: StepResult) -> None:
    """Commit changes, update memory bank, mark step complete.

    Called after user approves via Telegram.
    """
    if result.status != StepStatus.SUCCESS or result.step is None:
        return

    step = result.step

    # Commit
    commit_msg = f"feat({step.step_id}): {step.description}"
    if not commit_changes(cfg.project_path, commit_msg):
        logger.error("Commit failed during finalization")
        return

    update_memory(
        memory_path=cfg.memory_path,
        step=step,
        diff_summary=result.details[:1500],  # Use senior review as summary
        senior_review=result.details,
        model=cfg.models.context_updater,
    )

    logger.info(f"Step {step.step_id} finalized and committed")


def abandon_step(cfg: ForgeConfig) -> None:
    """Reset all uncommitted changes when a step fails."""
    reset_changes(cfg.project_path)
    logger.info("Abandoned step — all changes reset")
