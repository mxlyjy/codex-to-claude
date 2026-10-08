# v0.2.0 Preview — Codex → Claude Code

**One-command project migration. Preview first. Keep a way back.**

Codex → Claude Code helps you bring your project instructions, skills, and supported MCP settings to Claude Code.

This preview includes:

- Root and nested instruction conversion.
- Skills with their scripts, references, and assets.
- MCP configuration merging and environment-variable references.
- Optional user prompts, compatible agent instructions, and conversation text handoff.
- Conflict detection, verified backups, restoration, and write-failure rollback.
- JSON reports, 45 locally passing automated tests (43 original plus two path-validation regressions), and cross-platform CI configuration.

Start with a preview:

```bash
codex-to-claude --project /path/to/project
```

Then apply the supported changes:

```bash
codex-to-claude --project /path/to/project --apply
```

This is an early preview. On 2026-10-08, local verification passed on macOS 26.4.1 / arm64 / Python 3.11.15: compilation, installation, version checks, all 45 tests, and the example preview/apply/repeat/restore cycle. All 12 Linux/macOS/Windows × Python 3.11–3.14 jobs passed in [GitHub Actions run 37820171946](https://github.com/mxlyjy/codex-to-claude/actions/runs/37820171946) for source commit `33173a46325a51f3728971ceea29154cd2d3637d`: each Linux/macOS job passed all 45 tests; each Windows job passed 44 executed tests and skipped one POSIX executable-permission test (45 total). Live Claude Code loading / MCP connectivity remain unverified. Use a project copy first and check the actual CI results. Authentication, model settings, permissions, and native conversation state require manual setup.

Feedback and reproducible compatibility reports are welcome. Remove tokens and private content from reports.
