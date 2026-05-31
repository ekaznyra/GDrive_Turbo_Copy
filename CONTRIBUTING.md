# Contributing to Google Drive Transfer Colab

Thank you for your interest in contributing! This guide explains how you can help improve this project.

## How to Contribute

### Reporting Bugs

If you encounter a bug, please [open an issue](https://github.com/mnoumanhanif/google-drive-transfer-colab/issues/new?template=bug_report.md) and include:

- A clear description of the problem
- Steps to reproduce the issue
- Expected vs. actual behavior
- Screenshots or error messages (if applicable)
- Your environment details (browser, Google account type)

### Suggesting Features

Have an idea for an improvement? [Open a feature request](https://github.com/mnoumanhanif/google-drive-transfer-colab/issues/new?template=feature_request.md) and describe:

- The problem you want to solve
- Your proposed solution
- Any alternatives you've considered

### Submitting Pull Requests

1. **Fork** the repository
2. **Create a branch** for your change:
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **Make your changes** — follow the guidelines below
4. **Test your changes** by running the notebook in Google Colab
5. **Commit** with a clear message:
   ```bash
   git commit -m "Add: brief description of your change"
   ```
6. **Push** to your fork and open a pull request

## Development Guidelines

### Notebook Structure

The Colab notebook follows this structure:

1. **Markdown cells** — Provide context, instructions, and section headers
2. **Code cells** — Contain the executable Python code
3. Each major feature is contained in a single cell with `#@title` for Colab forms

### Code Style

- Use clear, descriptive variable and function names
- Add docstrings to all functions
- Include inline comments for complex logic
- Use emoji indicators for user-facing output:
  - `✅` for success messages
  - `❌` for errors
  - `⚠️` for warnings
  - `📁` for folder-related info

### Commit Messages

Use clear, descriptive commit messages:

- `Add: description` — for new features
- `Fix: description` — for bug fixes
- `Docs: description` — for documentation changes
- `Refactor: description` — for code restructuring

## Code of Conduct

Please be respectful and constructive in all interactions. We are committed to providing a welcoming and inclusive experience for everyone.

## Questions?

If you have questions about contributing, feel free to [open an issue](https://github.com/mnoumanhanif/google-drive-transfer-colab/issues) and we'll be happy to help.
