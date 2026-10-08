# Changelog

## 0.2.0 — Early preview

- Migrate root and nested project instructions, including override precedence.
- Copy compatible skills with scripts, references, and binary resources.
- Merge supported MCP settings while preserving unrelated servers.
- Reference shell variables instead of copying literal env values by default.
- Optionally import user assets, prompts, basic agent instructions, and a selected conversation transcript.
- Add conflict checks, transaction journals, verified backups, restoration, and failure rollback.
- Add JSON reports, installation metadata, examples, and MIT licensing.
- Author 43 tests and a cross-platform GitHub Actions matrix.

Local verification on 2026-10-08 passed on macOS 26.4.1 / arm64 / Python 3.11.15: compilation, installation, version checks, all 43 tests, and example preview/apply/repeat/restore. The 12 GitHub Actions OS/Python combinations and live Claude Code loading / MCP connectivity remain unverified. This is a preview, not a verified stable release.
