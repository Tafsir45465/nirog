import csv
import io
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, Response, send_file
from flask_jwt_extended import jwt_required

from ..errors import AppError
from ..extensions import db
from ..models import (
    Appointment,
    Patient,
    Invoice,
    InvoiceItem,
    Payment,
    Doctor,
    Hospital,
    Role,
)
from ..security import current_user, require_hospital_access, get_current_tenant

bp = Blueprint("exports", __name__, url_prefix="/api/exports")


def _safe_csv_value(value):
    """Prevent spreadsheet formula injection when CSV files are opened in Excel."""
    if value is None:
        return ""
    text = str(value)
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


class SafeCsvWriter:
    """csv.writer wrapper that sanitizes cells before writing rows."""

    def __init__(self, output: io.StringIO):
        self._writer = csv.writer(output)

    def writerow(self, row):
        self._writer.writerow([_safe_csv_value(value) for value in row])


def _csv_response(output: io.StringIO, filename_prefix: str) -> Response:
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename_prefix}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _get_hospital_filter(user, hospital_id=None):
    """Resolve hospital filter based on user role and tenant context."""
    tenant = get_current_tenant()
    if tenant:
        hospital_id = tenant.id
    elif not hospital_id and user.role != Role.SUPER_ADMIN:
        from ..security import hospital_ids_for_user
        hids = hospital_ids_for_user(user)
        hospital_id = next(iter(hids), None)

    if hospital_id:
        require_hospital_access(user, hospital_id)

    return hospital_id


@bp.route("/appointments/csv", methods=["GET"])
@jwt_required()
def export_appointments_csv():
    """Export appointments to CSV."""
    user = current_user()
    hospital_id = request.args.get("hospital_id", type=int)
    hospital_id = _get_hospital_filter(user, hospital_id)

    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    status = request.args.get("status")

    query = Appointment.query.filter(Appointment.deleted_at.is_(None))

    if hospital_id:
        query = query.filter_by(hospital_id=hospital_id)

    if start_date:
        query = query.filter(Appointment.scheduled_start >= start_date)
    if end_date:
        query = query.filter(Appointment.scheduled_start <= end_date)
    if status:
        query = query.filter(Appointment.status == status)

    appointments = query.order_by(Appointment.scheduled_start.desc()).all()

    output = io.StringIO()
    writer = SafeCsvWriter(output)
    writer.writerow([
        "Appointment ID", "Date", "Time", "Patient Name", "Patient Phone",
        "Doctor Name", "Specialty", "Hospital", "Status", "Type", "Reason", "Created At"
    ])

    for a in appointments:
        writer.writerow([
            a.id,
            a.scheduled_start.strftime("%Y-%m-%d") if a.scheduled_start else "",
            a.scheduled_start.strftime("%H:%M") if a.scheduled_start else "",
            a.patient.user.full_name if a.patient and a.patient.user else "",
            a.patient.user.phone if a.patient and a.patient.user else "",
            f"{a.doctor.professional_title} {a.doctor.user.full_name}" if a.doctor and a.doctor.user else "",
            a.doctor.specialty.name if a.doctor and a.doctor.specialty else "",
            a.hospital.name if a.hospital else "",
            a.status,
            a.appointment_type or "",
            a.reason or "",
            a.created_at.strftime("%Y-%m-%d %H:%M") if a.created_at else ""
        ])

    return _csv_response(output, "appointments")


@bp.route("/patients/csv", methods=["GET"])
@jwt_required()
def export_patients_csv():
    """Export patient roster to CSV."""
    user = current_user()
    if user.role not in [Role.SUPER_ADMIN, Role.ADMIN, Role.RECEPTIONIST]:
        raise AppError("Admin access required", 403, "permission_denied")

    hospital_id = request.args.get("hospital_id", type=int)
    hospital_id = _get_hospital_filter(user, hospital_id)

    query = Patient.query.filter(Patient.deleted_at.is_(None))

    if hospital_id:
        query = query.join(Appointment).filter(Appointment.hospital_id == hospital_id).distinct()

    patients = query.order_by(Patient.created_at.desc()).all()

    output = io.StringIO()
    writer = SafeCsvWriter(output)
    writer.writerow([
        "Patient ID", "Patient Code", "Full Name", "Email", "Phone",
        "Date of Birth", "Gender", "Blood Group", "Address",
        "Emergency Contact", "Emergency Phone", "Registered At"
    ])

    for p in patients:
        writer.writerow([
            p.id,
            p.patient_code or "",
            p.user.full_name if p.user else "",
            p.user.email if p.user else "",
            p.user.phone if p.user else "",
            p.date_of_birth.strftime("%Y-%m-%d") if p.date_of_birth else "",
            p.gender or "",
            p.blood_group or "",
            p.address or "",
            p.emergency_contact_name or "",
            p.emergency_contact_phone or "",
            p.created_at.strftime("%Y-%m-%d %H:%M") if p.created_at else ""
        ])

    return _csv_response(output, "patients")


