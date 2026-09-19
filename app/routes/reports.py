from __future__ import annotations

import io
import csv
from datetime import date, timedelta
from typing import List, Dict, Any

import pandas as pd
from flask import Blueprint, request, send_file
from flask_jwt_extended import jwt_required

from app.extensions import db
from app.models import Appointment, Hospital, Queue, User, Patient, Doctor, Consultation, Prescription
from app.security import current_user, hospital_ids_for_user
from app.utils.responses import ok, error as api_error

bp = Blueprint("reports", __name__, url_prefix="/api")


@bp.get("/reports/dashboard")
@jwt_required()
def dashboard():
    user = current_user()
    today = date.today()
    start = today - timedelta(days=int(request.args.get("days", "30")))
    if user.role.value == "super_admin":
        hospitals = Hospital.query.filter(Hospital.is_active.is_(True)).count()
        appointments = Appointment.query.filter(Appointment.scheduled_start >= start).count()
        completed = Appointment.query.filter(Appointment.status == "completed", Appointment.scheduled_start >= start).count()
        cancelled = Appointment.query.filter(Appointment.status == "cancelled", Appointment.scheduled_start >= start).count()
        return ok({"hospitals": hospitals, "appointments": appointments, "completed": completed, "cancelled": cancelled})


@bp.get("/exports/appointments/excel")
@jwt_required()
def export_appointments_excel():
    """Export appointments to Excel file."""
    user = current_user()
    
    # Build query based on user role
    if user.role.value == "super_admin":
        appointments = Appointment.query.all()
    elif user.role.value in {"admin", "receptionist"}:
        allowed = hospital_ids_for_user(user)
        appointments = Appointment.query.filter(Appointment.hospital_id.in_(allowed)).all() if allowed else []
    elif user.role.value == "patient" and user.patient_profile:
        appointments = Appointment.query.filter_by(patient_id=user.patient_profile.id).all()
    elif user.role.value == "doctor" and user.doctor_profile:
        appointments = Appointment.query.filter_by(doctor_id=user.doctor_profile.id).all()
    else:
        appointments = Appointment.query.limit(100).all()
    
    # Convert to DataFrame
    data = []
    for a in appointments:
        data.append({
            "ID": a.id,
            "Patient ID": a.patient_id,
            "Patient Name": a.patient.user.full_name if a.patient else "N/A",
            "Doctor ID": a.doctor_id,
            "Doctor Name": a.doctor.user.full_name if a.doctor else "N/A",
            "Hospital ID": a.hospital_id,
            "Hospital Name": a.hospital.name if a.hospital else "N/A",
            "Department ID": a.department_id or "",
            "Scheduled Start": a.scheduled_start.isoformat() if a.scheduled_start else "",
            "Scheduled End": a.scheduled_end.isoformat() if a.scheduled_end else "",
            "Status": a.status.value if a.status else "",
            "Appointment Type": a.appointment_type or "",
            "Reason": a.reason or "",
        })
    
    df = pd.DataFrame(data)
    
    # Export to Excel
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Appointments")
    output.seek(0)
    
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheet.sheet",
        download_name="appointments_export.xlsx",
        as_attachment=True,
    )


