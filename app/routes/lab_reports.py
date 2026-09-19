from __future__ import annotations

import os
import uuid
from flask import Blueprint, current_app, request, send_file
from flask_jwt_extended import jwt_required
from werkzeug.utils import secure_filename

from app.errors import AppError
from app.extensions import db
from app.models import LabReport, Patient, TestOrder, User
from app.security import can_access_patient, current_user
from app.services.audit import log_action
from app.utils.responses import ok

bp = Blueprint("lab_reports", __name__, url_prefix="/api")

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
}


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def detected_mime_type(file) -> str:
    """Detect the file type from its signature instead of trusting the browser header."""
    header = file.stream.read(16)
    file.stream.seek(0)
    if header.startswith(b"%PDF"):
        return "application/pdf"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return ""


def get_upload_folder() -> str:
    folder = os.path.join(current_app.instance_path, "uploads", "lab_reports")
    os.makedirs(folder, exist_ok=True)
    return folder


@bp.post("/lab-reports")
@jwt_required()
def upload_lab_report():
    user = current_user()

    # Determine target patient
    patient_id = request.form.get("patient_id", type=int)
    if not patient_id:
        if user.role.value == "patient" and user.patient_profile:
            patient_id = user.patient_profile.id
        else:
            raise AppError("patient_id is required", 400, "validation_error")

    # Authorization check
    if not can_access_patient(user, patient_id):
        raise AppError("Permission denied to upload for this patient", 403, "permission_denied")

    if "file" not in request.files:
        raise AppError("No file uploaded", 400, "no_file")

    file = request.files["file"]
    if file.filename == "":
        raise AppError("No file selected", 400, "empty_file")

    if not allowed_file(file.filename):
        raise AppError("Invalid file type. Only PDF, PNG, and JPG files are permitted.", 400, "invalid_file_type")

    mime_type = detected_mime_type(file)
    if mime_type not in ALLOWED_MIME_TYPES:
        raise AppError("The uploaded file content is not a supported PDF or image.", 400, "invalid_file_content")

    extension_mime = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}
    extension = file.filename.rsplit(".", 1)[1].lower()
    if extension_mime[extension] != mime_type:
        raise AppError("The file extension does not match its content.", 400, "file_type_mismatch")

    orig_filename = secure_filename(file.filename)
    ext = orig_filename.rsplit(".", 1)[1].lower() if "." in orig_filename else "bin"
    unique_filename = f"{uuid.uuid4().hex}.{ext}"

    upload_dir = get_upload_folder()
    saved_path = os.path.join(upload_dir, unique_filename)
    file.save(saved_path)
    file_size = os.path.getsize(saved_path)

    test_name = request.form.get("test_name") or orig_filename
    report_title = request.form.get("report_title") or f"Lab Report: {test_name}"
    notes = request.form.get("notes")
    test_order_id = request.form.get("test_order_id", type=int)
    hospital_id = request.form.get("hospital_id", type=int)

    report = LabReport(
        patient_id=patient_id,
        test_order_id=test_order_id,
        hospital_id=hospital_id,
        report_title=report_title,
        test_name=test_name,
        file_path=saved_path,
        file_name=orig_filename,
        file_size_bytes=file_size,
        mime_type=mime_type,
        notes=notes,
        uploaded_by_user_id=user.id,
    )
    db.session.add(report)
    db.session.commit()

    log_action(user, "lab_report.uploaded", "LabReport", report.id)
    return ok({"lab_report": report.to_dict()}, "Lab report uploaded successfully", 201)


@bp.get("/lab-reports")
@jwt_required()
def list_lab_reports():
    user = current_user()
    patient_id = request.args.get("patient_id", type=int)

    if user.role.value == "patient":
        if not user.patient_profile:
            return ok({"lab_reports": []})
        patient_id = user.patient_profile.id

    if patient_id:
        if not can_access_patient(user, patient_id):
            raise AppError("Permission denied", 403, "permission_denied")
        reports = LabReport.query.filter_by(patient_id=patient_id, is_deleted=False).order_by(LabReport.created_at.desc()).all()
    elif user.role.value in ("admin", "super_admin"):
        reports = LabReport.query.filter_by(is_deleted=False).order_by(LabReport.created_at.desc()).limit(100).all()
    else:
        reports = []

    return ok({"lab_reports": [r.to_dict() for r in reports]})


@bp.get("/lab-reports/<int:report_id>/download")
@jwt_required()
def download_lab_report(report_id):
    user = current_user()
    report = db.session.get(LabReport, report_id)
    if not report or report.is_deleted:
        raise AppError("Lab report not found", 404, "not_found")

    if not can_access_patient(user, report.patient_id):
        raise AppError("Permission denied", 403, "permission_denied")

    if not os.path.exists(report.file_path):
        raise AppError("File not found on server", 404, "file_missing")

    return send_file(
        report.file_path,
        mimetype=report.mime_type,
        as_attachment=True,
        download_name=report.file_name,
    )


@bp.delete("/lab-reports/<int:report_id>")
@jwt_required()
def delete_lab_report(report_id):
    user = current_user()
    report = db.session.get(LabReport, report_id)
    if not report or report.is_deleted:
        raise AppError("Lab report not found", 404, "not_found")

    # Only uploader or admin can delete
    if report.uploaded_by_user_id != user.id and user.role.value not in ("admin", "super_admin"):
        raise AppError("Permission denied", 403, "permission_denied")

    report.is_deleted = True
    db.session.commit()
    log_action(user, "lab_report.deleted", "LabReport", report.id)
    return ok(None, "Lab report deleted")
