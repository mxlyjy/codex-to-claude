# Verification record

Prepared on 2026-09-30. Local and GitHub Actions verification updated on 2026-10-08.

## Completed

- Compared MCP, env_vars, skill selectors, and agent-role fields with the official Codex configuration schema.
- Read official GitHub documentation and Claude's repository examples for MCP and skill formats.
- Reviewed configuration merging, conflict handling, backup hashes, restoration checks, transaction states, and write-failure recovery.
- Added nested instructions, skill resources, optional user assets, prompts, compatible agent instructions, and selected rollout text export.
- Checked bundle filenames for traversal and case-insensitive collisions.
- Checked JSON packing/unpacking and saved generator contents against all bundled files.
- Performed text-level delimiter/string balance checks. These are not Python syntax compilation.
- Authored 43 unittest cases and a Linux/macOS/Windows × Python 3.11–3.14 CI matrix.

No personal Codex configuration or credentials were included in the source bundle.

## Executed locally on 2026-10-08

Environment: macOS 26.4.1 (arm64), Python 3.11.15, PyYAML 6.0.3, isolated virtual environment.

1. Python compileall completed with exit status 0.
2. All 45 unittest cases passed (45/45; exit status 0): the 43 original tests plus two path-validation regressions.
3. Package installation and console/module version checks passed; version output was 0.2.0.
4. Example preview wrote no project files; application generated six supported files.
5. Repeated example application made no additional changes and created no transaction.
6. Example restoration removed the six generated files and restored the original file bytes and permissions. The migration journal reported restored.
7. The 20 recovered source files matched the original bundle SHA-256 hashes before the publication documentation update. The publication includes a scoped Windows path-validation fix in codex_to_claude/core.py, two regression tests in tests/test_migration.py, and updated verification statements in README.md, REVIEW.md, RELEASE_NOTES.md, and CHANGELOG.md. Examples and CI configuration are unchanged.

## GitHub Actions results on 2026-10-08

- Initial [run 37819521916](https://github.com/mxlyjy/codex-to-claude/actions/runs/37819521916), source commit `fb83ff526e464fb2737541ec6769b130e8a23ff8`: eight Linux/macOS jobs passed; four Windows jobs failed `test_path_traversal_and_state_targets_refused`.
- Root cause: a drive-less Windows rooted path such as `/absolute` has an anchor but can return false from `is_absolute()`. The path gate now rejects `path.anchor` rather than only `path.is_absolute()`. Two regressions cover rooted paths for POSIX/Windows path flavours and valid project-relative paths. A local PureWindowsPath probe is a path-semantics check, not execution on Windows.
- All 12 Linux/macOS/Windows × Python 3.11–3.14 jobs passed in [GitHub Actions run 37820171946](https://github.com/mxlyjy/codex-to-claude/actions/runs/37820171946) for source commit `33173a46325a51f3728971ceea29154cd2d3637d`: each Linux/macOS job passed all 45 tests; each Windows job passed 44 executed tests and skipped one POSIX executable-permission test (45 total).
- Installation, compileall, unittest, and the 0.2.0 version check succeeded in every job. The previously failing Windows path-validation case now passes.
- The CI result is tied to the source commit above; it does not claim that a later documentation-only commit has already been checked.

## Still unverified

The preparation environment had no Python runtime or terminal. The later local results above do not establish results for:

1. Migration/restoration of a real personal Codex project.
2. Live Claude Code loading of instructions, skills, commands, agents, or MCP configuration.
3. MCP connectivity, authentication, and tool-limit behavior.
4. Recovery after power loss or forced process termination.

Publication does not establish these results. Update this record only when actual results are available.

## Known limits

- Migration reads selected user/project layers, not the complete runtime configuration chain.
- Models, permissions, sandboxes, hooks, plugins, credentials, and memory state are not automatically converted.
- Agent conversion is limited to compatible instruction-only roles.
- Conversation export is a reference transcript, not native Claude session resumption.
- Literal env values become shell references by default; other source or existing content may still contain secrets.
- Per-file atomic replacement does not guarantee an atomic project transaction or power-loss durability.
- External documentation websites and installed runtime versions were not directly verified.

## Reproduce the checks locally

```bash
python -m pip install .
python -m compileall -q codex_to_claude tests
python -m unittest discover -v
codex-to-claude --version
codex-to-claude --project examples/demo --codex-home examples/codex-home --json
```

First use the example project or a copy. Check application, repeat runs, conflict handling, and restoration before using personal configuration.
