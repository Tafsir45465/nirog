"""Doctor reviews and ratings routes."""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app.errors import AppError
from app.extensions import db
from app.models import Review, Doctor, Patient, Role, Consultation
from app.security import current_user, require_patient_access, roles_required
from app.utils.responses import ok, error

bp = Blueprint("reviews", __name__, url_prefix="/api/reviews")


@bp.post("/<int:doctor_id>")
@jwt_required()
def create_review(doctor_id: int):
    """Create a review for a doctor."""
    user = current_user()
    if user.role != Role.PATIENT or not user.patient_profile:
        raise AppError("Only patients can write reviews", 403, "permission_denied")

    # Check if doctor exists
    doctor = db.session.get(Doctor, doctor_id)
    if not doctor:
        raise AppError("Doctor not found", 404, "not_found")

    data = request.get_json(silent=True) or {}

    rating = data.get("rating")
    if not rating or rating < 1 or rating > 5:
        raise AppError("Rating must be between 1 and 5", 400, "invalid_rating")

    title = data.get("title", "")
    description = data.get("description", "")

    # Check if patient has had a completed consultation with this doctor
    has_consultation = False
    if doctor.hospital_assignments:
        # Use explicit query instead of relying on relationship
        completed_consult = db.session.query(Consultation).filter_by(
            doctor_id=doctor_id,
            patient_id=user.patient_profile.id,
            status="completed"
        ).first()
        has_consultation = completed_consult is not None

    # Check if already reviewed
    existing = Review.query.filter_by(
        patient_id=user.patient_profile.id,
        doctor_id=doctor_id,
    ).first()

    if existing:
        raise AppError("You have already reviewed this doctor", 400, "already_reviewed")

    review = Review(
        patient_id=user.patient_profile.id,
        doctor_id=doctor_id,
        hospital_id=doctor.hospital_assignments[0].hospital_id if doctor.hospital_assignments else None,
        rating=rating,
        title=title,
        description=description,
        verified=has_consultation,
    )

    db.session.add(review)
    db.session.commit()

    return ok(
        data=review.to_dict(),
        message="Review submitted successfully",
    )


@bp.get("/my/<int:doctor_id>")
@jwt_required()
def get_my_review(doctor_id: int):
    """Get current patient's review for a doctor."""
    user = current_user()
    if user.role != Role.PATIENT or not user.patient_profile:
        raise AppError("Only patients can view their reviews", 403, "permission_denied")

    review = Review.query.filter_by(
        patient_id=user.patient_profile.id,
        doctor_id=doctor_id,
    ).first()

    if not review:
        return ok(data=None, message="No review found")

    return ok(data=review.to_dict())


@bp.get("/doctor/<int:doctor_id>")
@jwt_required()
def get_doctor_reviews(doctor_id: int):
    """Get all reviews for a doctor."""
    doctor = db.session.get(Doctor, doctor_id)
    if not doctor:
        raise AppError("Doctor not found", 404, "not_found")

    reviews = Review.query.filter_by(doctor_id=doctor_id).order_by(Review.created_at.desc()).all()

    # Calculate average rating
    avg_rating = round(sum(r.rating for r in reviews) / len(reviews), 2) if reviews else 0

    reviews_data = [r.to_dict() for r in reviews]

    return ok(
        data={
            "reviews": reviews_data,
            "average_rating": avg_rating,
            "total_reviews": len(reviews),
        },
    )


@bp.post("/<int:review_id>/verify")
@jwt_required()
@roles_required(Role.SUPER_ADMIN)
def verify_review(review_id: int):
    """Verify a review (super admin only)."""
    review = db.session.get(Review, review_id)
    if not review:
        raise AppError("Review not found", 404, "not_found")

    review.verified = True
    db.session.commit()

    return ok(data=review.to_dict(), message="Review verified successfully")