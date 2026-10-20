# Repository Guidelines

## Project Structure & Module Organization

This directory currently contains no application code, tests, assets, or build configuration. Treat the following layout as a starting convention when adding the first implementation:

- `src/`: application code, grouped by feature or responsibility.
- `tests/`: automated tests, organized to mirror the source modules.
- `assets/`: static resources required by the application.
- `docs/`: architecture notes and contributor documentation.

Create directories only when needed. Add a `README.md` describing the project's purpose, prerequisites, and setup once the implementation is established.

## Build, Test, and Development Commands

No build, test, or local development commands are configured yet. When introducing tooling, document the exact installation, development, build, and test commands in `README.md`. Keep these commands aligned with checked-in configuration and update this guide accordingly. Do not assume commands such as `npm test` or `make build` are available.

## Coding Style & Naming Conventions

No language, formatter, or linter has been selected. Use the chosen language's standard conventions and commit formatter or linter configuration with the initial implementation. Keep indentation consistent within each file. Choose descriptive names, group related functionality, and avoid mixing unrelated changes in one contribution.

## Testing Guidelines

No testing framework or coverage threshold exists yet. Add an appropriate test runner with the first testable functionality and document how to run it. Use the framework's standard test filename pattern and descriptive test names. Cover new behavior and include regression tests for bug fixes.

## Commit & Pull Request Guidelines

This directory has no Git history from which to infer commit conventions. Once Git is initialized, use concise, imperative commit subjects, such as `Add initial application scaffold`. Keep commits focused.

Pull requests should explain the change, its purpose, and validation performed. Link relevant issues when available, and include screenshots for visible interface changes. Explicitly identify checks that could not be run.

## Security & Configuration

Keep credentials, local environment files, and generated outputs out of version control. Provide placeholder configuration examples and document required environment variables when configuration is introduced.
