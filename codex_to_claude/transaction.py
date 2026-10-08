"""Journaled writes, rollback and explicit restore."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from .core import (
    MAX_FILES, STATE, MigrationError, Plan, read_file, safe_path, strict_json,
)


def digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def atomic_write(path, data, mode=0o600):
    fd, temporary = tempfile.mkstemp(prefix=".c2c-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_manifest(directory, manifest):
    atomic_write(
        directory / "manifest.json",
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(),
    )


def snapshot(root, relative):
    target = safe_path(root, relative)
    if not target.exists():
        return None, None
    data = read_file(target)
    return data, stat.S_IMODE(target.stat().st_mode)


def compatible_mode(actual, expected):
    # Windows chmod does not represent POSIX permission bits exactly.
    return os.name == "nt" or actual == expected


def check_before(plan):
    if plan.conflicts:
        raise MigrationError("Resolve all conflicts before applying")
    for change in plan.changes.values():
        current, mode = snapshot(plan.root, change.relative)
        if (
            current != change.before
            or not compatible_mode(mode, change.before_mode)
        ):
            raise MigrationError(f"Destination changed since preview: {change.relative}")


@contextmanager
def project_lock(root):
    state = safe_path(root, STATE)
    state.mkdir(mode=0o700, exist_ok=True)
    if not state.is_dir():
        raise MigrationError("Migration state is not a directory")
    lock = safe_path(root, STATE + "/lock")
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError:
        raise MigrationError(
            "Migration lock exists. If a previous process crashed, verify it "
            "has stopped before manually removing the empty lock directory."
        ) from None
    try:
        yield state
    finally:
        lock.rmdir()


def missing_directories(plan):
    result = set()
    for change in plan.changes.values():
        if change.after is None:
            continue
        current = safe_path(plan.root, change.relative).parent
        while current != plan.root and not current.exists():
            result.add(current.relative_to(plan.root).as_posix())
            current = current.parent
    return sorted(result, key=lambda x: (x.count("/"), x))


def clean_directories(root, directories):
    for relative in reversed(directories):
        path = safe_path(root, relative)
        if path.exists() and path.is_dir():
            try:
                path.rmdir()
            except OSError:
                # Never remove a directory containing unrelated files.
                pass


def apply_locked(plan, kind="migration"):
    check_before(plan)
    if not plan.changes:
        return None
    state = safe_path(plan.root, STATE)
    transaction_id = uuid.uuid4().hex
    directory = state / transaction_id
    directory.mkdir(mode=0o700)
    records = []
    for index, change in enumerate(plan.changes.values()):
        if change.before is not None:
            atomic_write(directory / f"{index}.before", change.before)
        records.append({
            "path": change.relative,
            "before": digest(change.before),
            "after": digest(change.after),
            "before_mode": change.before_mode,
            "after_mode": change.after_mode,
            "backup": f"{index}.before" if change.before is not None else None,
        })
    directories = missing_directories(plan)
    manifest = {
        "version": 1,
        "project": str(plan.root),
        "kind": kind,
        "status": "prepared",
        "files": records,
        "created_directories": directories,
    }
    save_manifest(directory, manifest)
    completed = []
    try:
        for change in plan.changes.values():
            completed.append(change)
            path = safe_path(plan.root, change.relative)
            if change.after is None:
                path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path = safe_path(plan.root, change.relative)
                atomic_write(path, change.after, change.after_mode)
        manifest["status"] = "applied"
        save_manifest(directory, manifest)
    except BaseException:
        errors = []
        for change in reversed(completed):
            try:
                current, mode = snapshot(plan.root, change.relative)
                if current == change.before and compatible_mode(mode, change.before_mode):
                    continue
                if current != change.after or not compatible_mode(mode, change.after_mode):
                    errors.append(change.relative)
                    continue
                path = safe_path(plan.root, change.relative)
                if change.before is None:
                    path.unlink()
                else:
                    atomic_write(path, change.before, change.before_mode)
            except (OSError, MigrationError):
                errors.append(change.relative)
        try:
            clean_directories(plan.root, directories)
        except (OSError, MigrationError):
            errors.append("directories")
        manifest["status"] = "recovery_required" if errors else "rolled_back"
        try:
            save_manifest(directory, manifest)
        except OSError:
            errors.append("journal")
        raise MigrationError(
            "Write failed. "
            + ("Recovery needs review. " if errors else "Completed writes rolled back. ")
            + f"Transaction: {transaction_id}"
        ) from None
    return transaction_id


def apply(plan):
    if not plan.changes:
        check_before(plan)
        return None
    with project_lock(plan.root):
        return apply_locked(plan)


def load_restore(root, transaction_id):
    if (
        len(transaction_id) != 32
        or any(c not in "0123456789abcdef" for c in transaction_id)
    ):
        raise MigrationError("Invalid transaction ID")
    directory = safe_path(root, STATE + "/" + transaction_id)
    manifest_path = safe_path(directory, "manifest.json")
    manifest = strict_json(read_file(manifest_path).decode("utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("version") != 1
        or manifest.get("project") != str(root)
        or manifest.get("status") not in {"applied", "prepared", "recovery_required"}
    ):
        raise MigrationError("Transaction cannot be restored")
    records = manifest.get("files")
    if not isinstance(records, list) or len(records) > MAX_FILES:
        raise MigrationError("Invalid transaction file list")
    plan = Plan(root)
    seen = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict) or not {
            "path", "before", "after", "before_mode", "after_mode", "backup"
        } <= set(record):
            raise MigrationError("Invalid transaction record")
        relative = record.get("path")
        if not isinstance(relative, str):
            raise MigrationError("Invalid transaction path")
        if relative.casefold() in seen:
            raise MigrationError("Duplicate transaction path")
        seen.add(relative.casefold())
        safe_path(root, relative)
        if Path(relative).parts[0] in {".git", ".codex", ".agents", STATE}:
            raise MigrationError("Protected transaction destination")
        safe_path(root, relative)
        before_hash, after_hash = record.get("before"), record.get("after")
        for value in (before_hash, after_hash):
            if value is not None and (
                not isinstance(value, str) or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)
            ):
                raise MigrationError("Invalid transaction digest")
        for key, value in (
            ("before_mode", before_hash), ("after_mode", after_hash)
        ):
            mode = record.get(key)
            if value is None:
                if mode is not None:
                    raise MigrationError("Unexpected transaction file mode")
            elif type(mode) is not int or not 0 <= mode <= 0o777:
                raise MigrationError("Invalid transaction file mode")
        if before_hash is None:
            if record.get("backup") is not None:
                raise MigrationError("Unexpected transaction backup")
            original = None
        else:
            if record.get("backup") != f"{index}.before":
                raise MigrationError("Invalid backup filename")
            original = read_file(safe_path(directory, f"{index}.before"))
            if digest(original) != before_hash:
                raise MigrationError("Backup integrity check failed")
        current, mode = snapshot(root, relative)
        if digest(current) == before_hash:
            if not compatible_mode(mode, record["before_mode"]):
                plan.conflicts.append(relative + ": permissions changed")
            continue
        if (
            digest(current) != after_hash
            or not compatible_mode(mode, record["after_mode"])
        ):
            plan.conflicts.append(relative + ": edited after migration")
            continue
        plan.add(
            relative, original,
            mode=record["before_mode"], overwrite=True,
        )
    directories = manifest.get("created_directories")
    if not isinstance(directories, list) or not all(
        isinstance(item, str) for item in directories
    ):
        raise MigrationError("Invalid transaction directory list")
    allowed_directories = set()
    for record in records:
        parent = Path(record["path"]).parent
        while parent.parts:
            allowed_directories.add(parent.as_posix())
            parent = parent.parent
    if len(directories) != len(set(directories)):
        raise MigrationError("Duplicate transaction directory")
    for relative in directories:
        if relative not in allowed_directories:
            raise MigrationError("Directory is not a recorded destination parent")
        if relative.split("/")[0] in {".git", STATE, ".codex", ".agents"}:
            raise MigrationError("Protected transaction directory")
        safe_path(root, relative)
    plan.notes.append("Restore refuses files edited since migration")
    return plan, directory, manifest


def restore(root, transaction_id):
    with project_lock(root):
        plan, directory, manifest = load_restore(root, transaction_id)
        new_id = apply_locked(plan, kind="restore")
        manifest["status"] = "restored"
        save_manifest(directory, manifest)
        clean_directories(root, manifest["created_directories"])
        return new_id
