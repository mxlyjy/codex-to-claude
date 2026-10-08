import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_to_claude.cli import main
from codex_to_claude.core import (
    MAX_FILE, MigrationError, Options, Plan, build_plan, safe_path,
    strict_json,
)
from codex_to_claude import transaction
from codex_to_claude.transaction import apply, load_restore, restore


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.project = self.base / "project"
        self.home = self.base / "codex"
        self.user_skills = self.base / "user-skills"
        self.project.mkdir()
        self.home.mkdir()
        self.user_skills.mkdir()
        self.options = Options(
            self.project, self.home, user_skills=self.user_skills
        )

    def write(self, relative, content, root=None):
        path = (root or self.project) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode() if isinstance(content, str) else content)
        return path

    def config(self, content):
        return self.write("config.toml", content, self.home)

    def skill(self, name="review", folder=None, root=None):
        folder = folder or ".agents/skills/" + name
        self.write(
            folder + "/SKILL.md",
            f"---\nname: {name}\ndescription: Review changes\n---\nCheck the diff.\n",
            root,
        )
        self.write(folder + "/references/example.txt", b"reference", root)
        return folder

    def invoke(self, *arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = main([
                "--project", str(self.project),
                "--codex-home", str(self.home),
                "--user-skills", str(self.user_skills),
                *arguments,
            ])
        return code, output.getvalue()

    def test_preview_does_not_write(self):
        self.write("AGENTS.md", "Use tests.\n")
        before = set(self.project.rglob("*"))
        plan = build_plan(self.options)
        self.assertIn("CLAUDE.md", plan.changes)
        self.assertEqual(set(self.project.rglob("*")), before)

    def test_override_and_nested_scope(self):
        self.write("AGENTS.md", "old root")
        self.write("AGENTS.override.md", "override")
        self.write("src/AGENTS.md", "nested")
        plan = build_plan(self.options)
        self.assertEqual(plan.changes["CLAUDE.md"].after, b"override")
        self.assertEqual(plan.changes["src/CLAUDE.md"].after, b"nested")

    def test_empty_override_falls_back(self):
        self.write("AGENTS.override.md", "\n")
        self.write("AGENTS.md", "fallback")
        self.assertEqual(
            build_plan(self.options).changes["CLAUDE.md"].after, b"fallback"
        )

    def test_fallback_instruction_filename(self):
        self.config('project_doc_fallback_filenames = ["RULES.md"]\n')
        self.write("RULES.md", "custom")
        self.assertEqual(
            build_plan(self.options).changes["CLAUDE.md"].after, b"custom"
        )

    def test_ignored_dependencies(self):
        self.write("node_modules/pkg/AGENTS.md", "ignored")
        self.assertFalse(build_plan(self.options).changes)

    def test_instruction_conflict_blocks_all_writes(self):
        self.write("AGENTS.md", "new")
        self.write("CLAUDE.md", "keep")
        plan = build_plan(self.options)
        self.assertIn("CLAUDE.md", plan.conflicts)
        with self.assertRaises(MigrationError):
            apply(plan)
        self.assertEqual((self.project / "CLAUDE.md").read_text(), "keep")

    def test_apply_and_repeat_are_idempotent(self):
        self.write("AGENTS.md", "\u89c4\u5219\n")
        transaction_id = apply(build_plan(self.options))
        self.assertEqual(len(transaction_id), 32)
        self.assertEqual((self.project / "CLAUDE.md").read_text(encoding="utf-8"), "\u89c4\u5219\n")
        self.assertFalse(build_plan(self.options).changes)

    def test_mcp_preserves_unrelated_servers_and_metadata(self):
        self.config('[mcp_servers.local]\ncommand = "node"\nargs = ["server.js"]\n')
        self.write(".mcp.json", json.dumps({
            "mcpServers": {"existing": {"command": "python"}},
            "extra": {"retained": True},
        }))
        plan = build_plan(self.options)
        result = json.loads(plan.changes[".mcp.json"].after)
        self.assertEqual(result["mcpServers"]["existing"], {"command": "python"})
        self.assertTrue(result["extra"]["retained"])
        self.assertEqual(result["mcpServers"]["local"]["command"], "node")

    def test_mcp_server_conflict(self):
        self.config('[mcp_servers.local]\ncommand = "node"\n')
        self.write(".mcp.json", '{"mcpServers":{"local":{"command":"keep"}}}')
        plan = build_plan(self.options)
        self.assertTrue(plan.conflicts)
        with self.assertRaises(MigrationError):
            apply(plan)

    def test_project_config_layer_overrides_user(self):
        self.config('[mcp_servers.local]\ncommand = "old"\n')
        self.write(".codex/config.toml", '[mcp_servers.local]\ncommand = "new"\n')
        result = json.loads(build_plan(self.options).changes[".mcp.json"].after)
        self.assertEqual(result["mcpServers"]["local"]["command"], "new")

    def test_disabled_server_is_skipped(self):
        self.config('[mcp_servers.local]\ncommand = "node"\nenabled = false\n')
        self.assertFalse(build_plan(self.options).changes)

    def test_restricted_server_is_not_weakened(self):
        self.config(
            '[mcp_servers.local]\ncommand = "node"\nenabled_tools = ["read"]\n'
        )
        plan = build_plan(self.options)
        self.assertTrue(plan.needs_review)
        self.assertNotIn(".mcp.json", plan.changes)

    def test_credential_literals_are_not_in_plan_or_report(self):
        self.config(
            '[mcp_servers.local]\ncommand = "node"\n'
            '[mcp_servers.local.env]\nDB_AUTH = "never-print-this-value"\n'
        )
        plan = build_plan(self.options)
        result = json.loads(plan.changes[".mcp.json"].after)
        self.assertEqual(
            result["mcpServers"]["local"]["env"]["DB_AUTH"], "$" + "{DB_AUTH}"
        )
        self.assertNotIn("never-print-this-value", json.dumps(plan.report()))
        self.assertNotIn(
            b"never-print-this-value", plan.changes[".mcp.json"].after
        )

    def test_explicit_literal_credential_option(self):
        self.config(
            '[mcp_servers.local]\ncommand = "node"\n'
            '[mcp_servers.local.env]\nAPI_KEY = "fixture"\n'
        )
        self.options.include_secrets = True
        data = build_plan(self.options).changes[".mcp.json"].after
        self.assertEqual(
            json.loads(data)["mcpServers"]["local"]["env"]["API_KEY"], "fixture"
        )

    def test_env_var_alias_and_bearer_header(self):
        self.config(
            '[mcp_servers.local]\ncommand = "node"\n'
            'env_vars = [{name = "TARGET", source = "SOURCE"}]\n'
            '[mcp_servers.remote]\nurl = "https://example.com/mcp"\n'
            'bearer_token_env_var = "MCP_TOKEN"\n'
        )
        result = json.loads(build_plan(self.options).changes[".mcp.json"].after)
        self.assertEqual(
            result["mcpServers"]["local"]["env"]["TARGET"], "$" + "{SOURCE}"
        )
        self.assertEqual(
            result["mcpServers"]["remote"]["headers"]["Authorization"],
            "Bearer $" + "{MCP_TOKEN}",
        )

    def test_url_credential_and_static_headers_are_skipped(self):
        self.config(
            '[mcp_servers.one]\nurl = "https://u:p@example.com/mcp"\n'
            '[mcp_servers.two]\nurl = "https://example.com/mcp"\n'
            'http_headers = {Authorization = "fixture"}\n'
        )
        plan = build_plan(self.options)
        self.assertTrue(plan.needs_review)
        self.assertNotIn(".mcp.json", plan.changes)

    def test_invalid_config_and_json_fail_without_writes(self):
        self.config('invalid = [\n')
        with self.assertRaises(MigrationError):
            build_plan(self.options)
        self.assertFalse((self.project / ".codex-to-claude").exists())
        for text in ['{"x":1,"x":2}', '{"x":NaN}', '[] trailing']:
            with self.assertRaises(MigrationError):
                strict_json(text)

    def test_skill_resources_and_binary_assets(self):
        folder = self.skill()
        self.write(folder + "/assets/image.bin", b"\x00\xff\x01")
        self.write(folder + "/agents/openai.yaml", "display_name: fixture")
        plan = build_plan(self.options)
        self.assertEqual(
            plan.changes[".claude/skills/review/assets/image.bin"].after,
            b"\x00\xff\x01",
        )
        self.assertNotIn(
            ".claude/skills/review/agents/openai.yaml", plan.changes
        )

    @unittest.skipIf(os.name == "nt", "POSIX executable permission test")
    def test_skill_executable_mode(self):
        folder = self.skill()
        script = self.write(folder + "/scripts/check.sh", "#!/bin/sh\nexit 0\n")
        script.chmod(0o755)
        apply(build_plan(self.options))
        target = self.project / ".claude/skills/review/scripts/check.sh"
        self.assertTrue(target.stat().st_mode & stat.S_IXUSR)

    def test_invalid_skill_frontmatter(self):
        self.write(".agents/skills/bad/SKILL.md", "No frontmatter")
        with self.assertRaises(MigrationError):
            build_plan(self.options)

    def test_duplicate_yaml_key_refused(self):
        self.write(
            ".agents/skills/bad/SKILL.md",
            "---\nname: bad\nname: other\ndescription: Test\n---\nBody",
        )
        with self.assertRaises(MigrationError):
            build_plan(self.options)

    def test_duplicate_skill_name_refused(self):
        self.skill("review", ".agents/skills/first")
        self.skill("review", ".codex/skills/second")
        with self.assertRaises(MigrationError):
            build_plan(self.options)

    def test_disabled_skill_selector(self):
        self.skill()
        self.config('[[skills.config]]\nname = "review"\nenabled = false\n')
        self.assertFalse(build_plan(self.options).changes)

    def test_user_scope_is_opt_in(self):
        self.write("AGENTS.md", "user", self.home)
        self.write("prompts/review.md", "Review $ARGUMENTS", self.home)
        self.skill("user-review", "user-review", self.user_skills)
        self.assertFalse(build_plan(self.options).changes)
        self.options.include_user = True
        plan = build_plan(self.options)
        self.assertIn("CLAUDE.md", plan.changes)
        self.assertIn(".claude/commands/review.md", plan.changes)
        self.assertIn(".claude/skills/user-review/SKILL.md", plan.changes)

    def test_project_agent_instruction_conversion(self):
        self.write(
            ".codex/config.toml",
            '[agents.reviewer]\ndescription = "Review code"\n'
            'config_file = "agents/reviewer.toml"\n',
        )
        self.write(
            ".codex/agents/reviewer.toml",
            'developer_instructions = "Check regression risks"\nmodel = "codex-model"\n',
        )
        plan = build_plan(self.options)
        self.assertIn(".claude/agents/reviewer.md", plan.changes)
        data = plan.changes[".claude/agents/reviewer.md"].after.decode()
        self.assertIn("Check regression risks", data)
        self.assertNotIn("codex-model", data)
        self.assertTrue(plan.needs_review)

    def test_agent_permissions_are_not_silently_dropped(self):
        self.write(
            ".codex/config.toml",
            '[agents.reviewer]\ndescription = "Review code"\n'
            'config_file = "agents/reviewer.toml"\n',
        )
        self.write(
            ".codex/agents/reviewer.toml",
            'developer_instructions = "Review"\nsandbox_mode = "read-only"\n',
        )
        plan = build_plan(self.options)
        self.assertNotIn(".claude/agents/reviewer.md", plan.changes)
        self.assertTrue(plan.needs_review)

    def test_user_agent_conversion_requires_include_user(self):
        self.config(
            '[agents.reviewer]\ndescription = "Review code"\n'
            'config_file = "agents/reviewer.toml"\n'
        )
        self.write(
            "agents/reviewer.toml",
            'developer_instructions = "Review"\n', self.home,
        )
        self.assertFalse(build_plan(self.options).changes)
        self.options.include_user = True
        self.assertIn(
            ".claude/agents/reviewer.md", build_plan(self.options).changes
        )

    def test_session_export_excludes_tools_and_developer_messages(self):
        session = self.write("session.jsonl", "\n".join(json.dumps(item) for item in [
            {"type": "response_item", "payload": {
                "type": "message", "role": "user",
                "content": [{"type": "input_text", "text": "Continue work"}],
            }},
            {"type": "response_item", "payload": {
                "type": "message", "role": "developer",
                "content": [{"type": "input_text", "text": "hidden-policy"}],
            }},
            {"type": "response_item", "payload": {
                "type": "function_call", "arguments": "tool-private-data",
            }},
        ]))
        self.options.session = session
        plan = build_plan(self.options)
        data = plan.changes["CODEX_HANDOFF.md"].after.decode()
        self.assertIn("Continue work", data)
        self.assertNotIn("hidden-policy", data)
        self.assertNotIn("tool-private-data", data)
        self.assertTrue(plan.needs_review)

    def test_restore_original_content_and_new_file_removal(self):
        self.write("AGENTS.md", "new")
        original = b"old\r\n"
        self.write("CLAUDE.md", original).chmod(0o640)
        self.options.overwrite = True
        transaction_id = apply(build_plan(self.options))
        restore(self.project, transaction_id)
        self.assertEqual((self.project / "CLAUDE.md").read_bytes(), original)
        self.assertFalse((self.project / ".gitignore").exists())
        if os.name != "nt":
            self.assertEqual(
                stat.S_IMODE((self.project / "CLAUDE.md").stat().st_mode), 0o640
            )

    def test_restore_refuses_post_migration_edits(self):
        self.write("AGENTS.md", "new")
        transaction_id = apply(build_plan(self.options))
        self.write("CLAUDE.md", "edited by user")
        with self.assertRaises(MigrationError):
            restore(self.project, transaction_id)
        self.assertEqual((self.project / "CLAUDE.md").read_text(), "edited by user")
        self.assertTrue((self.project / ".gitignore").exists())

    def test_restore_detects_backup_corruption(self):
        self.write("AGENTS.md", "new")
        self.write("CLAUDE.md", "old")
        self.options.overwrite = True
        transaction_id = apply(build_plan(self.options))
        backup = self.project / ".codex-to-claude" / transaction_id / "0.before"
        backup.write_bytes(b"tampered")
        with self.assertRaises(MigrationError):
            load_restore(self.project, transaction_id)

    def test_stale_plan_is_refused(self):
        self.write("AGENTS.md", "new")
        plan = build_plan(self.options)
        self.write("CLAUDE.md", "created while planning")
        with self.assertRaises(MigrationError):
            apply(plan)
        self.assertEqual(
            (self.project / "CLAUDE.md").read_text(), "created while planning"
        )

    def test_write_failure_rolls_back_completed_writes(self):
        self.write("AGENTS.md", "new")
        original_write = transaction.atomic_write

        def injected_failure(path, data, mode=0o600):
            if path.name == ".gitignore":
                raise OSError("injected failure")
            return original_write(path, data, mode)

        with mock.patch.object(transaction, "atomic_write", injected_failure):
            with self.assertRaises(MigrationError):
                apply(build_plan(self.options))
        self.assertFalse((self.project / "CLAUDE.md").exists())
        journals = list((self.project / ".codex-to-claude").glob("*/manifest.json"))
        self.assertEqual(len(journals), 1)
        self.assertEqual(json.loads(journals[0].read_text())["status"], "rolled_back")

    def test_lock_prevents_parallel_migration(self):
        self.write("AGENTS.md", "new")
        (self.project / ".codex-to-claude/lock").mkdir(parents=True)
        with self.assertRaises(MigrationError):
            apply(build_plan(self.options))

    def test_path_traversal_and_state_targets_refused(self):
        for path in ["../outside", "/absolute", "a\\b", "C:outside"]:
            with self.assertRaises(MigrationError):
                safe_path(self.project, path)
        with self.assertRaises(MigrationError):
            Plan(self.project).add(".git/config", b"forbidden")
        with self.assertRaises(MigrationError):
            load_restore(self.project, "../outside")

    def test_symbolic_source_and_destination_refused(self):
        outside = self.write("outside.txt", "outside", self.base)
        try:
            (self.project / "AGENTS.md").symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("Symbolic links unavailable")
        with self.assertRaises(MigrationError):
            build_plan(self.options)
        (self.project / "AGENTS.md").unlink()
        self.write("AGENTS.md", "new")
        (self.project / "CLAUDE.md").symlink_to(outside)
        with self.assertRaises(MigrationError):
            build_plan(self.options)

    def test_symbolic_skill_parent_refused(self):
        try:
            (self.project / ".agents").symlink_to(self.user_skills, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Symbolic links unavailable")
        with self.assertRaises(MigrationError):
            build_plan(self.options)

    def test_file_size_limit(self):
        path = self.project / "AGENTS.md"
        with path.open("wb") as stream:
            stream.truncate(MAX_FILE + 1)
        with self.assertRaises(MigrationError):
            build_plan(self.options)

    def test_cli_review_gate_and_json_report(self):
        self.config(
            '[mcp_servers.local]\ncommand = "node"\n'
            '[mcp_servers.local.env]\nAPI_KEY = "fixture-secret"\n'
        )
        code, output = self.invoke("--apply", "--json")
        self.assertEqual(code, 3)
        self.assertNotIn("fixture-secret", output)
        self.assertEqual(json.loads(output)["mode"], "preview")
        self.assertFalse((self.project / ".mcp.json").exists())
        code, output = self.invoke("--apply", "--accept-review", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["mode"], "applied")

    def test_cli_conflict_exit_status(self):
        self.write("AGENTS.md", "new")
        self.write("CLAUDE.md", "keep")
        code, _ = self.invoke("--apply")
        self.assertEqual(code, 2)

    def test_empty_restore_path_is_refused(self):
        self.write("AGENTS.md", "new")
        transaction_id = apply(build_plan(self.options))
        path = self.project / ".codex-to-claude" / transaction_id / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["files"][0]["path"] = ""
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(MigrationError):
            load_restore(self.project, transaction_id)

    def test_restore_cannot_remove_unrelated_directory(self):
        self.write("AGENTS.md", "new")
        transaction_id = apply(build_plan(self.options))
        path = self.project / ".codex-to-claude" / transaction_id / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["created_directories"] = ["unrelated"]
        path.write_text(json.dumps(manifest), encoding="utf-8")
        (self.project / "unrelated").mkdir()
        with self.assertRaises(MigrationError):
            restore(self.project, transaction_id)
        self.assertTrue((self.project / "unrelated").is_dir())

    def test_cli_restore_preview_is_read_only(self):
        self.write("AGENTS.md", "new")
        transaction_id = apply(build_plan(self.options))
        code, output = self.invoke("--restore", transaction_id, "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["mode"], "preview")
        self.assertTrue((self.project / "CLAUDE.md").exists())


if __name__ == "__main__":
    unittest.main()