@bp.route("/billing/invoices/csv", methods=["GET"])
@jwt_required()
def export_invoices_csv():
    """Export invoices to CSV."""
    user = current_user()
    hospital_id = request.args.get("hospital_id", type=int)
    hospital_id = _get_hospital_filter(user, hospital_id)

    status = request.args.get("status")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    query = Invoice.query.filter(Invoice.deleted_at.is_(None))

    if hospital_id:
        query = query.filter_by(hospital_id=hospital_id)

    if user.role == Role.PATIENT:
        if not user.patient_profile:
            return Response("", mimetype="text/csv")
        query = query.filter_by(patient_id=user.patient_profile.id)

    if status:
        query = query.filter(Invoice.status == status)
    if start_date:
        query = query.filter(Invoice.created_at >= start_date)
    if end_date:
        query = query.filter(Invoice.created_at <= end_date)

    invoices = query.order_by(Invoice.created_at.desc()).all()

    output = io.StringIO()
    writer = SafeCsvWriter(output)
    writer.writerow([
        "Invoice Number", "Date", "Patient Name", "Patient Phone",
        "Hospital", "Total Amount", "Discount", "Tax", "Payable",
        "Paid Amount", "Due Amount", "Status", "Payment Date"
    ])

    for inv in invoices:
        writer.writerow([
            inv.invoice_number,
            inv.created_at.strftime("%Y-%m-%d") if inv.created_at else "",
            inv.patient.user.full_name if inv.patient and inv.patient.user else "",
            inv.patient.user.phone if inv.patient and inv.patient.user else "",
            inv.hospital.name if inv.hospital else "",
            f"{float(inv.total_amount):.2f}",
            f"{float(inv.discount_amount):.2f}",
            f"{float(inv.tax_amount):.2f}",
            f"{float(inv.payable_amount):.2f}",
            f"{float(inv.paid_amount):.2f}",
            f"{float(inv.due_amount):.2f}",
            inv.status,
            inv.paid_at.strftime("%Y-%m-%d") if inv.paid_at else ""
        ])

    return _csv_response(output, "invoices")


@bp.route("/billing/payments/csv", methods=["GET"])
@jwt_required()
def export_payments_csv():
    """Export payments to CSV."""
    user = current_user()
    if user.role not in [Role.SUPER_ADMIN, Role.ADMIN, Role.RECEPTIONIST]:
        raise AppError("Admin access required", 403, "permission_denied")

    hospital_id = request.args.get("hospital_id", type=int)
    hospital_id = _get_hospital_filter(user, hospital_id)

    query = Payment.query

    if hospital_id:
        query = query.filter_by(hospital_id=hospital_id)

    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    if start_date:
        query = query.filter(Payment.payment_date >= start_date)
    if end_date:
        query = query.filter(Payment.payment_date <= end_date)

    payments = query.order_by(Payment.payment_date.desc()).all()

    output = io.StringIO()
    writer = SafeCsvWriter(output)
    writer.writerow([
        "Payment Number", "Date", "Invoice Number", "Patient Name",
        "Amount", "Method", "Transaction ID", "Status", "Received By"
    ])

    for p in payments:
        writer.writerow([
            p.payment_number,
            p.payment_date.strftime("%Y-%m-%d %H:%M") if p.payment_date else "",
            p.invoice.invoice_number if p.invoice else "",
            p.patient.user.full_name if p.patient and p.patient.user else "",
            f"{float(p.amount):.2f}",
            p.payment_method.upper(),
            p.transaction_id or "",
            p.status,
            p.received_by.full_name if p.received_by else ""
        ])

    return _csv_response(output, "payments")


@bp.route("/doctors/performance/csv", methods=["GET"])
@jwt_required()
def export_doctor_performance_csv():
    """Export doctor performance metrics to CSV."""
    user = current_user()
    if user.role not in [Role.SUPER_ADMIN, Role.ADMIN]:
        raise AppError("Admin access required", 403, "permission_denied")

    hospital_id = request.args.get("hospital_id", type=int)
    hospital_id = _get_hospital_filter(user, hospital_id)

    from ..models import DoctorHospitalAssignment
    from sqlalchemy import func

    query = db.session.query(
        Doctor.id,
        Doctor.license_number,
        func.count(Appointment.id).label("total_appointments"),
        func.sum((Appointment.status == "completed").cast(db.Integer)).label("completed"),
        func.sum((Appointment.status == "cancelled").cast(db.Integer)).label("cancelled"),
    ).outerjoin(
        Appointment, Appointment.doctor_id == Doctor.id
    )

    if hospital_id:
        query = query.join(
            DoctorHospitalAssignment, DoctorHospitalAssignment.doctor_id == Doctor.id
        ).filter(
            DoctorHospitalAssignment.hospital_id == hospital_id,
            DoctorHospitalAssignment.is_active == True
        )

    query = query.group_by(Doctor.id)

    results = query.all()

    output = io.StringIO()
    writer = SafeCsvWriter(output)
    writer.writerow([
        "Doctor ID", "Name", "Specialty", "License #", "Consultation Fee",
        "Total Appointments", "Completed", "Cancelled", "Completion Rate %"
    ])

    for doc_id, license_num, total, completed, cancelled in results:
        doctor = db.session.get(Doctor, doc_id)
        if doctor:
            writer.writerow([
                doc_id,
                doctor.user.full_name if doctor.user else "",
                doctor.specialty.name if doctor.specialty else "General",
                license_num,
                f"{float(doctor.consultation_fee):.2f}" if doctor.consultation_fee else "0.00",
                total or 0,
                completed or 0,
                cancelled or 0,
                round((completed or 0) / (total or 1) * 100, 1)
            ])

    return _csv_response(output, "doctor_performance")
