"""Build migration plans without writing files or executing migrated code."""
from __future__ import annotations

import json
import os
import re
import stat
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import yaml

MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
MAX_FILES = 10000
STATE = ".codex-to-claude"
EXCLUDE = {
    ".git", ".hg", ".svn", ".venv", "venv", "__pycache__",
    "node_modules", "vendor", "dist", "build", ".agents",
    ".codex", ".claude", STATE,
}
ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


class MigrationError(Exception):
    """A user-facing error that never includes configuration values."""


def safe_path(root: Path, relative: str) -> Path:
    path = Path(relative)
    if (
        # A rooted Windows path may have no drive and not be absolute.
        not relative or not path.parts or path.anchor
        or any(part in {"..", "."} for part in path.parts)
        or "\\" in relative or ":" in relative
    ):
        raise MigrationError("Unsafe relative path")
    candidate = root / path
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise MigrationError(f"Symbolic link refused: {relative}")
        if current.exists() and current != candidate and not current.is_dir():
            raise MigrationError(f"Parent is not a directory: {relative}")
    return candidate


def read_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise MigrationError(f"Not a regular source file: {path.name}")
    if path.stat().st_size > MAX_FILE:
        raise MigrationError(f"File exceeds 16 MiB: {path.name}")
    data = path.read_bytes()
    if len(data) > MAX_FILE:
        raise MigrationError(f"File exceeds 16 MiB: {path.name}")
    return data


def text_file(path: Path) -> str:
    try:
        return read_file(path).decode("utf-8-sig")
    except UnicodeError:
        raise MigrationError(f"File is not UTF-8: {path.name}") from None


def strict_json(text: str):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise MigrationError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(_):
        raise MigrationError("Non-finite JSON number")

    try:
        return json.loads(
            text, object_pairs_hook=unique, parse_constant=invalid_constant
        )
    except (ValueError, TypeError):
        raise MigrationError("Invalid JSON") from None


def load_toml(path: Path) -> dict:
    try:
        return tomllib.loads(text_file(path))
    except tomllib.TOMLDecodeError:
        raise MigrationError(f"Invalid TOML: {path.name}") from None


def merge_dict(left: dict, right: dict) -> dict:
    result = dict(left)
    for key, value in right.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = merge_dict(result[key], value)
        else:
            result[key] = value
    return result


@dataclass
class Change:
    relative: str
    before: bytes | None
    after: bytes | None
    before_mode: int | None
    after_mode: int | None


@dataclass
class Plan:
    root: Path
    changes: dict[str, Change] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    needs_review: bool = False
    _size: int = 0

    def add(self, relative, data, mode=0o600, overwrite=False):
        if data is not None and len(data) > MAX_FILE:
            raise MigrationError("Generated file exceeds 16 MiB")
        if len(self.changes) >= MAX_FILES:
            raise MigrationError("Too many migration files")
        for old in self.changes:
            if old.casefold() == relative.casefold() and old != relative:
                raise MigrationError("Case-insensitive destination collision")
        if relative in self.changes:
            if self.changes[relative].after != data:
                raise MigrationError(f"Multiple sources conflict: {relative}")
            return
        if Path(relative).parts and Path(relative).parts[0] in {".git", ".codex", ".agents", STATE}:
            raise MigrationError("Protected migration destination")
        target = safe_path(self.root, relative)
        if target.exists() and not target.is_file():
            raise MigrationError(f"Destination is not a file: {relative}")
        before = read_file(target) if target.exists() else None
        old_mode = stat.S_IMODE(target.stat().st_mode) if before is not None else None
        if old_mode is not None and old_mode > 0o777:
            raise MigrationError("Special destination permission bits need manual review")
        if before == data:
            return
        if before is not None and not overwrite:
            self.conflicts.append(relative)
            return
        self._size += len(data or b"") + len(before or b"")
        if self._size > MAX_TOTAL:
            raise MigrationError("Migration exceeds 128 MiB")
        self.changes[relative] = Change(
            relative, before, data, old_mode, mode if data is not None else None
        )

    def report(self):
        return {
            "version": 1,
            "changes": [
                {
                    "path": c.relative,
                    "action": "delete" if c.after is None else
                        ("create" if c.before is None else "update"),
                    "bytes": len(c.after or b""),
                }
                for c in self.changes.values()
            ],
            "conflicts": self.conflicts,
            "notes": self.notes,
            "needs_review": self.needs_review,
        }


