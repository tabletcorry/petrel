# Contributor Guide

Create pytest unit tests for all new code.

## Dev Environment Tips
- The environment is managed with `uv`
- Run scripts and tools by calling `uv run ...`
- Python can be called with `uv run python`
- Use `# noqa` and `# type: ignore` rarely.

## Testing Instructions
- Run the following tools to look for issues in new code. However, do not fix pre-existing errors on lines you didn't touch.
  - Run `uv run ruff format ...` to format all code to the appropriate standard.
  - Run `uv run ruff check ...` to check for linting and other issues.
  - Run `uv run mypy ...` to check for type issues.
  - Run `uv run pytest` to run tests.
  - Use `pre-commit run --files ...` to check that your changes pass the pre-commit checks. Run this last.
- Add or update tests for the code you change, even if nobody asked.
