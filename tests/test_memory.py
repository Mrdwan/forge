"""Unit tests for src/memory.py."""

from pathlib import Path
from unittest.mock import MagicMock, patch


from src.memory import (
    Step,
    ensure_memory_bank,
    find_next_step,
    get_coder_context,
    get_memory_file_paths,
    update_memory,
)

UNCHECKED = r"^\s*-\s*\[ \]\s*\*{0,2}Step\s+(\d+\.\d+):?\*{0,2}\s*(.*)"
CHECKED = r"^\s*-\s*\[x\]\s*\*{0,2}Step\s+(\d+\.\d+):?\*{0,2}\s*(.*)"


# ---------------------------------------------------------------------------
# ensure_memory_bank
# ---------------------------------------------------------------------------


class TestEnsureMemoryBank:
    def test_creates_directory_and_all_five_files(self, tmp_path: Path) -> None:
        mem = tmp_path / "memory"
        ensure_memory_bank(mem)
        assert mem.is_dir()
        for f in ["ARCHITECTURE.md", "ROADMAP.md", "DECISIONS.md"]:
            assert (mem / f).exists(), f"{f} not created"

    def test_does_not_overwrite_existing_files(self, tmp_path: Path) -> None:
        mem = tmp_path / "memory"
        mem.mkdir()
        custom = "# My custom content\n"
        (mem / "ARCHITECTURE.md").write_text(custom)
        ensure_memory_bank(mem)
        assert (mem / "ARCHITECTURE.md").read_text() == custom

    def test_creates_missing_files_when_some_exist(self, tmp_path: Path) -> None:
        mem = tmp_path / "memory"
        mem.mkdir()
        (mem / "ARCHITECTURE.md").write_text("existing\n")
        ensure_memory_bank(mem)
        # New file was created
        assert (mem / "ROADMAP.md").exists()
        # Existing was preserved
        assert (mem / "ARCHITECTURE.md").read_text() == "existing\n"

    def test_idempotent_on_second_call(self, tmp_path: Path) -> None:
        mem = tmp_path / "memory"
        ensure_memory_bank(mem)
        ensure_memory_bank(mem)  # second call should not raise
        assert mem.is_dir()


# ---------------------------------------------------------------------------
# find_next_step
# ---------------------------------------------------------------------------


class TestFindNextStep:
    def test_finds_first_unchecked_step(self, memory_path: Path) -> None:
        step = find_next_step(memory_path, UNCHECKED)
        assert step is not None
        assert step.step_id == "1.1"
        assert step.description == "Build the first thing"

    def test_skips_checked_steps(self, memory_path: Path) -> None:
        roadmap = memory_path / "ROADMAP.md"
        roadmap.write_text(
            "# Roadmap\n\n"
            "- [x] Step 1.1: Done already\n"
            "- [ ] Step 1.2: Build the second thing\n"
        )
        step = find_next_step(memory_path, UNCHECKED)
        assert step is not None
        assert step.step_id == "1.2"

    def test_returns_none_when_all_checked(self, memory_path: Path) -> None:
        roadmap = memory_path / "ROADMAP.md"
        roadmap.write_text(
            "# Roadmap\n\n- [x] Step 1.1: Done\n- [x] Step 1.2: Also done\n"
        )
        step = find_next_step(memory_path, UNCHECKED)
        assert step is None

    def test_returns_none_when_roadmap_missing(self, tmp_path: Path) -> None:
        mem = tmp_path / "no_memory"
        mem.mkdir()
        step = find_next_step(mem, UNCHECKED)
        assert step is None

    def test_raw_line_preserved(self, memory_path: Path) -> None:
        step = find_next_step(memory_path, UNCHECKED)
        assert step is not None
        assert "Step 1.1" in step.raw_line
        assert "[ ]" in step.raw_line

    def test_description_stripped_of_whitespace(self, memory_path: Path) -> None:
        roadmap = memory_path / "ROADMAP.md"
        roadmap.write_text("- [ ] Step 2.3:  Extra spaces here  \n")
        step = find_next_step(memory_path, UNCHECKED)
        assert step is not None
        assert step.description == "Extra spaces here"


# ---------------------------------------------------------------------------
# get_coder_context
# ---------------------------------------------------------------------------


