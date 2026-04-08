<!--
SYNC IMPACT REPORT
==================
Version change: (new project) → 1.0.0
Modified principles: N/A (initial ratification)
Added sections:
  - Core Principles (5 principles)
  - Target Technology Stack
  - Quality & Testing Standards
  - macOS Platform Requirements
  - Governance
Removed sections: N/A (initial ratification)
Templates requiring updates:
  ✅ .specify/memory/constitution.md — this file (created)
  ✅ .specify/memory/spec.md — created and aligned with these principles
Deferred TODOs: None — all placeholders resolved.
-->

# Screenshot Capture Tool Constitution

## Migration Mode

**Mode**: REWRITE

New project built from scratch with a purpose-selected Python technology stack.
No legacy codebase exists; target is a clean, self-contained desktop application.

**Justification**: There is no prior implementation. The project starts from a blank
repository; a REWRITE (green-field) approach is the only applicable mode.

## Core Principles

### I. Simplicity First

The application MUST do exactly one thing well: capture and save screenshots.
Every UI element, module, and API surface MUST justify its existence against this goal.
Features that add complexity without proportional user value MUST NOT be added.
YAGNI (You Aren't Gonna Need It) is the default decision filter for scope decisions.

### II. Platform-Native Compatibility

The application MUST run correctly on macOS (12 Monterey and later) without workarounds.
Requirements covered: Retina/HiDPI display handling, macOS Screen Recording permission
flow, correct coordinate mapping on multi-monitor setups, and native look-and-feel via
CustomTkinter theming. Platform-specific code MUST be isolated in a dedicated
`platform_utils.py` module and MUST NOT bleed into core logic.

### III. Test-Driven Development (NON-NEGOTIABLE)

This requirement MUST be followed for all future development. The core modules
(`capture.py`, `storage.py`, `shortcuts.py`, `preview.py`, `beautify.py`,
`platform_utils.py`, `app.py`) are pre-existing and were developed alongside their
test suites; TDD does not apply retroactively to them.
For any new module or non-trivial feature added going forward, tests MUST be written
before implementation code. The Red–Green–Refactor cycle is mandatory.
Unit tests MUST cover: capture logic, filename generation, folder resolution, and all
error-path branches. GUI interactions are excluded from automated unit tests but MUST
have manual acceptance criteria documented in the spec before development begins.

### IV. Explicit Error Handling

Every I/O boundary (screenshot capture, file save, folder open) MUST handle failures
explicitly. Errors MUST surface as human-readable status messages in the UI status bar;
they MUST NOT silently pass or propagate uncaught exceptions to the user.
Permission errors (Screen Recording on macOS) MUST be detected on startup and MUST
guide the user to System Settings with a clear, actionable message.

### V. Privacy by Default

The application MUST NOT transmit any data over a network.
No telemetry, analytics, crash reporting, or update checks are permitted.
All captured images are stored exclusively in the local `~/Screenshots/` folder.
No metadata beyond the timestamp-based filename is attached to saved files.

## Target Technology Stack

| Component        | Target Version    | Notes                                                                   |
| ---------------- | ----------------- | ----------------------------------------------------------------------- |
| Python           | 3.11+             | Required for `tomllib`, structural pattern match                        |
| GUI Framework    | CustomTkinter 5.x | Modern themed widgets built on tkinter; verify compatibility with 5.2.2 |
| Screenshot Lib   | mss 10.x          | Fast, cross-platform screen capture                                     |
| Image Processing | Pillow 12.x       | Resize, crop, `ImageTk` for live preview                                |
| Build/Packaging  | PyInstaller 6.x   | Single-file `.app` bundle for macOS; verify compatibility with 6.19.0   |
| Test Framework   | pytest 9.x        | With `pytest-mock` for I/O mocking                                      |
| Linter           | ruff              | Unified lint + format tool                                              |

## Quality & Testing Standards

All public functions in non-GUI modules MUST have at least one passing unit test.
Test coverage for `capture.py`, `storage.py`, and `shortcuts.py` MUST reach ≥ 80%.
GUI modules (`app.py`) are exempt from automated coverage requirements but MUST pass
all acceptance criteria documented in the spec before each release.
Every pull request MUST pass `ruff check .` with zero violations before merge.

## macOS Platform Requirements

The app MUST request and gracefully handle the macOS Screen Recording permission
(required since macOS 10.15 Catalina for programmatic screenshot capture by third-party
apps). On first launch, if permission is absent, the app MUST display a dialog that
opens `System Settings → Privacy & Security → Screen Recording` directly.
Retina display scaling MUST be handled by using `mss`'s native DPI-aware capture
followed by Pillow downscaling before preview display, ensuring 1:1 logical pixels.
The `~/Screenshots/` save folder MUST be created via `pathlib.Path.mkdir(parents=True,
exist_ok=True)` to avoid errors on first run or sandboxed environments.

## Governance

This constitution supersedes all ad-hoc coding conventions for this project.
Amendments require: a written rationale, a version bump per semantic versioning rules
(MAJOR — principle removal or redefinition; MINOR — new principle or section added;
PATCH — wording clarification or typo fix), and an update to this file before the
relevant code change is merged.
All contributors MUST verify compliance with these principles during code review.
Runtime development guidance lives in `README.md`.

**Version**: 1.0.0 | **Ratified**: 2026-04-05 | **Last Amended**: 2026-04-05
