# Codex → Claude Code

**One-command project migration. Preview first. Keep a way back.**

Move project instructions, skills, and supported MCP settings from Codex to Claude Code. Inspect the plan, apply it in one command, and restore the original files if needed.

**Status: early preview (v0.2.0).** Source review and bundle integrity checks are complete. On 2026-10-08, local verification passed on macOS 26.4.1 / arm64 / Python 3.11.15: compilation, package installation, version checks, all 45 automated tests, and example preview, application, repeat application, and restoration. All 12 Linux/macOS/Windows × Python 3.11–3.14 jobs passed in [GitHub Actions run 37820171946](https://github.com/mxlyjy/codex-to-claude/actions/runs/37820171946) for source commit `33173a46325a51f3728971ceea29154cd2d3637d`: each Linux/macOS job passed all 45 tests; each Windows job passed 44 executed tests and skipped one POSIX executable-permission test (45 total). Real Claude Code loading / MCP connectivity remain unverified. This targets Anthropic Claude Code.

## Quick start

Requires Python 3.11 or newer. Install from a local checkout:

```bash
python -m venv .venv
# macOS / Linux:
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\Activate.ps1

python -m pip install .
```

Preview your project without writing files:

```bash
codex-to-claude --project /path/to/project
```

Apply the supported changes:

```bash
codex-to-claude --project /path/to/project --apply
```

The tool prints a transaction ID for each operation that writes files. Keep it for restoration.

## What moves

| Codex source | Claude Code destination |
| --- | --- |
| Root and nested AGENTS.md / AGENTS.override.md | CLAUDE.md in the same directory |
| Supported MCP settings from user and project config.toml | Project .mcp.json; unrelated servers are retained |
| Project .agents/skills and legacy .codex/skills | .claude/skills, including scripts, references, and binary resources |
| Explicitly configured subagent instructions | .claude/agents; limited to compatible instruction-only roles |
| User instructions and user skills | Project scope, only with --include-user |
| User prompts/*.md | .claude/commands, only with --include-user |
| A selected Codex rollout JSONL | CODEX_HANDOFF.md reference transcript, only with --session |

Within each directory, a nonempty AGENTS.override.md takes precedence over AGENTS.md. Configured fallback filenames are also supported. Dependency, environment, tool-state, and build directories are excluded.

Skills must have valid YAML frontmatter, a Claude-compatible name, a description, and an instruction body. Resource paths stay together. Owner executable permissions are retained for scripts. Codex agents/openai.yaml UI metadata is omitted. Duplicate skill names stop the migration; disabled skills are skipped by name or absolute SKILL.md path.

Scripts and MCP servers are never executed by the migration tool.

## Conflicts and review items

Matching files are left as they are. Conflicting files or MCP servers block application. Preview replacements before using --overwrite:

```bash
codex-to-claude --project /path/to/project --overwrite
codex-to-claude --project /path/to/project --overwrite --apply
```

When a plan contains manual review items, --apply returns exit code 3 and writes nothing. Review the listed items, then use --accept-review to proceed:

```bash
codex-to-claude --project /path/to/project --accept-review --apply
```

User-level rules, skills, prompts, and agent roles are optional:

```bash
codex-to-claude --project /path/to/project --include-user
codex-to-claude --project /path/to/project --include-user --accept-review --apply
```

--include-user copies these assets into the selected project's scope. It does not write to ~/.claude.

## MCP and credentials

Supported fields include:

- stdio: command, args, env, env_vars.
- HTTP: url, env_http_headers, bearer_token_env_var.
- env_vars: variable names and name/source aliases.
- enabled = false: the server is skipped.

By default, literal env values become references to same-named shell variables. The report lists the variables to configure. Static HTTP headers and URLs containing credentials or query parameters are skipped. Use --include-secrets only when you intentionally want to copy literal values.

Existing target settings are preserved. This is not a comprehensive secret scanner: command arguments, rules, resources, transcripts, existing files, and backups may contain sensitive information. Inspect them before sharing.

A server with unsupported settings such as a working directory, tool restrictions, custom authentication, or timeout controls is skipped as a whole. The report explains which fields need manual conversion. Authenticate and approve MCP servers in Claude Code after migration.

JSON reports include filenames, actions, and review notes; they omit file contents and credential values.

## Restore

Preview a recorded restoration:

```bash
codex-to-claude --project /path/to/project --restore TRANSACTION_ID
```

Apply it:

```bash
codex-to-claude --project /path/to/project --restore TRANSACTION_ID --apply
```

Backups preserve original bytes and permissions and are checked with SHA-256. Restoration refuses files edited after migration. A restoration that changes files creates its own transaction, so it can also be undone.

Ordinary write failures roll back completed changes. Each file is replaced atomically using a temporary file in its own directory. The entire project is not a single atomic transaction, and power-loss durability is not guaranteed.

A forced termination may leave a prepared/recovery_required journal and an empty lock directory. Verify that the previous process has stopped before manually removing .codex-to-claude/lock, then preview restoration. Keep the backup directory.

The tool merges .gitignore entries for local migration state, handoff transcripts, and temporary files. File and plan size limits are 16 MiB per file and 128 MiB of combined planned content and originals. Symlinked selected sources or destinations, traversal paths, and case-insensitive destination collisions are refused. This does not isolate the tool from a malicious process modifying the filesystem concurrently.

## Conversation handoff

```bash
codex-to-claude --project /path/to/project --session /path/to/rollout.jsonl
codex-to-claude --project /path/to/project --session /path/to/rollout.jsonl --accept-review --apply
```

Only user and assistant input_text/output_text messages in supported rollout response_item events are exported. Tool calls, tool outputs, developer/system messages, hidden reasoning, images, and internal session state are omitted.

CODEX_HANDOFF.md is a reference transcript, not a native Claude Code session. Inspect it, then explicitly ask Claude Code to read it if you want to continue the work.

## Options and exit codes

| Option | Purpose |
| --- | --- |
| --project | Select the project directory |
| --codex-home | Select the Codex directory; defaults to CODEX_HOME or ~/.codex |
| --user-skills | Select user skills; defaults to ~/.agents/skills |
| --profile | Select a declared Codex profile; model and permission settings are not converted |
| --include-user | Copy user assets into project scope |
| --session | Export one supported rollout JSONL |
| --overwrite | Authorize conflicting replacements, with backups |
| --include-secrets | Allow literal MCP values |
| --accept-review | Apply after reviewing reported compatibility items |
| --apply | Write the changes; otherwise preview only |
| --restore | Preview or apply a recorded restoration |
| --json | Emit a machine-readable report |

Exit codes: 0 for a successful preview/application, 1 for invalid input or an operation failure, 2 for conflicts, and 3 for review items blocking application.

## Scope and limits

This is a project snapshot migration. It does not reproduce the full Codex runtime configuration chain: managed requirements, ancestor project layers, command-line overrides, plugin state, and organization configuration are excluded.

Model names, permissions, sandboxes, hooks, plugins, login credentials, memory databases, and subagent model/permission policies require manual setup. Agent roles with unsupported security settings are skipped. Instructions above the selected root and nested skill discovery require manual review. Claude's loading behavior and context limits can differ.

## Development and verification

```bash
python -m pip install .
python -m compileall -q codex_to_claude tests
python -m unittest discover -v
codex-to-claude --version
codex-to-claude --project examples/demo --codex-home examples/codex-home --json
```

The suite has 45 tests (43 original tests plus two path-validation regressions) covering planning, conflicts, repeat runs, configuration layering, MCP credential handling, skill assets, agent roles, transcript export, backup integrity, restoration, write-failure rollback, locks, and unsafe paths.

All 12 Linux/macOS/Windows × Python 3.11–3.14 jobs passed in [GitHub Actions run 37820171946](https://github.com/mxlyjy/codex-to-claude/actions/runs/37820171946) for source commit `33173a46325a51f3728971ceea29154cd2d3637d`: each Linux/macOS job passed all 45 tests; each Windows job passed 44 executed tests and skipped one POSIX executable-permission test (45 total). The verified workflow steps are installation, compilation, unittest, and version checks. First test migration and restoration on a copy; CI does not establish live Claude Code loading or MCP connectivity.

See REVIEW.md for the verification record and RELEASE_NOTES.md for the preview announcement.

## Format references

- [Codex configuration schema](https://github.com/openai/codex/blob/main/codex-rs/core/config.schema.json)
- [Codex project instructions](https://developers.openai.com/codex/guides/agents-md)
- [Codex skills](https://developers.openai.com/codex/skills)
- [Claude Code](https://github.com/anthropics/claude-code)
- [Claude memory](https://code.claude.com/docs/en/memory)
- [Claude skills](https://code.claude.com/docs/en/skills)
- [Claude MCP](https://code.claude.com/docs/en/mcp)

Preparation used the official Codex schema and both projects' GitHub documentation. Linked documentation websites and live installed versions were not directly tested.

## License

MIT. An independent community project, not affiliated with OpenAI or Anthropic.
