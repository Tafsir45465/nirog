from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt_identity

from ..errors import AppError
from ..extensions import db
from ..models import Hospital, HospitalBranch, Role, User
from ..security import (
    current_user,
    can_access_hospital,
    require_hospital_access,
    get_current_tenant,
    require_tenant,
)

bp = Blueprint("tenants", __name__, url_prefix="/api/tenants")


@bp.route("", methods=["GET"])
@jwt_required()
def list_tenants():
    """List all tenants (hospitals) - super admin only."""
    user = current_user()
    if user.role != Role.SUPER_ADMIN:
        raise AppError("Admin access required", 403, "admin_required")

    hospitals = Hospital.query.filter(Hospital.is_active == True).all()
    return jsonify({
        "data": {
            "tenants": [h.to_dict() for h in hospitals]
        }
    })


@bp.route("/<int:tenant_id>", methods=["GET"])
@jwt_required()
def get_tenant(tenant_id):
    """Get tenant details."""
    user = current_user()
    hospital = db.session.get(Hospital, tenant_id)
    if not hospital:
        raise AppError("Hospital not found", 404, "not_found")

    require_hospital_access(user, tenant_id)

    branches = HospitalBranch.query.filter_by(hospital_id=tenant_id, is_active=True).all()
    return jsonify({
        "data": {
            "hospital": hospital.to_dict(),
            "branches": [{"id": b.id, "name": b.name, "address": b.address, "phone": b.phone, "room_prefix": b.room_prefix}
                         for b in branches]
        }
    })


@bp.route("", methods=["POST"])
@jwt_required()
def create_tenant():
    """Create a new hospital/tenant - super admin only."""
    user = current_user()
    if user.role != Role.SUPER_ADMIN:
        raise AppError("Super admin access required", 403, "admin_required")

    data = request.get_json() or {}
    name = data.get("name", "").strip()
    slug = data.get("slug", "").strip().lower()
    address = data.get("address", "").strip()
    phone = data.get("phone", "").strip()
    email = data.get("email", "").strip()
    subscription_tier = data.get("subscription_tier", "free")
    max_doctors = data.get("max_doctors", 5)

    if not name or not slug or not address or not phone:
        raise AppError("Name, slug, address, and phone are required", 400, "validation_error")

    if Hospital.query.filter_by(slug=slug).first():
        raise AppError("Hospital slug already exists", 400, "slug_exists")

    hospital = Hospital(
        name=name,
        slug=slug,
        address=address,
        phone=phone,
        email=email,
        subscription_tier=subscription_tier,
        max_doctors=max_doctors,
        subscription_status="active",
    )
    db.session.add(hospital)
    db.session.commit()

    return jsonify({"data": {"hospital": hospital.to_dict()}}), 201


@bp.route("/<int:tenant_id>", methods=["PUT", "PATCH"])
@jwt_required()
def update_tenant(tenant_id):
    """Update tenant configuration."""
    user = current_user()
    if user.role != Role.SUPER_ADMIN:
        raise AppError("Super admin access required", 403, "admin_required")

    hospital = db.session.get(Hospital, tenant_id)
    if not hospital:
        raise AppError("Hospital not found", 404, "not_found")

    data = request.get_json() or {}
    updatable = [
        "name", "address", "phone", "email", "website", "description",
        "emergency_info", "opening_hours", "is_active", "subscription_tier",
        "subscription_status", "subscription_expires_at", "custom_domain",
        "max_doctors", "tenant_settings"
    ]

    for field in updatable:
        if field in data:
            setattr(hospital, field, data[field])

    db.session.commit()
    return jsonify({"data": {"hospital": hospital.to_dict()}})


@bp.route("/<int:tenant_id>/branches", methods=["GET"])
@jwt_required()
def list_branches(tenant_id):
    """List branches for a tenant."""
    user = current_user()
    require_hospital_access(user, tenant_id)

    branches = HospitalBranch.query.filter_by(hospital_id=tenant_id, is_active=True).all()
    return jsonify({
        "data": {
            "branches": [{"id": b.id, "name": b.name, "address": b.address, "phone": b.phone, "room_prefix": b.room_prefix}
                         for b in branches]
        }
    })


@bp.route("/<int:tenant_id>/branches", methods=["POST"])
@jwt_required()
def create_branch(tenant_id):
    """Create a new branch for a tenant."""
    user = current_user()
    if user.role != Role.SUPER_ADMIN:
        raise AppError("Super admin access required", 403, "admin_required")

    hospital = db.session.get(Hospital, tenant_id)
    if not hospital:
        raise AppError("Hospital not found", 404, "not_found")

    data = request.get_json() or {}
    name = data.get("name", "").strip()
    address = data.get("address", "").strip()
    phone = data.get("phone", "").strip()
    room_prefix = data.get("room_prefix", "").strip()

    if not name or not address:
        raise AppError("Name and address are required", 400, "validation_error")

    branch = HospitalBranch(
        hospital_id=tenant_id,
        name=name,
        address=address,
        phone=phone,
        room_prefix=room_prefix,
    )
    db.session.add(branch)
    db.session.commit()

    return jsonify({"data": {"branch": {
        "id": branch.id,
        "name": branch.name,
        "address": branch.address,
        "phone": branch.phone,
        "room_prefix": branch.room_prefix
    }}}), 201


@bp.route("/me", methods=["GET"])
@jwt_required()
def get_current_tenant_info():
    """Get the current tenant context from headers."""
    user = current_user()
    tenant = get_current_tenant()

    if not tenant:
        raise AppError("No tenant context found", 400, "tenant_required")

    require_hospital_access(user, tenant.id)

    branches = HospitalBranch.query.filter_by(hospital_id=tenant.id, is_active=True).all()
    return jsonify({
        "data": {
            "hospital": tenant.to_dict(),
            "branches": [{"id": b.id, "name": b.name, "address": b.address, "phone": b.phone, "room_prefix": b.room_prefix}
                         for b in branches]
        }
    })


@bp.route("/subscription/check", methods=["GET"])
@jwt_required()
def check_subscription():
    """Check if current tenant has valid subscription."""
    user = current_user()
    tenant = require_tenant()

    # Check doctor limit
    from ..models import DoctorHospitalAssignment
    active_doctors = db.session.query(DoctorHospitalAssignment).filter_by(
        hospital_id=tenant.id, is_active=True
    ).count()

    return jsonify({
        "data": {
            "hospital": tenant.to_dict(),
            "subscription_valid": tenant.subscription_status in ["active", "trial"],
            "subscription_expires": tenant.subscription_expires_at.isoformat() if tenant.subscription_expires_at else None,
            "doctor_count": active_doctors,
            "doctor_limit": tenant.max_doctors,
            "can_add_doctor": active_doctors < tenant.max_doctors,
            "subscription_tier": tenant.subscription_tier,
        }
    })