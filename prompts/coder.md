## Your Task

Implement Step {step_id}: {description}

Read the architecture and progress above to understand the current state of the project.
Figure out what files need to be created or modified. Write clean, well-tested code.

Requirements:
- Write pytest tests for your implementation (in tests/ directory)
- Use type hints on all function signatures (use modern syntax like `X | None` instead of `Optional[X]`, and builtins like `list`/`dict` instead of `List`/`Dict`)
- Ensure your code passes `ruff check` (no unused imports, variables, etc)
- Use Google-style docstrings on public methods
- Catch specific exceptions, never bare except
- If this step involves rolling calculations, guard every .where() and division against NaN
- Run your new tests to verify they pass before finishing

After implementing, briefly summarize what you built and which files you created/modified.
