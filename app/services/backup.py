"""Data backup service for database and file backups."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from flask import current_app

from app.extensions import db
from app.models import (
    BackupLog,
    BackupStatus,
    BackupType,
    Hospital,
    User,
)
from app.services.audit import log_action


def _generate_backup_id() -> str:
    """Generate a unique backup identifier."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"backup_{timestamp}"


def _calculate_checksum(file_path: str) -> str:
    """Calculate SHA-256 checksum of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def _get_database_tables() -> list[str]:
    """Get list of all tables in the database."""
    engine = db.engine
    if engine.dialect.name == "sqlite":
        with sqlite3.connect(str(engine.url).replace("sqlite:///", "")) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            return [row[0] for row in cursor.fetchall()]
    else:
        # For PostgreSQL/other databases
        from sqlalchemy import inspect
        inspector = inspect(engine)
        return inspector.get_table_names()


def _backup_sqlite_database(output_path: str, tables: Optional[list[str]] = None) -> dict:
    """Backup SQLite database to a file."""
    db_url = str(db.engine.url)
    db_path = db_url.replace("sqlite:///", "").replace("sqlite://", "")

    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file not found: {db_path}")

    # For SQLite, we can simply copy the file for a consistent backup
    shutil.copy2(db_path, output_path)

    return {
        "file_path": output_path,
        "file_size": os.path.getsize(output_path),
        "tables": tables or _get_database_tables(),
    }


def _backup_postgres_database(output_path: str, tables: Optional[list[str]] = None) -> dict:
    """Backup PostgreSQL database using pg_dump."""
    db_url = str(db.engine.url)

    # Parse connection details from URL
    # Format: postgresql://user:password@host:port/dbname
    from urllib.parse import urlparse
    parsed = urlparse(db_url)

    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    username = parsed.username or "postgres"
    database = parsed.path.lstrip("/")

    # Build pg_dump command
    cmd = [
        "pg_dump",
        "-h", host,
        "-p", str(port),
        "-U", username,
        "-d", database,
        "-f", output_path,
        "--format=custom",  # Custom format for easy restore
    ]

    if tables:
        for table in tables:
            cmd.extend(["-t", table])

    # Set password via environment variable
    env = os.environ.copy()
    if parsed.password:
        env["PGPASSWORD"] = parsed.password

    result = subprocess.run(cmd, env=env, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {result.stderr}")

    return {
        "file_path": output_path,
        "file_size": os.path.getsize(output_path),
        "tables": tables or _get_database_tables(),
    }


def _backup_database(output_path: str, tables: Optional[list[str]] = None) -> dict:
    """Backup database based on dialect."""
    dialect = db.engine.dialect.name

    if dialect == "sqlite":
        return _backup_sqlite_database(output_path, tables)
    elif dialect == "postgresql":
        return _backup_postgres_database(output_path, tables)
    else:
        raise ValueError(f"Unsupported database dialect: {dialect}")


def _backup_files(output_path: str, hospital_id: Optional[int] = None) -> dict:
    """Backup uploaded files (lab reports, prescriptions, etc.)."""
    upload_dir = current_app.config.get("UPLOAD_DIR", "uploads")

    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir, exist_ok=True)
        return {
            "file_path": output_path,
            "file_size": 0,
            "files_count": 0,
        }

    # Create a compressed archive of the upload directory
    shutil.make_archive(output_path.replace(".zip", ""), "zip", upload_dir)

    return {
        "file_path": output_path,
        "file_size": os.path.getsize(output_path),
        "files_count": sum(1 for _ in Path(upload_dir).rglob("*") if _.is_file()),
    }


def create_backup(
    backup_type: BackupType = BackupType.FULL,
    hospital_id: Optional[int] = None,
    tables: Optional[list[str]] = None,
    notes: Optional[str] = None,
    created_by: Optional[User] = None,
) -> BackupLog:
    """Create a new backup."""
    backup_id = _generate_backup_id()
    backup_dir = current_app.config.get("BACKUP_DIR", "backups")

    # Ensure backup directory exists
    os.makedirs(backup_dir, exist_ok=True)

    # Create backup log entry
    backup = BackupLog(
        backup_id=backup_id,
        backup_type=backup_type,
        status=BackupStatus.IN_PROGRESS,
        database_name=db.engine.url.database,
        tables_included=tables,
        hospital_id=hospital_id,
        started_at=datetime.now(timezone.utc),
        created_by_user_id=created_by.id if created_by else None,
        notes=notes,
    )
    db.session.add(backup)
    db.session.flush()

    try:
        # Perform backup based on type
        if backup_type in [BackupType.FULL, BackupType.DATABASE_ONLY]:
            db_output = os.path.join(backup_dir, f"{backup_id}_database.db")
            db_result = _backup_database(db_output, tables)
            backup.file_name = os.path.basename(db_output)
            backup.file_path = db_output
            backup.file_size_bytes = db_result["file_size"]
            backup.checksum = _calculate_checksum(db_output)

        if backup_type in [BackupType.FULL, BackupType.FILES_ONLY]:
            files_output = os.path.join(backup_dir, f"{backup_id}_files.zip")
            files_result = _backup_files(files_output, hospital_id)
            if backup_type == BackupType.FULL:
                backup.file_size_bytes = (backup.file_size_bytes or 0) + files_result["file_size"]

        # Mark as completed
        backup.status = BackupStatus.COMPLETED
        backup.completed_at = datetime.now(timezone.utc)
        backup.duration_seconds = int(
            (backup.completed_at - backup.started_at).total_seconds()
        )

        db.session.flush()

        # Audit log
        log_action(
            user=created_by,
            action="backup_created",
            entity="backup_log",
            entity_id=backup.id,
            after=backup.to_dict(),
        )

        return backup

    except Exception as e:
        backup.status = BackupStatus.FAILED
        backup.error_message = str(e)
        backup.completed_at = datetime.now(timezone.utc)
        backup.duration_seconds = int(
            (backup.completed_at - backup.started_at).total_seconds()
        )
        db.session.flush()

        # Audit log
        log_action(
            user=created_by,
            action="backup_failed",
            entity="backup_log",
            entity_id=backup.id,
            after=backup.to_dict(),
        )

        raise


def restore_backup(
    backup_id: str,
    restore_by: Optional[User] = None,
) -> BackupLog:
    """Restore from a backup."""
    backup = BackupLog.query.filter_by(backup_id=backup_id).first()
    if not backup:
        raise ValueError(f"Backup not found: {backup_id}")

    if backup.status != BackupStatus.COMPLETED:
        raise ValueError(f"Cannot restore backup with status: {backup.status.value}")

    try:
        # For SQLite, we need to stop the current database connection
        # and replace the file
        if db.engine.dialect.name == "sqlite":
            db_url = str(db.engine.url)
            current_db_path = db_url.replace("sqlite:///", "").replace("sqlite://", "")

            # Create a backup of current database
            current_backup_path = f"{current_db_path}.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            if os.path.exists(current_db_path):
                shutil.copy2(current_db_path, current_backup_path)

            # Restore from backup
            if backup.file_path and os.path.exists(backup.file_path):
                shutil.copy2(backup.file_path, current_db_path)

        # Mark backup as restored
        backup.status = BackupStatus.RESTORED
        backup.restored_at = datetime.now(timezone.utc)
        backup.restored_by_user_id = restore_by.id if restore_by else None
        db.session.flush()

        # Audit log
        log_action(
            user=restore_by,
            action="backup_restored",
            entity="backup_log",
            entity_id=backup.id,
            before={"status": "completed"},
            after=backup.to_dict(),
        )

        return backup

    except Exception as e:
        backup.error_message = f"Restore failed: {str(e)}"
        db.session.flush()
        raise


def list_backups(
    hospital_id: Optional[int] = None,
    backup_type: Optional[BackupType] = None,
    status: Optional[BackupStatus] = None,
    limit: int = 50,
) -> list[BackupLog]:
    """List backups with optional filters."""
    query = BackupLog.query

    if hospital_id:
        query = query.filter_by(hospital_id=hospital_id)
    if backup_type:
        query = query.filter_by(backup_type=backup_type)
    if status:
        query = query.filter_by(status=status)

    return query.order_by(BackupLog.created_at.desc()).limit(limit).all()


def get_backup_stats() -> dict:
    """Get backup statistics."""
    total = BackupLog.query.count()
    completed = BackupLog.query.filter_by(status=BackupStatus.COMPLETED).count()
    failed = BackupLog.query.filter_by(status=BackupStatus.FAILED).count()
    restored = BackupLog.query.filter_by(status=BackupStatus.RESTORED).count()

    # Get latest backup
    latest = BackupLog.query.filter_by(status=BackupStatus.COMPLETED).order_by(
        BackupLog.completed_at.desc()
    ).first()

    # Calculate total backup size
    from sqlalchemy import func
    total_size = db.session.query(func.sum(BackupLog.file_size_bytes)).filter(
        BackupLog.status.in_([BackupStatus.COMPLETED, BackupStatus.RESTORED])
    ).scalar() or 0

    return {
        "total_backups": total,
        "completed": completed,
        "failed": failed,
        "restored": restored,
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "latest_backup": latest.to_dict() if latest else None,
    }


def delete_old_backups(days_to_keep: int = 30) -> int:
    """Delete backups older than specified days."""
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)

    old_backups = BackupLog.query.filter(
        BackupLog.created_at < cutoff_date,
        BackupLog.status.in_([BackupStatus.COMPLETED, BackupStatus.FAILED]),
    ).all()

    deleted_count = 0
    for backup in old_backups:
        # Delete the backup file
        if backup.file_path and os.path.exists(backup.file_path):
            try:
                os.remove(backup.file_path)
            except OSError:
                pass

        # Delete the database record
        db.session.delete(backup)
        deleted_count += 1

    db.session.flush()
    return deleted_count
