"""Command-line entry point."""
import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .core import MigrationError, Options, build_plan
from .transaction import apply, load_restore, restore


def parser():
    result = argparse.ArgumentParser(
        prog="codex-to-claude",
        description="Preview, migrate and restore Codex project assets for Claude Code.",
    )
    result.add_argument("--version", action="version", version=__version__)
    result.add_argument("--project", type=Path, default=Path.cwd())
    result.add_argument(
        "--codex-home", type=Path,
        default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))),
    )
    result.add_argument(
        "--user-skills", type=Path, default=Path.home() / ".agents/skills"
    )
    result.add_argument("--profile")
    result.add_argument("--include-user", action="store_true",
                        help="Copy user rules, skills and prompts into project scope")
    result.add_argument("--include-secrets", action="store_true",
                        help="Allow literal MCP credentials; review before committing")
    result.add_argument("--session", type=Path,
                        help="Export one Codex rollout JSONL as reference Markdown")
    result.add_argument("--overwrite", action="store_true",
                        help="Replace conflicting files/servers, with backups")
    result.add_argument("--apply", action="store_true",
                        help="Write changes; otherwise preview only")
    result.add_argument("--restore", metavar="TRANSACTION_ID",
                        help="Preview or apply a recorded restore")
    result.add_argument("--accept-review", action="store_true",
                        help="Apply a plan with documented manual-review items")
    result.add_argument("--json", action="store_true", dest="json_output")
    return result


def main(argv=None):
    arguments = parser().parse_args(argv)
    try:
        root = arguments.project.expanduser().resolve()
        if not root.is_dir():
            raise MigrationError("Project directory does not exist")
        if arguments.restore:
            if (
                arguments.overwrite or arguments.include_user
                or arguments.include_secrets or arguments.profile or arguments.session
            ):
                raise MigrationError("Restore cannot be combined with migration options")
            plan, _, _ = load_restore(root, arguments.restore)
        else:
            plan = build_plan(Options(
                project=root,
                codex_home=arguments.codex_home,
                user_skills=arguments.user_skills.expanduser(),
                profile=arguments.profile,
                include_user=arguments.include_user,
                include_secrets=arguments.include_secrets,
                overwrite=arguments.overwrite,
                session=arguments.session,
            ))
        report = plan.report()
        report["mode"] = "preview"
        status = 0
        if plan.conflicts:
            status = 2
        elif arguments.apply and plan.needs_review and not arguments.accept_review:
            report["notes"].append(
                "Review the listed items, then use --accept-review to apply"
            )
            status = 3
        elif arguments.apply:
            transaction = (
                restore(root, arguments.restore) if arguments.restore else apply(plan)
            )
            report["mode"] = "applied"
            report["transaction"] = transaction
        if arguments.json_output:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print("Codex -> Claude Code " + __version__)
            for change in report["changes"]:
                print(f'{change["action"]}: {change["path"]}')
            for conflict in report["conflicts"]:
                print("CONFLICT: " + conflict)
            for note in report["notes"]:
                print("NOTE: " + note)
            if not report["changes"] and not report["conflicts"]:
                print("No automatic changes planned")
            print("Applied" if report["mode"] == "applied" else "Preview only; no files written")
            if report.get("transaction"):
                print("Transaction: " + report["transaction"])
        return status
    except MigrationError as error:
        if arguments.json_output:
            print(json.dumps({"error": str(error), "mode": "failed"}))
        else:
            print(str(error), file=sys.stderr)
        return 1
    except (OSError, UnicodeError, RecursionError):
        # OSError details and parser input may contain credential-bearing paths.
        if arguments.json_output:
            print(json.dumps({
                "error": "Migration failed; inspect configuration, paths and recovery state",
                "mode": "failed",
            }))
        else:
            print(
                "Migration failed; inspect configuration, paths and recovery state",
                file=sys.stderr,
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