@dataclass
class Options:
    project: Path
    codex_home: Path
    user_skills: Path | None = None
    profile: str | None = None
    include_user: bool = False
    include_secrets: bool = False
    overwrite: bool = False
    session: Path | None = None


def env_reference(name):
    if not isinstance(name, str) or not ENV_NAME.fullmatch(name):
        raise MigrationError("Invalid environment variable name")
    return "$" + "{" + name + "}"


def strings(value, label):
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise MigrationError(f"{label} must be a string list")
    return value


def mapping(value, label):
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        raise MigrationError(f"{label} must be a string mapping")
    return dict(value)


def has_expansion(value):
    return "$" + "{" in value


def mcp_server(name, server, options, plan):
    if not isinstance(server, dict):
        raise MigrationError("MCP server must be a table")
    if "enabled" in server and not isinstance(server["enabled"], bool):
        raise MigrationError("MCP enabled must be a boolean")
    if server.get("enabled") is False:
        plan.notes.append(f"MCP {name}: disabled; skipped")
        return None
    supported = {
        "command", "args", "env", "env_vars", "url", "enabled",
        "http_headers", "env_http_headers", "bearer_token_env_var",
    }
    unsupported = set(server) - supported
    if unsupported:
        # Do not silently weaken tool restrictions, auth or working directory.
        plan.notes.append(
            f"MCP {name}: skipped; unsupported fields: "
            + ", ".join(sorted(unsupported))
        )
        plan.needs_review = True
        return None
    has_command, has_url = "command" in server, "url" in server
    if has_command == has_url:
        raise MigrationError("MCP requires exactly one command or url")
    if has_command:
        if any(k in server for k in (
            "http_headers", "env_http_headers", "bearer_token_env_var"
        )):
            raise MigrationError("HTTP-only field on stdio MCP")
        command = server["command"]
        if not isinstance(command, str) or not command.strip():
            raise MigrationError("MCP command must be a nonempty string")
        args = strings(server.get("args", []), "MCP args")
        env = mapping(server.get("env", {}), "MCP env")
        for key, value in list(env.items()):
            env_reference(key)
            if not options.include_secrets:
                if value != env_reference(key):
                    env[key] = env_reference(key)
                    plan.notes.append(
                        f"MCP {name}: set shell variable {key}; literal omitted"
                    )
                    plan.needs_review = True
            elif has_expansion(value):
                plan.notes.append(
                    f"MCP {name}: review Claude variable expansion in env {key}"
                )
                plan.needs_review = True
        variables = server.get("env_vars", [])
        if not isinstance(variables, list):
            raise MigrationError("MCP env_vars must be a list")
        for item in variables:
            if isinstance(item, str):
                key, source = item, item
            elif isinstance(item, dict) and set(item) <= {"name", "source"}:
                key, source = item.get("name"), item.get("source", item.get("name"))
            else:
                raise MigrationError("Invalid MCP env_vars entry")
            env_reference(key)
            if key not in env:
                env[key] = env_reference(source)
        if any(has_expansion(arg) for arg in args) or has_expansion(command):
            plan.notes.append(f"MCP {name}: review expansion in command/args")
            plan.needs_review = True
        return {"type": "stdio", "command": command, "args": args, "env": env}
    if any(k in server for k in ("args", "env", "env_vars")):
        raise MigrationError("stdio-only field on HTTP MCP")
    url = server["url"]
    if not isinstance(url, str):
        raise MigrationError("MCP url must be a string")
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        credentials = bool(parsed.username or parsed.password or parsed.query)
    except ValueError:
        raise MigrationError("Invalid MCP URL") from None
    if not valid:
        raise MigrationError("MCP URL must use HTTP(S)")
    if credentials and not options.include_secrets:
        plan.notes.append(f"MCP {name}: URL has credentials/query; skipped")
        plan.needs_review = True
        return None
    if has_expansion(url):
        plan.notes.append(f"MCP {name}: review variable expansion in URL")
        plan.needs_review = True
    headers = mapping(server.get("http_headers", {}), "MCP HTTP headers")
    if headers and not options.include_secrets:
        plan.notes.append(f"MCP {name}: literal HTTP headers; skipped")
        plan.needs_review = True
        return None
    env_headers = mapping(server.get("env_http_headers", {}), "MCP env headers")
    for key, variable in env_headers.items():
        if any(old.casefold() == key.casefold() for old in headers):
            raise MigrationError("Conflicting MCP HTTP header")
        headers[key] = env_reference(variable)
    if "bearer_token_env_var" in server:
        if any(key.casefold() == "authorization" for key in headers):
            raise MigrationError("Conflicting MCP authorization")
        headers["Authorization"] = (
            "Bearer " + env_reference(server["bearer_token_env_var"])
        )
    return {"type": "http", "url": url, "headers": headers}


