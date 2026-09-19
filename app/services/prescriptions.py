from __future__ import annotations

from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.errors import AppError
from app.extensions import db
from app.models import (
    Consultation,
    MedicalTest,
    Medicine,
    Prescription,
    PrescriptionItem,
    PrescriptionStatus,
    TestOrder,
    User,
    utcnow,
)
from app.services.audit import log_action
from app.services.notifications import notify


def create_prescription(actor: User, consultation: Consultation, payload: dict):
    prescription = Prescription(
        prescription_code=f"RX-{consultation.id}-{int(utcnow().timestamp())}",
        consultation_id=consultation.id,
        patient_id=consultation.patient_id,
        doctor_id=consultation.doctor_id,
        hospital_id=consultation.hospital_id,
        diagnosis_summary=payload.get("diagnosis_summary"),
        advice=payload.get("advice"),
        status=PrescriptionStatus.DRAFT,
    )
    if payload.get("follow_up_date"):
        from datetime import date
        prescription.follow_up_date = date.fromisoformat(payload["follow_up_date"])
    db.session.add(prescription)
    db.session.flush()
    for item in payload.get("items", []):
        medicine = db.session.get(Medicine, item.get("medicine_id")) if item.get("medicine_id") else None
        db.session.add(PrescriptionItem(
            prescription_id=prescription.id,
            medicine_id=medicine.id if medicine else None,
            medicine_name_snapshot=item.get("medicine_name") or (medicine.brand_name or medicine.generic_name if medicine else None),
            strength_snapshot=item.get("strength") or (medicine.strength if medicine else None),
            dosage=item["dosage"],
            frequency=item["frequency"],
            route=item.get("route"),
            duration=item["duration"],
            quantity=item.get("quantity"),
            timing=item.get("timing"),
            meal_instruction=item.get("meal_instruction"),
            instructions=item.get("instructions"),
        ))
    for test in payload.get("tests", []):
        medical_test = db.session.get(MedicalTest, test.get("medical_test_id")) if test.get("medical_test_id") else None
        db.session.add(TestOrder(
            prescription_id=prescription.id,
            medical_test_id=medical_test.id if medical_test else None,
            test_name_snapshot=test.get("test_name") or (medical_test.name if medical_test else None),
            instructions=test.get("instructions"),
        ))
    log_action(actor, "prescription.created", "Prescription", prescription.id)
    return prescription


def finalize_prescription(actor: User, prescription: Prescription):
    if prescription.status != PrescriptionStatus.DRAFT:
        raise AppError("Only draft prescriptions can be finalized", 400, "not_draft")
    prescription.status = PrescriptionStatus.FINALIZED
    prescription.finalized_at = utcnow()
    prescription.finalized_by_user_id = actor.id

    notify(
        prescription.patient.user_id,
        "prescription_finalized",
        "Prescription finalized",
        "Your prescription is ready",
        {"prescription_id": prescription.id},
    )
    log_action(actor, "prescription.finalized", "Prescription", prescription.id, after=prescription.to_dict())
    return prescription


def ensure_editable(prescription: Prescription):
    if prescription.status == PrescriptionStatus.FINALIZED:
        raise AppError("Finalized prescriptions cannot be silently modified. Create an amendment.", 409, "finalized_immutable")


def render_prescription_pdf(prescription: Prescription) -> bytes:
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 50
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, y, prescription.hospital.name)
    y -= 20
    p.setFont("Helvetica", 10)
    p.drawString(50, y, prescription.hospital.address)
    y -= 30
    p.setFont("Helvetica-Bold", 13)
    p.drawString(50, y, "Prescription")
    p.drawRightString(width - 50, y, prescription.prescription_code)
    y -= 30
    p.setFont("Helvetica", 10)
    p.drawString(50, y, f"Patient: {prescription.patient.user.full_name} ({prescription.patient.patient_code})")
    y -= 16
    p.drawString(50, y, f"Doctor: {prescription.doctor.professional_title} {prescription.doctor.user.full_name} | {prescription.doctor.specialty.name if prescription.doctor.specialty else ''}")
    y -= 16
    p.drawString(50, y, f"License: {prescription.doctor.license_number}")
    y -= 28
    p.setFont("Helvetica-Bold", 11)
    p.drawString(50, y, "Diagnosis")
    y -= 14
    p.setFont("Helvetica", 10)
    p.drawString(50, y, prescription.diagnosis_summary or "-")
    y -= 28
    p.setFont("Helvetica-Bold", 11)
    p.drawString(50, y, "Medicines")
    y -= 16
    p.setFont("Helvetica", 9)
    for idx, item in enumerate(prescription.items, 1):
        line = f"{idx}. {item.medicine_name_snapshot} {item.strength_snapshot or ''} - {item.dosage}, {item.frequency}, {item.duration}; {item.meal_instruction or ''} {item.instructions or ''}"
        p.drawString(60, y, line[:115])
        y -= 14
    y -= 10
    p.setFont("Helvetica-Bold", 11)
    p.drawString(50, y, "Tests")
    y -= 16
    p.setFont("Helvetica", 9)
    for idx, test in enumerate(prescription.tests, 1):
        p.drawString(60, y, f"{idx}. {test.test_name_snapshot} {test.instructions or ''}"[:115])
        y -= 14
    y -= 12
    p.drawString(50, y, f"Advice: {prescription.advice or '-'}"[:115])
    y -= 14
    p.drawString(50, y, f"Follow-up: {prescription.follow_up_date.isoformat() if prescription.follow_up_date else '-'}")
    p.showPage()
    p.save()
    return buffer.getvalue()
