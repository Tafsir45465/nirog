"""Consent management service for handling patient consent workflows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from flask import request, current_app

from app.extensions import db
from app.models import (
    ConsentStatus,
    ConsentType,
    Patient,
    PatientConsent,
    Hospital,
    User,
)
from app.services.audit import log_action
from app.services.notifications import notify


# Default consent templates for different consent types
DEFAULT_CONSENT_TEMPLATES = {
    ConsentType.TREATMENT: {
        "title": "Informed Consent for Medical Treatment",
        "description": """I, the undersigned patient, hereby voluntarily consent to receive medical treatment at this healthcare facility. I understand that:

1. The nature of the proposed treatment, including its purpose, potential benefits, and risks, has been explained to me.
2. I have the right to refuse treatment at any time.
3. I have the opportunity to ask questions and receive answers about my treatment.
4. I understand that no guarantee has been made to me regarding the outcome of treatment.""",
    },
    ConsentType.DATA_SHARING: {
        "title": "Consent for Health Data Sharing",
        "description": """I consent to the sharing of my health information with authorized healthcare providers, insurance companies, and other parties as necessary for my care coordination. I understand that:

1. My health information will be shared in accordance with applicable privacy laws.
2. I may revoke this consent at any time.
3. Certain disclosures may be required by law even without my consent.
4. I have the right to request a copy of who has accessed my information.""",
    },
    ConsentType.RESEARCH: {
        "title": "Consent for Participation in Medical Research",
        "description": """I voluntarily agree to participate in medical research conducted by this healthcare facility. I understand that:

1. My participation is voluntary and I may withdraw at any time.
2. My identity will be protected to the extent possible.
3. There may be risks associated with research participation.
4. My data may be used for future research studies.""",
    },
    ConsentType.MARKETING: {
        "title": "Consent for Marketing Communications",
        "description": """I consent to receive marketing communications, newsletters, and health-related information from this healthcare facility. I understand that:

1. I may unsubscribe at any time.
2. My personal information will not be sold to third parties.
3. Communications may be sent via email, SMS, or other channels.""",
    },
    ConsentType.EMERGENCY_TREATMENT: {
        "title": "Emergency Treatment Authorization",
        "description": """In the event of a medical emergency, I authorize the healthcare facility to provide emergency treatment as deemed necessary by the attending medical professionals. I understand that:

1. Emergency treatment may be provided without prior consent if I am unable to give consent.
2. Every effort will be made to contact my emergency contact.
3. Treatment will be provided regardless of ability to pay.""",
    },
    ConsentType.TELEHEALTH: {
        "title": "Consent for Telehealth Services",
        "description": """I consent to receive healthcare services via telehealth (video/phone consultation). I understand that:

1. Telehealth involves the use of electronic communications to enable healthcare providers to deliver care.
2. There are potential risks including technology failures, interruptions, or breaches of confidentiality.
3. I have the right to refuse telehealth services at any time.
4. My healthcare provider may determine that telehealth is not appropriate for my condition.""",
    },
}


def get_consent_template(consent_type: ConsentType) -> dict:
    """Get the default consent template for a given consent type."""
    return DEFAULT_CONSENT_TEMPLATES.get(consent_type, {
        "title": f"Consent for {consent_type.value.replace('_', ' ').title()}",
        "description": f"I consent to {consent_type.value.replace('_', ' ')}.",
    })


def create_consent_request(
    patient_id: int,
    hospital_id: int,
    consent_type: ConsentType,
    title: Optional[str] = None,
    description: Optional[str] = None,
    version: str = "1.0",
    expires_in_days: Optional[int] = None,
    created_by: Optional[User] = None,
) -> PatientConsent:
    """Create a new consent request for a patient."""
    template = get_consent_template(consent_type)

    consent = PatientConsent(
        patient_id=patient_id,
        hospital_id=hospital_id,
        consent_type=consent_type,
        status=ConsentStatus.PENDING,
        title=title or template["title"],
        description=description or template["description"],
        version=version,
        expires_at=datetime.now(timezone.utc) + timedelta(days=expires_in_days) if expires_in_days else None,
    )

    db.session.add(consent)
    db.session.flush()

    # Audit log
    log_action(
        user=created_by,
        action="consent_created",
        entity="patient_consent",
        entity_id=consent.id,
        after=consent.to_dict(),
    )

    return consent


def grant_consent(
    consent_id: int,
    patient: Patient,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    signature_data: Optional[str] = None,
    notes: Optional[str] = None,
) -> PatientConsent:
    """Patient grants consent."""
    consent = db.session.get(PatientConsent, consent_id)
    if not consent:
        raise ValueError("Consent not found")

    if consent.patient_id != patient.id:
        raise PermissionError("You can only grant your own consent")

    if consent.status not in [ConsentStatus.PENDING, ConsentStatus.DENIED]:
        raise ValueError(f"Cannot grant consent with status {consent.status.value}")

    before = consent.to_dict()

    consent.status = ConsentStatus.GRANTED
    consent.granted_at = datetime.now(timezone.utc)
    consent.ip_address = ip_address
    consent.user_agent = user_agent
    consent.signature_data = signature_data
    consent.notes = notes

    db.session.flush()

    # Audit log
    log_action(
        user=patient.user,
        action="consent_granted",
        entity="patient_consent",
        entity_id=consent.id,
        before=before,
        after=consent.to_dict(),
    )

    # Notify
    notify(
        patient.user_id,
        "consent_granted",
        "Consent Granted",
        f"Your consent for {consent.consent_type.value.replace('_', ' ')} has been recorded.",
        {"consent_id": consent.id, "consent_type": consent.consent_type.value},
    )

    return consent


def deny_consent(
    consent_id: int,
    patient: Patient,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    notes: Optional[str] = None,
) -> PatientConsent:
    """Patient denies consent."""
    consent = db.session.get(PatientConsent, consent_id)
    if not consent:
        raise ValueError("Consent not found")

    if consent.patient_id != patient.id:
        raise PermissionError("You can only deny your own consent")

    if consent.status != ConsentStatus.PENDING:
        raise ValueError(f"Cannot deny consent with status {consent.status.value}")

    before = consent.to_dict()

    consent.status = ConsentStatus.DENIED
    consent.denied_at = datetime.now(timezone.utc)
    consent.ip_address = ip_address
    consent.user_agent = user_agent
    consent.notes = notes

    db.session.flush()

    # Audit log
    log_action(
        user=patient.user,
        action="consent_denied",
        entity="patient_consent",
        entity_id=consent.id,
        before=before,
        after=consent.to_dict(),
    )

    return consent


def revoke_consent(
    consent_id: int,
    patient: Patient,
    reason: Optional[str] = None,
) -> PatientConsent:
    """Patient revokes previously granted consent."""
    consent = db.session.get(PatientConsent, consent_id)
    if not consent:
        raise ValueError("Consent not found")

    if consent.patient_id != patient.id:
        raise PermissionError("You can only revoke your own consent")

    if consent.status != ConsentStatus.GRANTED:
        raise ValueError(f"Cannot revoke consent with status {consent.status.value}")

    before = consent.to_dict()

    consent.status = ConsentStatus.REVOKED
    consent.revoked_at = datetime.now(timezone.utc)
    consent.notes = reason

    db.session.flush()

    # Audit log
    log_action(
        user=patient.user,
        action="consent_revoked",
        entity="patient_consent",
        entity_id=consent.id,
        before=before,
        after=consent.to_dict(),
    )

    # Notify
    notify(
        patient.user_id,
        "consent_revoked",
        "Consent Revoked",
        f"Your consent for {consent.consent_type.value.replace('_', ' ')} has been revoked.",
        {"consent_id": consent.id, "consent_type": consent.consent_type.value},
    )

    return consent


def check_consent_status(
    patient_id: int,
    hospital_id: int,
    consent_type: ConsentType,
) -> dict:
    """Check if a patient has valid consent for a specific type."""
    consent = PatientConsent.query.filter_by(
        patient_id=patient_id,
        hospital_id=hospital_id,
        consent_type=consent_type,
    ).order_by(PatientConsent.created_at.desc()).first()

    if not consent:
        return {
            "has_consent": False,
            "status": None,
            "consent_id": None,
            "message": f"No consent record found for {consent_type.value}",
        }

    is_valid = consent.is_valid()

    return {
        "has_consent": is_valid,
        "status": consent.status.value,
        "consent_id": consent.id,
        "granted_at": consent.granted_at.isoformat() if consent.granted_at else None,
        "expires_at": consent.expires_at.isoformat() if consent.expires_at else None,
        "message": f"Consent is {'valid' if is_valid else consent.status.value}",
    }


def get_patient_consents(
    patient_id: int,
    hospital_id: Optional[int] = None,
    consent_type: Optional[ConsentType] = None,
    status: Optional[ConsentStatus] = None,
) -> list[PatientConsent]:
    """Get all consents for a patient with optional filters."""
    query = PatientConsent.query.filter_by(patient_id=patient_id)

    if hospital_id:
        query = query.filter_by(hospital_id=hospital_id)
    if consent_type:
        query = query.filter_by(consent_type=consent_type)
    if status:
        query = query.filter_by(status=status)

    return query.order_by(PatientConsent.created_at.desc()).all()


def get_hospital_consents(
    hospital_id: int,
    consent_type: Optional[ConsentType] = None,
    status: Optional[ConsentStatus] = None,
) -> list[PatientConsent]:
    """Get all consents for a hospital (admin view)."""
    query = PatientConsent.query.filter_by(hospital_id=hospital_id)

    if consent_type:
        query = query.filter_by(consent_type=consent_type)
    if status:
        query = query.filter_by(status=status)

    return query.order_by(PatientConsent.created_at.desc()).all()


def require_consent_for_appointment(
    patient_id: int,
    hospital_id: int,
    consent_type: ConsentType = ConsentType.TREATMENT,
) -> PatientConsent:
    """Check if patient has consent required for appointment. Raises ValueError if not."""
    result = check_consent_status(patient_id, hospital_id, consent_type)

    if not result["has_consent"]:
        raise ValueError(
            f"Patient consent required: {consent_type.value.replace('_', ' ')}. "
            f"Please provide consent before booking an appointment."
        )

    return db.session.get(PatientConsent, result["consent_id"])