def migrate_mcp(config, options, plan):
    servers = config.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise MigrationError("mcp_servers must be a table")
    converted = {}
    for name, server in sorted(servers.items()):
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise MigrationError("MCP server name must use letters, digits, underscores or hyphens")
        value = mcp_server(name, server, options, plan)
        if value is not None:
            converted[name] = value
    if not converted:
        return
    target = safe_path(plan.root, ".mcp.json")
    original = strict_json(text_file(target)) if target.exists() else {}
    if not isinstance(original, dict):
        raise MigrationError(".mcp.json must be an object")
    document = dict(original)
    existing = document.get("mcpServers", {})
    if not isinstance(existing, dict):
        raise MigrationError("mcpServers must be an object")
    existing = dict(existing)
    document["mcpServers"] = existing
    for name, server in converted.items():
        if name in existing and existing[name] != server and not options.overwrite:
            plan.conflicts.append(f".mcp.json: server {name}")
        else:
            existing[name] = server
    if document == original:
        return
    data = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode()
    # Unrelated servers are retained. Conflict authorization happens per server.
    plan.add(".mcp.json", data, overwrite=True)


def selected_instruction(directory, names):
    for name in names:
        candidate = safe_path(directory, name)
        if candidate.exists():
            value = text_file(candidate)
            if value.strip():
                return value, name
    return "", None


def migrate_instructions(config, options, plan):
    fallback = strings(config.get("project_doc_fallback_filenames", []), "Fallback names")
    if any(Path(x).name != x or "\\" in x or ":" in x for x in fallback):
        raise MigrationError("Fallback instruction names must be plain filenames")
    names = list(dict.fromkeys(["AGENTS.override.md", "AGENTS.md"] + fallback))
    global_text = ""
    if options.include_user:
        global_text, _ = selected_instruction(
            options.codex_home, ["AGENTS.override.md", "AGENTS.md"]
        )
        if global_text:
            plan.notes.append("User instructions copied into this project's root scope")
    for directory, dirs, _ in os.walk(plan.root, followlinks=False):
        dirs[:] = sorted(
            d for d in dirs if d not in EXCLUDE
            and not (Path(directory) / d).is_symlink()
        )
        current = Path(directory)
        value, selected = selected_instruction(current, names)
        if current == plan.root and global_text:
            value = (
                "# Imported Codex user instructions\n\n" + global_text.rstrip()
                + "\n\n# Imported project instructions\n\n" + value
            )
        if value.strip():
            relative = (current / "CLAUDE.md").relative_to(plan.root).as_posix()
            plan.add(
                relative, value.encode("utf-8"),
                overwrite=options.overwrite
            )
            if selected == "AGENTS.override.md":
                plan.notes.append(f"{relative}: AGENTS.override.md takes precedence")
    if config.get("developer_instructions") or config.get("instructions"):
        plan.notes.append("Inline developer/system instructions need manual migration")
        plan.needs_review = True