class TestGetCoderContext:
    def test_includes_memory_file_contents(
        self, memory_path: Path, sample_step: Step
    ) -> None:
        context = get_coder_context(memory_path, sample_step)
        assert "System description" in context
        assert "Some decisions" in context
        assert "Build the first thing" in context  # from ROADMAP.md

    def test_includes_task_prompt(self, memory_path: Path, sample_step: Step) -> None:
        context = get_coder_context(memory_path, sample_step)
        assert "Step 1.1" in context
        assert "Build the first thing" in context
        assert "pytest tests" in context.lower() or "tests" in context

    def test_handles_missing_memory_files(
        self, tmp_path: Path, sample_step: Step
    ) -> None:
        """Should not crash when some memory files don't exist."""
        mem = tmp_path / "empty_memory"
        mem.mkdir()
        context = get_coder_context(mem, sample_step)
        # Still has the task section
        assert "Step 1.1" in context

    def test_includes_plan_file_if_exists(
        self, memory_path: Path, sample_step: Step
    ) -> None:
        plan_dir = memory_path.parent / "docs" / "plans"
        plan_dir.mkdir(parents=True)
        (plan_dir / "plan_1.1_my_plan.md").write_text(
            "# Detailed Plan\n\nDo it this way.\n"
        )
        context = get_coder_context(memory_path, sample_step)
        assert "Do it this way" in context

    def test_no_crash_when_plan_dir_missing(
        self, memory_path: Path, sample_step: Step
    ) -> None:
        context = get_coder_context(memory_path, sample_step)
        assert "Step 1.1" in context


# ---------------------------------------------------------------------------
# get_memory_file_paths
# ---------------------------------------------------------------------------


class TestGetMemoryFilePaths:
    def test_returns_paths_for_existing_files(self, memory_path: Path) -> None:
        paths = get_memory_file_paths(memory_path)
        assert "memory/ARCHITECTURE.md" in paths
        assert "memory/DECISIONS.md" in paths
        # ROADMAP is not in the list for a coder to write back to, memory handler will pass it automatically
        assert "memory/ROADMAP.md" not in paths

    def test_missing_files_excluded(self, tmp_path: Path) -> None:
        mem = tmp_path / "memory"
        mem.mkdir()
        (mem / "ARCHITECTURE.md").write_text("arch\n")
        paths = get_memory_file_paths(mem)
        assert len(paths) == 1
        assert "memory/ARCHITECTURE.md" in paths


# ---------------------------------------------------------------------------
# update_memory
# ---------------------------------------------------------------------------


class TestUpdateMemory:
    _SAMPLE_RESPONSE = (
        "===ROADMAP===\n"
        "# Roadmap\n\n- [x] Step 1.1: Build the thing\n> Built the thing.\n"
        "===ARCHITECTURE===\n"
        "# Architecture\n\nUpdated arch.\n"
        "===DECISIONS===\n"
        "# Decisions\n\nNew decision.\n"
    )

    def _mock_response(self, text: str) -> MagicMock:
        msg = MagicMock()
        msg.content = text
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        return resp

    def test_happy_path_writes_all_sections(
        self, memory_path: Path, sample_step: Step
    ) -> None:
        with patch(
            "src.memory.litellm.completion",
            return_value=self._mock_response(self._SAMPLE_RESPONSE),
        ):
            update_memory(
                memory_path,
                sample_step,
                "diff content",
                "senior review text",
                "test/model",
            )

        assert "Built the thing." in (memory_path / "ROADMAP.md").read_text()
        assert "Updated arch." in (memory_path / "ARCHITECTURE.md").read_text()
        assert "New decision." in (memory_path / "DECISIONS.md").read_text()

    def test_malformed_response_section_skipping(
        self, memory_path: Path, sample_step: Step
    ) -> None:
        """If response has only ROADMAP, other files should be unchanged."""
        partial = "===ROADMAP===\n# Roadmap\n\n- [x] Step 1.1: done\n> Done.\n"
        original_arch = (memory_path / "ARCHITECTURE.md").read_text()
        with patch(
            "src.memory.litellm.completion", return_value=self._mock_response(partial)
        ):
            update_memory(memory_path, sample_step, "diff", "review", "test/model")

        assert "Done." in (memory_path / "ROADMAP.md").read_text()
        assert (memory_path / "ARCHITECTURE.md").read_text() == original_arch

    def test_exception_triggers_fallback_append(
        self, memory_path: Path, sample_step: Step
    ) -> None:
        with patch(
            "src.memory.litellm.completion", side_effect=RuntimeError("API down")
        ):
            update_memory(
                memory_path, sample_step, "diff content", "review", "test/model"
            )

        new_roadmap = (memory_path / "ROADMAP.md").read_text()
        # Fallback checked off only the completed step
        assert "- [x] Step 1.1" in new_roadmap
        assert "- [ ] Step 1.1" not in new_roadmap
        # Other unchecked steps are unaffected
        assert "- [ ] Step 1.2" in new_roadmap

    def test_exception_when_roadmap_missing(
        self, memory_path: Path, sample_step: Step
    ) -> None:
        """Should not crash if ROADMAP.md is missing when an exception occurs."""
        (memory_path / "ROADMAP.md").unlink()
        with patch(
            "src.memory.litellm.completion", side_effect=RuntimeError("API down")
        ):
            update_memory(memory_path, sample_step, "diff", "review", "test/model")

        assert not (memory_path / "ROADMAP.md").exists()
