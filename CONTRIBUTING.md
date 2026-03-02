# Contributing to SkopaqTrader

Thank you for your interest in contributing to SkopaqTrader! This document provides guidelines for contributing to the project.

## Getting Started

1. **Fork** the repository on GitHub
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/<your-username>/skopaqtrader.git
   cd skopaqtrader
   ```
3. **Set up** the development environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   ```
4. **Create a branch** for your changes:
   ```bash
   git checkout -b feature/my-feature
   ```

## Development Guidelines

### Code Style

- We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting
- Line length: 100 characters
- Target Python version: 3.11+
- Run the linter before committing:
  ```bash
  ruff check .
  ruff format .
  ```

### Project Organization

- **`skopaq/`** — All new SkopaqTrader code goes here
- **`tradingagents/`** — Vendored upstream code. Modify only when necessary, and document every change in `UPSTREAM_CHANGES.md`
- **`tests/unit/`** — Unit tests (no external API calls)
- **`tests/integration/`** — Integration tests (require API keys, marked with `@pytest.mark.integration`)

### Upstream Modification Policy

The `tradingagents/` directory is vendored from [TradingAgents v0.2.0](https://github.com/TauricResearch/TradingAgents). Changes to this directory must:

1. Be **minimal and surgical** — prefer wrapping over modifying
2. Be **backward compatible** — upstream behavior unchanged when Skopaq extensions are absent
3. Be **documented** in `UPSTREAM_CHANGES.md` with: what changed, why, and backward compatibility status

### Testing

- Write tests for all new functionality
- Unit tests should not require API keys or external services
- Use `unittest.mock` and `respx` for mocking HTTP calls

```bash
# Run unit tests
python -m pytest tests/unit/ -v

# Run integration tests (requires .env with API keys)
python -m pytest tests/integration/ -v -m integration
```

### Commit Messages

Use clear, descriptive commit messages:

```
feat: add multi-model scanner engine
fix: handle Gemini 3 list content format
docs: update UPSTREAM_CHANGES with setup.py modification
test: add unit tests for safety checker
```

## Pull Request Process

1. Ensure all unit tests pass
2. Update documentation if your change affects public APIs
3. Update `UPSTREAM_CHANGES.md` if you modify vendored code
4. Write a clear PR description explaining the change and motivation
5. PRs require review before merging

## Reporting Issues

- Use GitHub Issues for bug reports and feature requests
- Include steps to reproduce for bugs
- Include your Python version and relevant API provider

## Code of Conduct

Be respectful, constructive, and inclusive. We're building something together.

## Upstream Community

This project builds on the [TradingAgents](https://github.com/TauricResearch/TradingAgents) framework by [TauricResearch](https://tauric.ai/). If your contribution relates to the upstream framework, consider also contributing there.

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).