class UniqueSafeLoader(yaml.SafeLoader):
    pass


def unique_yaml(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise MigrationError("Invalid or duplicate YAML frontmatter key")
        result[key] = loader.construct_object(value_node)
    return result


UniqueSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_yaml
)


def validate_skill(path):
    content = text_file(path)
    lines = content.splitlines()
    if not lines or lines[0] != "---":
        raise MigrationError("SKILL.md needs YAML frontmatter")
    try:
        end = lines.index("---", 1)
        frontmatter = yaml.load("\n".join(lines[1:end]), Loader=UniqueSafeLoader)
    except (ValueError, yaml.YAMLError):
        raise MigrationError("Invalid SKILL.md frontmatter") from None
    if not isinstance(frontmatter, dict):
        raise MigrationError("SKILL.md frontmatter must be an object")
    name, description = frontmatter.get("name"), frontmatter.get("description")
    if (
        not isinstance(name, str) or len(name) > 64
        or not SKILL_NAME.fullmatch(name)
        or not isinstance(description, str) or not description.strip()
    ):
        raise MigrationError("Skill needs a Claude-compatible name and description")
    if not "\n".join(lines[end + 1:]).strip():
        raise MigrationError("Skill instruction body is empty")
    return name, frontmatter


def migrate_skills(config, options, plan):
    roots = []
    if options.include_user:
        if options.user_skills is not None:
            roots.append(options.user_skills)
        roots.append(options.codex_home / "skills")
        plan.notes.append("User skills, if present, are copied into project scope")
    roots.extend([
        safe_path(plan.root, ".codex/skills"),
        safe_path(plan.root, ".agents/skills"),
    ])
    skills_config = config.get("skills", {})
    if not isinstance(skills_config, dict):
        raise MigrationError("skills must be a table")
    entries = skills_config.get("config", [])
    if not isinstance(entries, list):
        raise MigrationError("skills.config must be a list")
    disabled_names, disabled_paths = set(), set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("enabled"), bool):
            raise MigrationError("Invalid skills.config entry")
        if entry["enabled"] is False:
            if "name" in entry:
                if not isinstance(entry["name"], str):
                    raise MigrationError("Disabled skill name must be a string")
                disabled_names.add(entry["name"])
            if "path" in entry:
                if not isinstance(entry["path"], str):
                    raise MigrationError("Disabled skill path must be a string")
                disabled = Path(entry["path"]).expanduser()
                if not disabled.is_absolute():
                    raise MigrationError("Disabled skill path must be absolute")
                disabled_paths.add(disabled.resolve())
    seen = {}
    for root in roots:
        if root.is_symlink():
            raise MigrationError("Symbolic skill root refused")
        if not root.exists():
            continue
        if not root.is_dir():
            raise MigrationError("Skill root is not a directory")
        for folder in sorted(root.iterdir()):
            if folder.name.startswith("."):
                continue
            if folder.is_symlink():
                raise MigrationError("Symbolic skill directory refused")
            if not folder.is_dir():
                continue
            skill_path = folder / "SKILL.md"
            if not skill_path.exists():
                plan.notes.append(f"Skill {folder.name}: no SKILL.md; skipped")
                plan.needs_review = True
                continue
            if skill_path.resolve() in disabled_paths:
                plan.notes.append(f"Skill {folder.name}: disabled; skipped")
                continue
            name, metadata = validate_skill(skill_path)
            if name in disabled_names:
                plan.notes.append(f"Skill {name}: disabled; skipped")
                continue
            if name.casefold() in seen:
                raise MigrationError(f"Duplicate skill name across sources: {name}")
            seen[name.casefold()] = folder
            unsupported = set(metadata) - {"name", "description", "license", "compatibility"}
            if unsupported:
                plan.notes.append(
                    f"Skill {name}: review retained metadata "
                    + ", ".join(sorted(unsupported))
                )
                plan.needs_review = True
            for directory, dirs, file_names in os.walk(folder, followlinks=False):
                # Relative resources stay together; no script is executed.
                for d in dirs:
                    if (Path(directory) / d).is_symlink():
                        raise MigrationError(f"Skill {name}: symbolic resource refused")
                dirs[:] = sorted(d for d in dirs if d not in {".git", "__pycache__"})
                for filename in sorted(file_names):
                    source = Path(directory) / filename
                    relative = source.relative_to(folder).as_posix()
                    if relative == "agents/openai.yaml":
                        plan.notes.append(f"Skill {name}: Codex UI metadata omitted")
                        continue
                    data = read_file(source)
                    mode = 0o700 if source.stat().st_mode & 0o111 else 0o600
                    plan.add(
                        f".claude/skills/{name}/{relative}", data,
                        mode, overwrite=options.overwrite,
                    )
            if name != folder.name:
                plan.notes.append(f"Skill {folder.name}: destination uses declared name {name}")


