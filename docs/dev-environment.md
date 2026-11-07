# Your work environment, in plain words

This page explains the environment files and how to start working.

## Start in the browser (recommended)
1. Open the repository on GitHub.
2. Choose **Code**, then **Codespaces**, then **Create codespace on main**.
3. Wait a few minutes the first time. GitHub builds the workspace for you.
4. In the terminal at the bottom, type `make test`.

If the tests pass, your environment works. You have installed nothing on your own computer.

Codespaces has a monthly free allowance on personal accounts. Check it under GitHub **Settings → Billing and plans**. Stop the codespace when you finish.

## What each file does

| File | What it is |
|---|---|
| `.devcontainer/devcontainer.json` | The recipe for the workspace: Python 3.11, Java 17 (Spark needs it), the GitHub tool, and the editor add-ons. It then runs `make setup` |
| `pyproject.toml` | The list of Python tools the project uses, with exact versions for Spark and Delta Lake, so everyone gets the same ones |
| `Makefile` | Short commands: `make setup`, `make test`, `make lint`, `make format` |
| `.pre-commit-config.yaml` | Small automatic checks that run before each commit: tidy spaces, no private keys, no huge files, code style |
| `src/lakehouse/` | The folder where the project code will live. It is almost empty for now |
| `tests/conftest.py` | A helper that starts a small Spark session for tests that need one |
| `tests/test_environment.py` | Three small tests that check the environment itself works |

## Useful commands

| Command | What it does |
|---|---|
| `make setup` | Installs the project and its tools |
| `make test` | Runs all tests. The first run is slower, because Spark downloads some files |
| `make test-fast` | Runs only the tests that do not need Spark |
| `make lint` | Checks code style |
| `make format` | Fixes code style automatically |

## Status
The recipe has been tested for its Python parts in the build environment. It has **not** been tested in GitHub Codespaces yet. The first time you open it is the real test. If something fails, copy the message into an issue or tell your mentor.
