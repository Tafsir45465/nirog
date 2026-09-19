"""Data backup management routes."""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app.errors import AppError
from app.extensions import db
from app.models import BackupLog, BackupStatus, BackupType, Role
from app.security import current_user, require_hospital_access, roles_required
from app.services.backup import (
    create_backup,
    delete_old_backups,
    get_backup_stats,
    list_backups,
    restore_backup,
)
from app.utils.responses import ok, error

bp = Blueprint("backup", __name__, url_prefix="/api/backups")


@bp.get("/stats")
@jwt_required()
@roles_required(Role.ADMIN, Role.SUPER_ADMIN)
def get_stats():
    """Get backup statistics."""
    stats = get_backup_stats()
    return ok(data=stats)


@bp.get("/")
@jwt_required()
@roles_required(Role.ADMIN, Role.SUPER_ADMIN)
def list_all_backups():
    """List all backups with optional filters."""
    backup_type = request.args.get("backup_type")
    status = request.args.get("status")
    hospital_id = request.args.get("hospital_id", type=int)
    limit = request.args.get("limit", default=50, type=int)

    bt = BackupType(backup_type) if backup_type else None
    bs = BackupStatus(status) if status else None

    backups = list_backups(
        hospital_id=hospital_id,
        backup_type=bt,
        status=bs,
        limit=limit,
    )

    return ok(
        data=[b.to_dict() for b in backups],
        meta={"total": len(backups)},
    )


@bp.get("/<int:backup_id>")
@jwt_required()
@roles_required(Role.ADMIN, Role.SUPER_ADMIN)
def get_backup(backup_id: int):
    """Get a specific backup by ID."""
    backup = db.session.get(BackupLog, backup_id)
    if not backup:
        raise AppError("Backup not found", 404, "not_found")

    return ok(data=backup.to_dict())


@bp.post("/create")
@jwt_required()
@roles_required(Role.ADMIN, Role.SUPER_ADMIN)
def create_new_backup():
    """Create a new backup."""
    user = current_user()
    data = request.get_json(silent=True) or {}

    backup_type = data.get("backup_type", "full")
    hospital_id = data.get("hospital_id")
    tables = data.get("tables")
    notes = data.get("notes")

    try:
        bt = BackupType(backup_type)
    except ValueError:
        raise AppError(
            f"Invalid backup type. Valid types: {[t.value for t in BackupType]}",
            400,
            "invalid_backup_type",
        )

    # If hospital_id provided, verify access
    if hospital_id:
        require_hospital_access(user, hospital_id)

    try:
        backup = create_backup(
            backup_type=bt,
            hospital_id=hospital_id,
            tables=tables,
            notes=notes,
            created_by=user,
        )
        db.session.commit()
        return ok(data=backup.to_dict(), message="Backup created successfully"), 201
    except Exception as e:
        db.session.rollback()
        raise AppError(f"Backup failed: {str(e)}", 500, "backup_failed")


@bp.post("/restore/<int:backup_id>")
@jwt_required()
@roles_required(Role.SUPER_ADMIN)  # Only super admin can restore
def restore_existing_backup(backup_id: int):
    """Restore from a backup (requires super admin privileges)."""
    user = current_user()

    try:
        backup = restore_backup(
            backup_id=str(backup_id),
            restore_by=user,
        )
        db.session.commit()
        return ok(data=backup.to_dict(), message="Backup restored successfully")
    except ValueError as e:
        raise AppError(str(e), 400, "restore_failed")
    except Exception as e:
        db.session.rollback()
        raise AppError(f"Restore failed: {str(e)}", 500, "restore_failed")


@bp.delete("/<int:backup_id>")
@jwt_required()
@roles_required(Role.SUPER_ADMIN)  # Only super admin can delete
def delete_backup(backup_id: int):
    """Delete a backup."""
    backup = db.session.get(BackupLog, backup_id)
    if not backup:
        raise AppError("Backup not found", 404, "not_found")

    # Delete the backup file if it exists
    import os
    if backup.file_path and os.path.exists(backup.file_path):
        try:
            os.remove(backup.file_path)
        except OSError:
            pass

    # Delete the database record
    db.session.delete(backup)
    db.session.commit()

    return ok(message="Backup deleted successfully")


@bp.post("/cleanup")
@jwt_required()
@roles_required(Role.SUPER_ADMIN)
def cleanup_old_backups():
    """Delete backups older than specified days."""
    data = request.get_json(silent=True) or {}
    days_to_keep = data.get("days_to_keep", 30)

    deleted_count = delete_old_backups(days_to_keep)
    db.session.commit()

    return ok(
        data={"deleted_count": deleted_count},
        message=f"Deleted {deleted_count} backups older than {days_to_keep} days",
    )


@bp.get("/health")
def backup_health_check():
    """Health check for backup system."""
    from app.services.backup import _get_database_tables
    try:
        tables = _get_database_tables()
        return ok(
            data={
                "status": "healthy",
                "database_type": db.engine.dialect.name,
                "tables_count": len(tables),
            }
        )
    except Exception as e:
        return error(message=f"Backup system unhealthy: {str(e)}", code="unhealthy"), 500
