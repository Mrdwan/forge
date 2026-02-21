"""Unit tests for src/reviewers.py."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.aider_client import AiderResult
from src.reviewers import (
    extract_issues,
    get_senior_guidance,
    parse_verdict,
    run_junior_review,
    run_senior_review,
)


def _make_aider_result(output: str = "", success: bool = True) -> AiderResult:
    return AiderResult(success=success, output=output, error="", changed_files=[])


# ---------------------------------------------------------------------------
# parse_verdict
# ---------------------------------------------------------------------------

class TestParseVerdict:
    def test_verdict_pass_line(self) -> None:
        assert parse_verdict("VERDICT: PASS\n\nSUMMARY: Looks good.") is True

    def test_verdict_fail_line(self) -> None:
        assert parse_verdict("VERDICT: FAIL\n\nISSUES:\n- Bug found") is False

    def test_verdict_case_insensitive(self) -> None:
        assert parse_verdict("verdict: pass\n\nsummary: ok") is True

    def test_verdict_fail_case_insensitive(self) -> None:
        assert parse_verdict("verdict: fail\n\nISSUES:\n- nope") is False

    def test_no_verdict_returns_false(self) -> None:
        assert parse_verdict("Everything looks good here actually.") is False

    def test_pass_in_irrelevant_context_still_passes(self) -> None:
        # "VERDICT: PASS" in the text → True even if surrounded by other words
        assert parse_verdict("Note: VERDICT: PASS you're done") is True

    def test_empty_string_returns_false(self) -> None:
        assert parse_verdict("") is False

    def test_multiple_lines_finds_verdict_line(self) -> None:
        review = (
            "Looking at the code...\n"
            "VERDICT: PASS\n"
            "SUMMARY: Nice work.\n"
        )
        assert parse_verdict(review) is True


# ---------------------------------------------------------------------------
# extract_issues
# ---------------------------------------------------------------------------

class TestExtractIssues:
    def test_extracts_bullet_points_from_issues(self) -> None:
        review = (
            "VERDICT: FAIL\n\n"
            "ISSUES:\n"
            "- Missing error handling\n"
            "- Off-by-one in loop\n\n"
            "SUMMARY: Bad code.\n"
        )
        result = extract_issues(review)
        assert "- Missing error handling" in result
        assert "- Off-by-one in loop" in result
        assert "SUMMARY" not in result

    def test_stops_at_summary_section(self) -> None:
        review = (
            "ISSUES:\n"
            "- Bug 1\n\n"
            "SUMMARY: short summary\n"
            "- This should NOT be captured\n"
        )
        result = extract_issues(review)
        assert "Bug 1" in result
        assert "This should NOT be captured" not in result

    def test_stops_at_suggestions_section(self) -> None:
        review = (
            "ISSUES:\n"
            "- Real issue\n\n"
            "SUGGESTIONS:\n"
            "- Optional suggestion\n"
        )
        result = extract_issues(review)
        assert "Real issue" in result
        assert "Optional suggestion" not in result

    def test_fallback_when_no_issues_header(self) -> None:
        review = "A" * 600  # 600 chars
        result = extract_issues(review)
        # Falls back to first 500 chars
        assert len(result) == 500

    def test_empty_issues_fallback(self) -> None:
        review = "ISSUES:\n\nSUMMARY: Nothing actually."
        result = extract_issues(review)
        # No bullets collected → fallback to truncated text
        assert len(result) <= 500

    def test_empty_string_returns_empty_truncation(self) -> None:
        result = extract_issues("")
        assert result == ""


# ---------------------------------------------------------------------------
# run_junior_review
# ---------------------------------------------------------------------------

class TestRunJuniorReview:
    def test_calls_run_reviewer_with_correct_args(self, tmp_path: Path) -> None:
        expected = _make_aider_result("VERDICT: PASS\n\nSUMMARY: ok")
        with (
            patch("src.reviewers.get_changed_files", return_value=["src/foo.py"]),
            patch("src.reviewers.get_diff", return_value="diff text"),
            patch("src.reviewers.run_reviewer", return_value=expected) as mock_reviewer,
        ):
            result = run_junior_review(
                model="test/junior",
                step_id="1.1",
                description="Do something",
                project_path=tmp_path,
            )

        assert result.output == "VERDICT: PASS\n\nSUMMARY: ok"
        mock_reviewer.assert_called_once()
        call_kwargs = mock_reviewer.call_args
        assert call_kwargs.kwargs["model"] == "test/junior"
        assert call_kwargs.kwargs["project_path"] == tmp_path

    def test_prompt_contains_step_info(self, tmp_path: Path) -> None:
        expected = _make_aider_result("VERDICT: PASS")
        with (
            patch("src.reviewers.get_changed_files", return_value=[]),
            patch("src.reviewers.get_diff", return_value=""),
            patch("src.reviewers.run_reviewer", return_value=expected) as mock_reviewer,
        ):
            run_junior_review("m", "2.5", "Build the scorer", tmp_path)

        prompt = mock_reviewer.call_args.kwargs["message"]
        assert "2.5" in prompt
        assert "Build the scorer" in prompt

    def test_no_changed_files_shows_placeholder(self, tmp_path: Path) -> None:
        expected = _make_aider_result("VERDICT: PASS")
        with (
            patch("src.reviewers.get_changed_files", return_value=[]),
            patch("src.reviewers.get_diff", return_value=""),
            patch("src.reviewers.run_reviewer", return_value=expected) as mock_reviewer,
        ):
            run_junior_review("m", "1.1", "Desc", tmp_path)

        prompt = mock_reviewer.call_args.kwargs["message"]
        assert "No files detected" in prompt


# ---------------------------------------------------------------------------
# run_senior_review
# ---------------------------------------------------------------------------

class TestRunSeniorReview:
    def test_calls_run_reviewer(self, tmp_path: Path) -> None:
        expected = _make_aider_result("VERDICT: PASS\n\nSUMMARY: great")
        with (
            patch("src.reviewers.get_changed_files", return_value=["src/bar.py"]),
            patch("src.reviewers.get_diff", return_value="some diff"),
            patch("src.reviewers.run_reviewer", return_value=expected) as mock_reviewer,
        ):
            result = run_senior_review("test/senior", "1.2", "Build bar", tmp_path)

        assert result.output == "VERDICT: PASS\n\nSUMMARY: great"
        mock_reviewer.assert_called_once()

    def test_prompt_contains_step_id(self, tmp_path: Path) -> None:
        expected = _make_aider_result("VERDICT: PASS")
        with (
            patch("src.reviewers.get_changed_files", return_value=[]),
            patch("src.reviewers.get_diff", return_value=""),
            patch("src.reviewers.run_reviewer", return_value=expected) as mock_reviewer,
        ):
            run_senior_review("m", "3.7", "Big feature", tmp_path)

        prompt = mock_reviewer.call_args.kwargs["message"]
        assert "3.7" in prompt
        assert "Big feature" in prompt


# ---------------------------------------------------------------------------
# get_senior_guidance
# ---------------------------------------------------------------------------

class TestGetSeniorGuidance:
    def test_calls_run_reviewer_with_guidance_prompt(self, tmp_path: Path) -> None:
        expected = _make_aider_result("Fix the error handling in foo.py")
        with (
            patch("src.reviewers.get_changed_files", return_value=["src/foo.py"]),
            patch("src.reviewers.run_reviewer", return_value=expected) as mock_reviewer,
        ):
            result = get_senior_guidance(
                model="test/senior",
                step_id="1.1",
                description="Build foo",
                coder_output="I tried to build foo",
                error="Tests failed",
                junior_feedback="Missing error handling",
                project_path=tmp_path,
            )

        assert "Fix the error handling" in result.output
        mock_reviewer.assert_called_once()

    def test_prompt_truncates_long_inputs(self, tmp_path: Path) -> None:
        expected = _make_aider_result("guidance")
        long_output = "x" * 3000
        long_error = "e" * 2000
        long_feedback = "f" * 2000
        with (
            patch("src.reviewers.get_changed_files", return_value=[]),
            patch("src.reviewers.run_reviewer", return_value=expected) as mock_reviewer,
        ):
            get_senior_guidance("m", "1.1", "desc", long_output, long_error, long_feedback, tmp_path)

        prompt = mock_reviewer.call_args.kwargs["message"]
        # Coder output truncated to 1500
        assert len(prompt) < 3000 + 2000 + 2000 + 1000