@bp.get("/exports/appointments/pdf")
@jwt_required()
def export_appointments_pdf():
    """Export appointments to PDF report using ReportLab."""
    user = current_user()
    
    # Build query based on user role
    if user.role.value == "super_admin":
        appointments = Appointment.query.all()
    elif user.role.value in {"admin", "receptionist"}:
        allowed = hospital_ids_for_user(user)
        appointments = Appointment.query.filter(Appointment.hospital_id.in_(allowed)).all() if allowed else []
    elif user.role.value == "patient" and user.patient_profile:
        appointments = Appointment.query.filter_by(patient_id=user.patient_profile.id).all()
    elif user.role.value == "doctor" and user.doctor_profile:
        appointments = Appointment.query.filter_by(doctor_id=user.doctor_profile.id).all()
    else:
        appointments = Appointment.query.limit(100).all()
    
    # Generate PDF using ReportLab
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # Header
    p.setFont("Helvetica-Bold", 18)
    p.drawString(50, height - 50, "Appointment Report")
    p.setFont("Helvetica", 12)
    p.drawString(50, height - 80, f"Generated: {date.today().isoformat()}")
    p.drawString(50, height - 95, f"User: {user.full_name} ({user.email})")
    
    # Table headers
    y = height - 130
    p.setFont("Helvetica-Bold", 9)
    headers = ["ID", "Patient", "Doctor", "Hospital", "Date", "Status", "Type"]
    col_widths = [0.8*inch, 1.5*inch, 1.5*inch, 1.5*inch, 1.2*inch, 0.8*inch, 1.0*inch]
    x_start = 50
    
    for i, header in enumerate(headers):
        p.drawString(x_start + sum(col_widths[:i]), y, header)
    
    y -= 12
    p.setFont("Helvetica", 8)
    
    for idx, a in enumerate(appointments):
        row_data = [
            str(a.id),
            a.patient.user.full_name if a.patient else "N/A",
            a.doctor.user.full_name if a.doctor else "N/A",
            a.hospital.name if a.hospital else "N/A",
            a.scheduled_start.strftime("%Y-%m-%d %H:%M") if a.scheduled_start else "",
            a.status.value if a.status else "",
            a.appointment_type or "",
        ]
        
        for i, cell in enumerate(row_data):
            p.drawString(x_start + sum(col_widths[:i]), y, cell)
        
        y -= 10
        if y < 50:
            p.showPage()
            y = height - 50
            p.setFont("Helvetica-Bold", 9)
            for i, header in enumerate(headers):
                p.drawString(x_start + sum(col_widths[:i]), y, header)
            y -= 12
            p.setFont("Helvetica", 8)
    
    p.showPage()
    p.save()
    buffer.seek(0)
    
    return send_file(
        buffer,
        mimetype="application/pdf",
        download_name="appointments_report.pdf",
        as_attachment=True,
    )


@bp.get("/exports/prescriptions/pdf")
@jwt_required()
def export_prescriptions_pdf():
    """Export prescriptions to PDF report."""
    user = current_user()
    
    # Build query based on user role
    if user.role.value == "super_admin":
        prescriptions = Prescription.query.all()
    elif user.role.value in {"admin", "receptionist"}:
        allowed = hospital_ids_for_user(user)
        prescriptions = Prescription.query.filter(Prescription.hospital_id.in_(allowed)).all() if allowed else []
    elif user.role.value == "patient" and user.patient_profile:
        prescriptions = Prescription.query.filter_by(patient_id=user.patient_profile.id).all()
    elif user.role.value == "doctor" and user.doctor_profile:
        prescriptions = Prescription.query.filter_by(doctor_id=user.doctor_profile.id).all()
    else:
        prescriptions = Prescription.query.limit(50).all()
    
    # Generate PDF using existing ReportLab logic
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 50
    
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, y, "Prescription Report")
    y -= 30
    p.setFont("Helvetica", 10)
    p.drawString(50, y, f"Generated: {date.today().isoformat()}")
    y -= 30
    p.drawString(50, y, f"User: {user.full_name} ({user.email})")
    y -= 50
    
    p.setFont("Helvetica-Bold", 11)
    p.drawString(50, y, "Prescription Code")
    p.drawRightString(width - 50, y, "Patient")
    y -= 16
    
    p.setFont("Helvetica", 9)
    
    for idx, pres in enumerate(prescriptions):
        y -= 14
        p.drawString(50, y, pres.prescription_code)
        p.drawRightString(width - 50, y, pres.patient.user.full_name if pres.patient else "N/A")
        y -= 14
        
        if y < 50:
            p.showPage()
            y = height - 50
            p.setFont("Helvetica-Bold", 11)
            p.drawString(50, y, "Prescription Code")
            p.drawRightString(width - 50, y, "Patient")
            y -= 16
            p.setFont("Helvetica", 9)
    
    p.showPage()
    p.save()
    buffer.seek(0)
    
    return send_file(
        buffer,
        mimetype="application/pdf",
        download_name="prescriptions_report.pdf",
        as_attachment=True,
    )