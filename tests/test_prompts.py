import pytest
from src.prompts import load_prompt

EXPECTED_PROMPTS = [
    "coder",
    "junior_reviewer",
    "senior_guidance",
    "senior_reviewer",
    "memory_updater",
]


def test_load_prompt_returns_string() -> None:
    content = load_prompt("coder")
    assert isinstance(content, str)
    assert len(content) > 0
    assert "Your Task" in content


def test_load_prompt_missing_file_raises() -> None:
    with pytest.raises(FileNotFoundError, match="Prompt file not found"):
        load_prompt("does_not_exist_xyz555")


@pytest.mark.parametrize("prompt_name", EXPECTED_PROMPTS)
def test_all_expected_prompts_exist(prompt_name: str) -> None:
    # Ensure all expected files exist and are loadable
    content = load_prompt(prompt_name)
    assert len(content.strip()) > 0

    # Check that they compile successfully as string templates
    # This prevents syntax errors like unbalanced curly braces {} in the markdown
    # Just format with dummy kwargs since we don't know the exact args for all of them
    try:

        class DummyDict(dict):
            def __missing__(self, key):
                return f"{{{key}}}"

        content.format_map(DummyDict())
    except Exception as e:
        pytest.fail(f"Prompt '{prompt_name}' failed to parse as a template string: {e}")
