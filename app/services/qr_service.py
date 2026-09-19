"""QR code service for patient identification."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from flask import current_app, send_from_directory

from app.extensions import db
from app.models import Patient, User
from app.services.audit import log_action


def generate_patient_qr_code(patient_id: int, hospital_id: int = None) -> dict:
    """Generate a QR code for patient identification.
    
    The QR code encodes the patient ID and hospital ID for scanning at reception.
    """
    # Get patient details
    patient = db.session.get(Patient, patient_id)
    if not patient:
        raise ValueError(f"Patient not found: {patient_id}")

    hospital = db.session.get(type('Hospital', (), {'id': hospital_id})(), hospital_id) if hospital_id else None

    # Generate QR code data
    # Format: patient_id:hospital_id:timestamp
    qr_data = f"{patient_id}:{hospital_id or '0'}:{datetime.now(timezone.utc).isoformat()}"
    
    # Generate a unique filename
    qr_filename = f"patient_qr_{patient_id}_{uuid.uuid4().hex[:8]}.png"
    qr_path = os.path.join(current_app.config.get("QR_CODE_DIR", "qr_codes"), qr_filename)
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(qr_path), exist_ok=True)
    
    # Generate QR code using available library
    try:
        import qrcode
        
        img = qrcode.make(qr_data)
        img.save(qr_path)
        
    except ImportError:
        # Fallback: create a placeholder image
        from PIL import Image, ImageDraw
        img = Image.new('RGB', (300, 300), color='white')
        draw = ImageDraw.Draw(img)
        # Try to draw QR pattern
        try:
            draw.rectangle([50, 50, 250, 250], fill='black')
        except:
            pass
        img.save(qr_path)
    
    # Update patient QR code record
    patient.qr_code = qr_filename
    db.session.flush()
    
    # Audit log
    log_action(
        user=patient.user,
        action="qr_code_generated",
        entity="patient_qr_code",
        entity_id=patient.id,
        after={"qr_code": qr_filename, "patient_id": patient_id},
    )
    
    return {
        "qr_code": qr_filename,
        "qr_url": f"/api/qr/{qr_filename}",
        "qr_data": qr_data,
        "patient_name": patient.user.full_name if patient.user else "Unknown",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_patient_qr_code(patient_id: int) -> Optional[dict]:
    """Get existing QR code for a patient."""
    patient = db.session.get(Patient, patient_id)
    if not patient or not patient.qr_code:
        return None
    
    return {
        "qr_code": patient.qr_code,
        "qr_url": f"/api/qr/{patient.qr_code}",
        "patient_name": patient.user.full_name if patient.user else "Unknown",
    }


def get_qr_code_file(qr_filename: str):
    """Serve a QR code file."""
    qr_dir = current_app.config.get("QR_CODE_DIR", "qr_codes")
    return send_from_directory(qr_dir, qr_filename)


def cleanup_old_qr_codes(days: int = 365) -> int:
    """Clean up old QR code files."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    
    qr_dir = current_app.config.get("QR_CODE_DIR", "qr_codes")
    if not os.path.exists(qr_dir):
        return 0
    
    deleted = 0
    for filename in os.listdir(qr_dir):
        filepath = os.path.join(qr_dir, filename)
        if os.path.getmtime(filepath) < cutoff.timestamp():
            try:
                os.remove(filepath)
                deleted += 1
            except OSError:
                pass
    
    return deleted