def migrate_agents(config, options, plan):
    agents = config.get("agents", {})
    if not isinstance(agents, dict):
        raise MigrationError("agents must be a table")
    if agents.get("enabled") is False:
        plan.notes.append("Codex subagents are disabled; skipped")
        return
    for name, role in sorted(agents.items()):
        if not isinstance(role, dict):
            continue
        if not SKILL_NAME.fullmatch(name) or len(name) > 64:
            raise MigrationError("Agent name is not Claude-compatible")
        if set(role) - {"description", "config_file", "nickname_candidates"}:
            plan.notes.append(f"Agent {name}: unsupported role fields; skipped")
            plan.needs_review = True
            continue
        description = role.get("description")
        if not isinstance(description, str) or not description.strip():
            plan.notes.append(f"Agent {name}: no usable description; skipped")
            plan.needs_review = True
            continue
        config_file = role.get("config_file")
        if not isinstance(config_file, str):
            plan.notes.append(f"Agent {name}: no instruction config; skipped")
            plan.needs_review = True
            continue
        path = Path(config_file)
        allowed = False
        for base in (plan.root, options.codex_home):
            try:
                relative = path.relative_to(base).as_posix()
            except ValueError:
                continue
            path = safe_path(base, relative)
            allowed = True
            break
        if not allowed:
            plan.notes.append(f"Agent {name}: config outside selected roots; skipped")
            plan.needs_review = True
            continue
        role_config = load_toml(path)
        if set(role_config) - {
            "developer_instructions", "model", "model_reasoning_effort"
        }:
            plan.notes.append(
                f"Agent {name}: permissions or unsupported config; skipped"
            )
            plan.needs_review = True
            continue
        instructions = role_config.get("developer_instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            plan.notes.append(f"Agent {name}: no usable instructions; skipped")
            plan.needs_review = True
            continue
        body = (
            "---\nname: " + name + "\ndescription: "
            + json.dumps(description, ensure_ascii=False)
            + "\n---\n\n" + instructions.rstrip() + "\n"
        )
        plan.add(
            f".claude/agents/{name}.md", body.encode(),
            overwrite=options.overwrite,
        )
        plan.notes.append(
            f"Agent {name}: review instructions; Claude inherits its own model/tools"
        )
        plan.needs_review = True


def migrate_prompts(options, plan):
    if not options.include_user:
        return
    root = options.codex_home / "prompts"
    if root.is_symlink():
        raise MigrationError("Symbolic prompt root refused")
    if not root.exists():
        return
    if not root.is_dir():
        raise MigrationError("Prompt root must be a directory")
    for path in sorted(root.glob("*.md")):
        plan.add(
            f".claude/commands/{path.name}",
            text_file(path).encode(),
            overwrite=options.overwrite,
        )
        plan.notes.append(f"Prompt {path.name}: review arguments and tool names")
        plan.needs_review = True


def export_session(options, plan):
    if options.session is None:
        return
    source = options.session.expanduser()
    transcript = text_file(source)
    messages = []
    for number, line in enumerate(transcript.splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = strict_json(line)
        except MigrationError:
            raise MigrationError(f"Invalid session JSONL at line {number}") from None
        if not isinstance(event, dict):
            raise MigrationError(f"Session event must be an object at line {number}")
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        if event.get("type") == "response_item" and payload.get("type") == "message":
            role = payload.get("role")
            if role not in {"user", "assistant"}:
                continue
            content = payload.get("content", [])
            if not isinstance(content, list):
                continue
            text = "\n".join(
                part["text"] for part in content
                if isinstance(part, dict)
                and part.get("type") in {"input_text", "output_text"}
                and isinstance(part.get("text"), str)
            )
            if text:
                messages.append((role, text))
    if not messages:
        raise MigrationError("Session contains no supported user/assistant messages")
    result = (
        "# Imported Codex conversation\n\n"
        "Reference transcript only. This is not a native Claude session, "
        "and does not include tool calls, tool outputs or hidden reasoning.\n\n"
    )
    for role, text in messages:
        result += f"## {role}\n\n"
        result += "\n".join("> " + line for line in text.splitlines()) + "\n\n"
    plan.add("CODEX_HANDOFF.md", result.encode(), overwrite=options.overwrite)
    plan.notes.append("Session export can contain private text; inspect before sharing")
    plan.needs_review = True


def build_plan(options):
    root = options.project.expanduser().resolve()
    if not root.is_dir():
        raise MigrationError("Project directory does not exist")
    home = options.codex_home.expanduser().resolve()
    options.project, options.codex_home = root, home
    plan = Plan(root)
    config = {}
    config_paths = [home / "config.toml", root / ".codex/config.toml"]
    for path in config_paths:
        base = home if path == config_paths[0] else root
        candidate = safe_path(base, path.relative_to(base).as_posix())
        if candidate.exists():
            layer = load_toml(candidate)
            if path == config_paths[0] and not options.include_user:
                layer.pop("agents", None)
            layer_agents = layer.get("agents", {})
            if isinstance(layer_agents, dict):
                for role in layer_agents.values():
                    if isinstance(role, dict) and "config_file" in role:
                        reference = role["config_file"]
                        if not isinstance(reference, str):
                            raise MigrationError("Agent config_file must be a string")
                        reference = Path(reference).expanduser()
                        if not reference.is_absolute():
                            reference = candidate.parent / reference
                        # Keep lexical paths so safe_path can detect symlinks.
                        role["config_file"] = str(reference)
            config = merge_dict(config, layer)
    selected = options.profile or config.get("profile")
    if selected:
        profiles = config.get("profiles", {})
        if (
            not isinstance(selected, str) or not isinstance(profiles, dict)
            or selected not in profiles or not isinstance(profiles[selected], dict)
        ):
            raise MigrationError("Requested Codex profile does not exist")
        config = merge_dict(config, profiles[selected])
        plan.notes.append("Selected profile overlay applied")
    plan.notes.append(
        "Snapshot migration: excludes managed config, ancestor project layers, "
        "CLI overrides, plugins, hooks, permissions, models and auth.json"
    )
    migrate_instructions(config, options, plan)
    migrate_mcp(config, options, plan)
    migrate_skills(config, options, plan)
    migrate_agents(config, options, plan)
    migrate_prompts(options, plan)
    export_session(options, plan)
    if plan.changes:
        ignore_path = safe_path(root, ".gitignore")
        existing = text_file(ignore_path) if ignore_path.exists() else ""
        additions = []
        for entry in ["/.codex-to-claude/", "/CODEX_HANDOFF.md", "**/.c2c-*"]:
            if entry not in existing.splitlines():
                additions.append(entry)
        if additions:
            result = existing.rstrip("\n") + ("\n" if existing else "")
            result += "# Local Codex migration data\n" + "\n".join(additions) + "\n"
            plan.add(".gitignore", result.encode(), overwrite=True)
    return plan
