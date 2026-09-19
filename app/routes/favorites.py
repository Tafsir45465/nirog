"""Favorite doctors management routes."""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app.errors import AppError
from app.extensions import db
from app.models import Favorite, Doctor, Role
from app.security import current_user, require_patient_access, roles_required
from app.utils.responses import ok, error

bp = Blueprint("favorites", __name__, url_prefix="/api/favorites")


@bp.post("/toggle/<int:doctor_id>")
@jwt_required()
def toggle_favorite(doctor_id: int):
    """Toggle a doctor in patient's favorites list."""
    user = current_user()
    if user.role != Role.PATIENT or not user.patient_profile:
        raise AppError("Only patients can manage favorites", 403, "permission_denied")

    # Check if doctor exists
    doctor = db.session.get(Doctor, doctor_id)
    if not doctor:
        raise AppError("Doctor not found", 404, "not_found")

    # Check if already favorited
    existing = Favorite.query.filter_by(
        patient_id=user.patient_profile.id,
        doctor_id=doctor_id,
    ).first()

    if existing:
        # Remove from favorites
        db.session.delete(existing)
        db.session.commit()
        return ok(
            message="Doctor removed from favorites",
            data={"is_favorited": False, "doctor_id": doctor_id},
        )
    else:
        # Add to favorites
        favorite = Favorite(
            patient_id=user.patient_profile.id,
            doctor_id=doctor_id,
            hospital_id=doctor.hospital_assignments[0].hospital_id if doctor.hospital_assignments else None,
        )
        db.session.add(favorite)
        db.session.commit()
        return ok(
            message="Doctor added to favorites",
            data={"is_favorited": True, "doctor_id": doctor_id},
        )


@bp.get("/my")
@jwt_required()
def list_my_favorites():
    """List current patient's favorite doctors."""
    user = current_user()
    if user.role != Role.PATIENT or not user.patient_profile:
        raise AppError("Only patients can view favorites", 403, "permission_denied")

    favorites = Favorite.query.filter_by(patient_id=user.patient_profile.id).all()

    # Get doctor details
    favorites_data = []
    for fav in favorites:
        doctor = fav.doctor
        if doctor:
            favorites_data.append({
                "id": fav.id,
                "doctor_id": doctor.id,
                "doctor_name": doctor.user.full_name if doctor.user else "Unknown",
                "title": doctor.professional_title,
                "specialty": doctor.specialty.name if doctor.specialty else None,
                "qualifications": doctor.qualifications,
                "consultation_fee": float(doctor.consultation_fee),
                "is_active": doctor.is_bookable(),
                "created_at": fav.created_at.isoformat() if fav.created_at else None,
            })

    return ok(
        data=favorites_data,
        meta={"total": len(favorites_data)},
    )


@bp.delete("/<int:favorite_id>")
@jwt_required()
def remove_favorite(favorite_id: int):
    """Remove a specific favorite."""
    user = current_user()
    if user.role != Role.PATIENT or not user.patient_profile:
        raise AppError("Only patients can remove favorites", 403, "permission_denied")

    favorite = db.session.get(Favorite, favorite_id)
    if not favorite:
        raise AppError("Favorite not found", 404, "not_found")

    # Verify ownership
    if favorite.patient_id != user.patient_profile.id:
        raise AppError("Access denied", 403, "access_denied")

    db.session.delete(favorite)
    db.session.commit()

    return ok(message="Favorite removed successfully")