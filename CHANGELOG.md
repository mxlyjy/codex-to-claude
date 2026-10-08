# Changelog

## 0.2.0 — Early preview

- Migrate root and nested project instructions, including override precedence.
- Copy compatible skills with scripts, references, and binary resources.
- Merge supported MCP settings while preserving unrelated servers.
- Reference shell variables instead of copying literal env values by default.
- Optionally import user assets, prompts, basic agent instructions, and a selected conversation transcript.
- Add conflict checks, transaction journals, verified backups, restoration, and failure rollback.
- Add JSON reports, installation metadata, examples, and MIT licensing.
- Author 43 tests and a cross-platform GitHub Actions matrix; add two path-validation regressions (45 total).
- Fix the initial Windows CI failure by rejecting anchored paths, including drive-less rooted paths, in safe_path.

Local verification on 2026-10-08 passed on macOS 26.4.1 / arm64 / Python 3.11.15: compilation, installation, version checks, all 45 tests, and example preview/apply/repeat/restore. All 12 Linux/macOS/Windows × Python 3.11–3.14 jobs passed in [GitHub Actions run 37820171946](https://github.com/mxlyjy/codex-to-claude/actions/runs/37820171946) for source commit `33173a46325a51f3728971ceea29154cd2d3637d`: each Linux/macOS job passed all 45 tests; each Windows job passed 44 executed tests and skipped one POSIX executable-permission test (45 total). Live Claude Code loading / MCP connectivity remain unverified. This is a preview, not a verified stable release.
