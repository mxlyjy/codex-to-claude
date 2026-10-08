# Verification record

Prepared on 2026-09-30. Local verification updated on 2026-10-08.

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
2. All 43 unittest cases passed (43/43; exit status 0).
3. Package installation and console/module version checks passed; version output was 0.2.0.
4. Example preview wrote no project files; application generated six supported files.
5. Repeated example application made no additional changes and created no transaction.
6. Example restoration removed the six generated files and restored the original file bytes and permissions. The migration journal reported restored.
7. The 20 recovered source files matched the original bundle SHA-256 hashes before the publication documentation update. Only README.md, REVIEW.md, RELEASE_NOTES.md, and CHANGELOG.md received updated verification statements; program logic, examples, tests, and CI configuration are unchanged.

## Still unverified

The preparation environment had no Python runtime or terminal. The later local results above do not establish results for:

1. The 12 Linux/macOS/Windows × Python 3.11–3.14 GitHub Actions combinations.
2. Migration/restoration of a real personal Codex project.
3. Live Claude Code loading of instructions, skills, commands, agents, or MCP configuration.
4. MCP connectivity, authentication, and tool-limit behavior.
5. Recovery after power loss or forced process termination.

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
