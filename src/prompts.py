"""Prompt loading utility for Forge.

Loads agent prompts from the `prompts/` directory.
"""

from pathlib import Path

# The Prompts directory is located at the root of the project, alongside src/
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_prompt(name: str) -> str:
    """Load a prompt template from prompts/<name>.md.

    Args:
        name: The basename of the prompt file (without .md)

    Returns:
        The contents of the prompt file as a string.

    Raises:
        FileNotFoundError: If the prompt file does not exist.
    """
    prompt_file = PROMPTS_DIR / f"{name}.md"
    if not prompt_file.exists():
        raise FileNotFoundError(
            f"Prompt file not found: {prompt_file}. "
            "Make sure the file exists in the prompts/ directory."
        )
    return prompt_file.read_text()
