"""Scriptable backup and restore for marcedit-web operational data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from marcedit_web.lib import db


@dataclass(frozen=True)
class BackupResult:
    backup_dir: Path
    db_backup_path: Path
    audit_backup_dir: Path
    verification: dict


@dataclass(frozen=True)
class RestoreResult:
    db_path: Path
    audit_dir: Path


def create_backup(target_dir: Path) -> BackupResult:
    """Create a backup directory containing SQLite DB + audit JSONL files."""
    db.init_schema()
    target_dir.mkdir(parents=True, exist_ok=True)
    db_backup_path = target_dir / "marcedit.db"
    audit_backup_dir = target_dir / "audit"

    source_verification = _sqlite_metadata(db.db_path())
    _backup_sqlite(db.db_path(), db_backup_path)
    verification = verify_sqlite_backup(
        db_backup_path,
        expected=source_verification,
    )
    verification["source_sha256"] = _sha256(db.db_path())
    verification["backup_sha256"] = _sha256(db_backup_path)
    _copy_tree(_audit_dir(), audit_backup_dir)
    _write_manifest(
        target_dir,
        db_backup_path,
        audit_backup_dir,
        verification=verification,
    )
    return BackupResult(
        backup_dir=target_dir,
        db_backup_path=db_backup_path,
        audit_backup_dir=audit_backup_dir,
        verification=verification,
    )


def restore_backup(source_dir: Path) -> RestoreResult:
    """Restore a backup created by :func:`create_backup`."""
    source_db = source_dir / "marcedit.db"
    source_audit = source_dir / "audit"
    if not source_db.exists():
        raise FileNotFoundError(f"backup DB not found: {source_db}")

    target_db = db.db_path()
    target_db.parent.mkdir(parents=True, exist_ok=True)
    _remove_sqlite_sidecars(target_db)
    shutil.copy2(source_db, target_db)

    target_audit = _audit_dir()
    if target_audit.exists():
        shutil.rmtree(target_audit)
    if source_audit.exists():
        shutil.copytree(source_audit, target_audit)
    else:
        target_audit.mkdir(parents=True, exist_ok=True)

    db.reset_for_tests()
    db.init_schema()
    return RestoreResult(db_path=target_db, audit_dir=target_audit)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create or restore marcedit-web data backups.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="create backup")
    create.add_argument("target_dir")
    restore = sub.add_parser("restore", help="restore backup")
    restore.add_argument("source_dir")
    args = parser.parse_args(argv)

    try:
        if args.command == "create":
            result = create_backup(Path(args.target_dir))
            print(
                "backup created: "
                f"dir={result.backup_dir} db={result.db_backup_path} "
                f"audit={result.audit_backup_dir}"
            )
            return 0
        if args.command == "restore":
            result = restore_backup(Path(args.source_dir))
            print(
                "backup restored: "
                f"db={result.db_path} audit={result.audit_dir}"
            )
            return 0
    except Exception as exc:  # noqa: BLE001 - operator CLI must fail loud
        print(f"backup {args.command} failed: {exc}", file=sys.stderr)
        return 1
    return 1


def _backup_sqlite(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)


def verify_sqlite_backup(
    path: Path,
    *,
    expected: dict | None = None,
) -> dict:
    """Verify a backup independently and optionally against live metadata."""
    actual = _sqlite_metadata(path)
    if actual["integrity_check"] != "ok":
        raise ValueError("SQLite integrity_check did not return ok")
    if expected is not None:
        for key in ("schema", "user_version", "row_counts"):
            if actual[key] != expected.get(key):
                raise ValueError(
                    "SQLite backup schema or row-count verification failed"
                )
    return actual


def _sqlite_metadata(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {path}")
    with sqlite3.connect(path) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        schema = [
            tuple(row)
            for row in conn.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
            )
        ]
        table_names = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        row_counts = {
            name: int(
                conn.execute(
                    f"SELECT COUNT(*) FROM {_quote_identifier(name)}"
                ).fetchone()[0]
            )
            for name in table_names
        }
        user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    return {
        "integrity_check": str(integrity),
        "schema": schema,
        "user_version": user_version,
        "row_counts": row_counts,
        "size": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _quote_identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_tree(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    if source.exists():
        shutil.copytree(source, target)
    else:
        target.mkdir(parents=True, exist_ok=True)


def _write_manifest(
    target_dir: Path,
    db_backup_path: Path,
    audit_backup_dir: Path,
    *,
    verification: dict,
) -> None:
    manifest = {
        "format": 1,
        "db": db_backup_path.name,
        "audit_dir": audit_backup_dir.name,
        "note": "SQLite backup uses sqlite3.Connection.backup; WAL/SHM are folded into marcedit.db.",
        "verification": verification,
    }
    (target_dir / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _remove_sqlite_sidecars(db_file: Path) -> None:
    for path in (db_file, Path(str(db_file) + "-wal"), Path(str(db_file) + "-shm")):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _audit_dir() -> Path:
    return Path(os.environ.get("MARCEDIT_WEB_AUDIT_DIR", "data/audit"))


if __name__ == "__main__":
    raise SystemExit(main())
