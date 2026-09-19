"""Relational data model for centralized multi-hospital healthcare platform."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class Role(str, Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    DOCTOR = "doctor"
    RECEPTIONIST = "receptionist"
    PATIENT = "patient"


class UserStatus(str, Enum):
    ACTIVE = "active"
    PENDING = "pending"
    SUSPENDED = "suspended"
    INACTIVE = "inactive"
    REJECTED = "rejected"


class AppointmentStatus(str, Enum):
    BOOKED = "booked"
    CONFIRMED = "confirmed"
    CHECKED_IN = "checked_in"
    WAITING = "waiting"
    IN_CONSULTATION = "in_consultation"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    PARTIAL = "partial"
    PAID = "paid"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentMethod(str, Enum):
    CASH = "cash"
    CARD = "card"
    BKASH = "bkash"
    NAGAD = "nagad"
    ONLINE = "online"


class PaymentStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"
    NO_SHOW = "no_show"
    RESCHEDULED = "rescheduled"


class QueueStatus(str, Enum):
    WAITING = "waiting"
    CALLED = "called"
    IN_CONSULTATION = "in_consultation"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"
    # Priority levels
    EMERGENCY = "emergency"
    PRIORITY = "priority"
    STANDARD = "standard"


class PrescriptionStatus(str, Enum):
    DRAFT = "draft"
    FINALIZED = "finalized"
    AMENDED = "amended"


class TimestampMixin:
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class SoftDeleteMixin:
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class User(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, index=True, nullable=False)
    phone = db.Column(db.String(40), unique=True, index=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum(Role), nullable=False, index=True)
    status = db.Column(db.Enum(UserStatus), nullable=False, default=UserStatus.ACTIVE, index=True)
    full_name = db.Column(db.String(160), nullable=False)
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)
    failed_login_count = db.Column(db.Integer, default=0, nullable=False)
    suspended_reason = db.Column(db.String(255), nullable=True)

    patient_profile = db.relationship("Patient", back_populates="user", uselist=False, foreign_keys="Patient.user_id")
    doctor_profile = db.relationship("Doctor", back_populates="user", uselist=False, foreign_keys="Doctor.user_id")
    admin_profile = db.relationship("AdminProfile", back_populates="user", uselist=False, foreign_keys="AdminProfile.user_id")
    receptionist_profile = db.relationship("ReceptionistProfile", back_populates="user", uselist=False, foreign_keys="ReceptionistProfile.user_id")
    # Back-refs for user FKs in other tables
    approved_doctors = db.relationship("Doctor", foreign_keys="Doctor.approved_by_user_id", back_populates="approved_by")
    finalized_prescriptions = db.relationship("Prescription", foreign_keys="Prescription.finalized_by_user_id", back_populates="finalized_by")
    cancelled_appointments = db.relationship("Appointment", foreign_keys="Appointment.cancelled_by_user_id", back_populates="cancelled_by")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def to_public_dict(self):
        return {"id": self.id, "full_name": self.full_name, "email": self.email, "phone": self.phone, "role": self.role.value, "status": self.status.value}


class Hospital(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "hospitals"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(180), unique=True, nullable=False, index=True)
    slug = db.Column(db.String(120), unique=True, nullable=False, index=True)
    logo_url = db.Column(db.String(500), nullable=True)
    address = db.Column(db.String(500), nullable=False)
    phone = db.Column(db.String(60), nullable=False)
    email = db.Column(db.String(255), nullable=True)
    website = db.Column(db.String(255), nullable=True)
    description = db.Column(db.Text, nullable=True)
    emergency_info = db.Column(db.String(500), nullable=True)
    opening_hours = db.Column(db.JSON, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    # Multi-tenant specific fields
    subscription_tier = db.Column(db.String(50), nullable=False, default="free")  # e.g., free, basic, pro, enterprise
    subscription_status = db.Column(db.String(50), nullable=False, default="active")  # active, suspended, expired, cancelled
    subscription_expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    custom_domain = db.Column(db.String(255), unique=True, nullable=True, index=True)
    max_doctors = db.Column(db.Integer, nullable=False, default=5)
    tenant_settings = db.Column(db.JSON, nullable=True)  # custom configuration for this tenant

    branches = db.relationship("HospitalBranch", back_populates="hospital", cascade="all, delete-orphan")
    departments = db.relationship("Department", back_populates="hospital")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "address": self.address,
            "phone": self.phone,
            "email": self.email,
            "website": self.website,
            "description": self.description,
            "emergency_info": self.emergency_info,
            "is_active": self.is_active,
            "subscription_tier": self.subscription_tier,
            "subscription_status": self.subscription_status,
            "custom_domain": self.custom_domain,
            "tenant_settings": self.tenant_settings,
        }


class HospitalBranch(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "hospital_branches"

    id = db.Column(db.Integer, primary_key=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False, index=True)
    name = db.Column(db.String(180), nullable=False)
    address = db.Column(db.String(500), nullable=False)
    phone = db.Column(db.String(60), nullable=True)
    room_prefix = db.Column(db.String(20), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    hospital = db.relationship("Hospital", back_populates="branches")


class Specialty(db.Model, TimestampMixin):
    __tablename__ = "specialties"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "description": self.description, "is_active": self.is_active}


class Department(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "departments"

    id = db.Column(db.Integer, primary_key=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False, index=True)
    specialty_id = db.Column(db.Integer, db.ForeignKey("specialties.id"), nullable=True, index=True)
    name = db.Column(db.String(140), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    hospital = db.relationship("Hospital", back_populates="departments")
    specialty = db.relationship("Specialty")
    __table_args__ = (db.UniqueConstraint("hospital_id", "name", name="uq_department_hospital_name"),)


class AdminProfile(db.Model, TimestampMixin):
    __tablename__ = "admin_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    title = db.Column(db.String(120), nullable=True)
    can_manage_doctors = db.Column(db.Boolean, default=True, nullable=False)
    can_manage_catalogs = db.Column(db.Boolean, default=False, nullable=False)

    user = db.relationship("User", back_populates="admin_profile")
    hospital_assignments = db.relationship("AdminHospitalAssignment", back_populates="admin_profile", cascade="all, delete-orphan")


class AdminHospitalAssignment(db.Model, TimestampMixin):
    __tablename__ = "admin_hospital_assignments"

    id = db.Column(db.Integer, primary_key=True)
    admin_profile_id = db.Column(db.Integer, db.ForeignKey("admin_profiles.id"), nullable=False, index=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    admin_profile = db.relationship("AdminProfile", back_populates="hospital_assignments")
    hospital = db.relationship("Hospital")
    __table_args__ = (db.UniqueConstraint("admin_profile_id", "hospital_id", name="uq_admin_hospital"),)


class Doctor(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "doctors"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    specialty_id = db.Column(db.Integer, db.ForeignKey("specialties.id"), nullable=True, index=True)
    professional_title = db.Column(db.String(80), default="Dr.", nullable=False)
    qualifications = db.Column(db.String(500), nullable=True)
    license_number = db.Column(db.String(120), nullable=False, unique=True)
    experience_years = db.Column(db.Integer, default=0, nullable=False)
    consultation_fee = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    appointment_duration_minutes = db.Column(db.Integer, default=15, nullable=False)
    bio = db.Column(db.Text, nullable=True)
    languages = db.Column(db.String(255), nullable=True)
    verification_status = db.Column(db.Enum(UserStatus), default=UserStatus.PENDING, nullable=False, index=True)
    approved_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    approved_at = db.Column(db.DateTime(timezone=True), nullable=True)

    user = db.relationship("User", foreign_keys=[user_id], back_populates="doctor_profile")
    approved_by = db.relationship("User", foreign_keys=[approved_by_user_id], back_populates="approved_doctors")
    specialty = db.relationship("Specialty")
    hospital_assignments = db.relationship("DoctorHospitalAssignment", back_populates="doctor", cascade="all, delete-orphan")
    department_assignments = db.relationship("DoctorDepartmentAssignment", back_populates="doctor", cascade="all, delete-orphan")
    schedules = db.relationship("DoctorSchedule", back_populates="doctor", cascade="all, delete-orphan")

    def is_bookable(self) -> bool:
        return self.user.status == UserStatus.ACTIVE and self.verification_status == UserStatus.ACTIVE

    def to_dict(self):
        return {"id": self.id, "user_id": self.user_id, "name": self.user.full_name, "title": self.professional_title, "specialty": self.specialty.name if self.specialty else None, "qualifications": self.qualifications, "license_number": self.license_number, "experience_years": self.experience_years, "consultation_fee": float(self.consultation_fee), "appointment_duration_minutes": self.appointment_duration_minutes, "bio": self.bio, "languages": self.languages, "verification_status": self.verification_status.value}


class DoctorHospitalAssignment(db.Model, TimestampMixin):
    __tablename__ = "doctor_hospital_assignments"

    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=False, index=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("hospital_branches.id"), nullable=True)
    room = db.Column(db.String(60), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    doctor = db.relationship("Doctor", back_populates="hospital_assignments")
    hospital = db.relationship("Hospital")
    branch = db.relationship("HospitalBranch")
    __table_args__ = (db.UniqueConstraint("doctor_id", "hospital_id", name="uq_doctor_hospital"),)


class DoctorDepartmentAssignment(db.Model, TimestampMixin):
    __tablename__ = "doctor_department_assignments"

    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    doctor = db.relationship("Doctor", back_populates="department_assignments")
    department = db.relationship("Department")
    __table_args__ = (db.UniqueConstraint("doctor_id", "department_id", name="uq_doctor_department"),)


class ReceptionistProfile(db.Model, TimestampMixin):
    __tablename__ = "receptionist_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    employee_code = db.Column(db.String(80), nullable=True)

    user = db.relationship("User", back_populates="receptionist_profile")
    hospital_assignments = db.relationship("ReceptionistHospitalAssignment", back_populates="receptionist_profile", cascade="all, delete-orphan")


class ReceptionistHospitalAssignment(db.Model, TimestampMixin):
    __tablename__ = "receptionist_hospital_assignments"

    id = db.Column(db.Integer, primary_key=True)
    receptionist_profile_id = db.Column(db.Integer, db.ForeignKey("receptionist_profiles.id"), nullable=False, index=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("hospital_branches.id"), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    receptionist_profile = db.relationship("ReceptionistProfile", back_populates="hospital_assignments")
    hospital = db.relationship("Hospital")
    branch = db.relationship("HospitalBranch")
    __table_args__ = (db.UniqueConstraint("receptionist_profile_id", "hospital_id", name="uq_receptionist_hospital"),)


class Patient(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "patients"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    patient_code = db.Column(db.String(40), unique=True, nullable=False, index=True)
    qr_code = db.Column(db.String(100), unique=True, nullable=True, index=True)
    date_of_birth = db.Column(db.Date, nullable=True)
    gender = db.Column(db.String(40), nullable=True)
    address = db.Column(db.String(500), nullable=True)
    emergency_contact_name = db.Column(db.String(160), nullable=True)
    emergency_contact_phone = db.Column(db.String(40), nullable=True)
    blood_group = db.Column(db.String(10), nullable=True)
    basic_health_info = db.Column(db.Text, nullable=True)
    profile_photo_url = db.Column(db.String(500), nullable=True)

    user = db.relationship("User", back_populates="patient_profile")

    def to_dict(self):
        return {"id": self.id, "patient_code": self.patient_code, "name": self.user.full_name, "email": self.user.email, "phone": self.user.phone, "date_of_birth": self.date_of_birth.isoformat() if self.date_of_birth else None, "gender": self.gender, "address": self.address, "emergency_contact_name": self.emergency_contact_name, "emergency_contact_phone": self.emergency_contact_phone, "blood_group": self.blood_group, "basic_health_info": self.basic_health_info}


class DoctorSchedule(db.Model, TimestampMixin):
    __tablename__ = "doctor_schedules"

    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=False, index=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=True, index=True)
    weekday = db.Column(db.Integer, nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    break_start = db.Column(db.Time, nullable=True)
    break_end = db.Column(db.Time, nullable=True)
    appointment_duration_minutes = db.Column(db.Integer, default=15, nullable=False)
    max_appointments = db.Column(db.Integer, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    doctor = db.relationship("Doctor", back_populates="schedules")
    hospital = db.relationship("Hospital")
    department = db.relationship("Department")
    __table_args__ = (db.CheckConstraint("weekday >= 0 AND weekday <= 6", name="weekday_range"),)


class DoctorScheduleOverride(db.Model, TimestampMixin):
    __tablename__ = "doctor_schedule_overrides"

    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=False, index=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    is_available = db.Column(db.Boolean, default=False, nullable=False)
    start_time = db.Column(db.Time, nullable=True)
    end_time = db.Column(db.Time, nullable=True)
    reason = db.Column(db.String(255), nullable=True)
    __table_args__ = (db.UniqueConstraint("doctor_id", "hospital_id", "date", name="uq_schedule_override"),)


class Appointment(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "appointments"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=False, index=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=True, index=True)
    scheduled_start = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    scheduled_end = db.Column(db.DateTime(timezone=True), nullable=False)
    actual_start_time = db.Column(db.DateTime(timezone=True), nullable=True)  # When patient actually checked in
    actual_end_time = db.Column(db.DateTime(timezone=True), nullable=True)  # When consultation ended
    appointment_type = db.Column(db.String(40), default="in_person", nullable=False)
    status = db.Column(db.Enum(AppointmentStatus), default=AppointmentStatus.BOOKED, nullable=False, index=True)
    reason = db.Column(db.String(500), nullable=True)
    cancelled_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    cancellation_reason = db.Column(db.String(500), nullable=True)
    rescheduled_from_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), nullable=True)

    patient = db.relationship("Patient")
    doctor = db.relationship("Doctor")
    hospital = db.relationship("Hospital")
    department = db.relationship("Department")
    cancelled_by = db.relationship("User", foreign_keys=[cancelled_by_user_id], back_populates="cancelled_appointments")
    __table_args__ = (db.UniqueConstraint("doctor_id", "hospital_id", "scheduled_start", name="uq_doctor_hospital_slot"), db.Index("ix_appointments_patient_status", "patient_id", "status"))

    def to_dict(self):
        return {"id": self.id, "patient_id": self.patient_id, "patient_name": self.patient.user.full_name, "doctor_id": self.doctor_id, "doctor_name": self.doctor.user.full_name, "hospital_id": self.hospital_id, "hospital_name": self.hospital.name, "department_id": self.department_id, "scheduled_start": self.scheduled_start.isoformat(), "scheduled_end": self.scheduled_end.isoformat(), "appointment_type": self.appointment_type, "status": self.status.value, "reason": self.reason}


class Queue(db.Model, TimestampMixin):
    __tablename__ = "queues"

    id = db.Column(db.Integer, primary_key=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=True, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=True, index=True)
    queue_date = db.Column(db.Date, nullable=False, index=True)
    prefix = db.Column(db.String(8), default="A", nullable=False)
    current_token_id = db.Column(db.Integer, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    hospital = db.relationship("Hospital")
    doctor = db.relationship("Doctor")
    department = db.relationship("Department")
    tokens = db.relationship("QueueToken", back_populates="queue", order_by="QueueToken.position")
    __table_args__ = (db.UniqueConstraint("hospital_id", "doctor_id", "queue_date", name="uq_queue_hospital_doctor_date"),)


class QueueToken(db.Model, TimestampMixin):
    __tablename__ = "queue_tokens"

    id = db.Column(db.Integer, primary_key=True)
    queue_id = db.Column(db.Integer, db.ForeignKey("queues.id"), nullable=False, index=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), nullable=False, unique=True)
    token_number = db.Column(db.String(20), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False)
    status = db.Column(db.Enum(QueueStatus), default=QueueStatus.WAITING, nullable=False, index=True)
    priority_level = db.Column(db.Integer, default=3, nullable=False)  # 1=emergency, 2=priority, 3=standard
    called_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    checked_in_at = db.Column(db.DateTime(timezone=True), nullable=True)

    queue = db.relationship("Queue", back_populates="tokens")
    appointment = db.relationship("Appointment")
    __table_args__ = (db.UniqueConstraint("queue_id", "token_number", name="uq_queue_token_number"),)

    def to_dict(self):
        return {"id": self.id, "queue_id": self.queue_id, "appointment_id": self.appointment_id, "token_number": self.token_number, "position": self.position, "status": self.status.value, "priority_level": self.priority_level, "patient_id": self.appointment.patient_id, "doctor_id": self.appointment.doctor_id, "hospital_id": self.appointment.hospital_id, "checked_in_at": self.checked_in_at.isoformat() if self.checked_in_at else None}


class Consultation(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "consultations"

    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), unique=True, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=False, index=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False, index=True)
    symptoms = db.Column(db.Text, nullable=True)
    observations = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    advice = db.Column(db.Text, nullable=True)
    follow_up_date = db.Column(db.Date, nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    appointment = db.relationship("Appointment")
    patient = db.relationship("Patient")
    doctor = db.relationship("Doctor")
    hospital = db.relationship("Hospital")


class Diagnosis(db.Model, TimestampMixin):
    __tablename__ = "diagnoses"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(180), unique=True, nullable=False, index=True)
    code = db.Column(db.String(60), nullable=True, index=True)
    category = db.Column(db.String(120), nullable=True)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)


class ConsultationDiagnosis(db.Model, TimestampMixin):
    __tablename__ = "consultation_diagnoses"

    id = db.Column(db.Integer, primary_key=True)
    consultation_id = db.Column(db.Integer, db.ForeignKey("consultations.id"), nullable=False, index=True)
    diagnosis_id = db.Column(db.Integer, db.ForeignKey("diagnoses.id"), nullable=True)
    diagnosis_name_snapshot = db.Column(db.String(180), nullable=False)
    notes = db.Column(db.String(500), nullable=True)

    consultation = db.relationship("Consultation")
    diagnosis = db.relationship("Diagnosis")


class MedicineCategory(db.Model, TimestampMixin):
    __tablename__ = "medicine_categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)


class Medicine(db.Model, TimestampMixin):
    __tablename__ = "medicines"

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("medicine_categories.id"), nullable=True)
    generic_name = db.Column(db.String(180), nullable=False, index=True)
    brand_name = db.Column(db.String(180), nullable=True, index=True)
    strength = db.Column(db.String(80), nullable=True)
    dosage_form = db.Column(db.String(80), nullable=True)
    manufacturer = db.Column(db.String(160), nullable=True)
    unit = db.Column(db.String(40), nullable=True)
    default_instructions = db.Column(db.String(500), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    category = db.relationship("MedicineCategory")


class MedicalTest(db.Model, TimestampMixin):
    __tablename__ = "medical_tests"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(180), unique=True, nullable=False, index=True)
    category = db.Column(db.String(120), nullable=True)
    description = db.Column(db.Text, nullable=True)
    preparation_instructions = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)


class Prescription(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "prescriptions"

    id = db.Column(db.Integer, primary_key=True)
    prescription_code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    consultation_id = db.Column(db.Integer, db.ForeignKey("consultations.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=False, index=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False, index=True)
    status = db.Column(db.Enum(PrescriptionStatus), default=PrescriptionStatus.DRAFT, nullable=False, index=True)
    diagnosis_summary = db.Column(db.Text, nullable=True)
    advice = db.Column(db.Text, nullable=True)
    follow_up_date = db.Column(db.Date, nullable=True)
    finalized_at = db.Column(db.DateTime(timezone=True), nullable=True)
    finalized_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    amendment_of_id = db.Column(db.Integer, db.ForeignKey("prescriptions.id"), nullable=True)

    consultation = db.relationship("Consultation")
    patient = db.relationship("Patient")
    doctor = db.relationship("Doctor")
    hospital = db.relationship("Hospital")
    finalized_by = db.relationship("User", foreign_keys=[finalized_by_user_id], back_populates="finalized_prescriptions")
    items = db.relationship("PrescriptionItem", back_populates="prescription", cascade="all, delete-orphan")
    tests = db.relationship("TestOrder", back_populates="prescription", cascade="all, delete-orphan")

    def to_dict(self):
        return {"id": self.id, "prescription_code": self.prescription_code, "consultation_id": self.consultation_id, "patient_id": self.patient_id, "patient_name": self.patient.user.full_name, "doctor_id": self.doctor_id, "doctor_name": self.doctor.user.full_name, "hospital_id": self.hospital_id, "hospital_name": self.hospital.name, "status": self.status.value, "diagnosis_summary": self.diagnosis_summary, "advice": self.advice, "follow_up_date": self.follow_up_date.isoformat() if self.follow_up_date else None, "finalized_at": self.finalized_at.isoformat() if self.finalized_at else None, "items": [i.to_dict() for i in self.items], "tests": [t.to_dict() for t in self.tests]}


class PrescriptionItem(db.Model, TimestampMixin):
    __tablename__ = "prescription_items"

    id = db.Column(db.Integer, primary_key=True)
    prescription_id = db.Column(db.Integer, db.ForeignKey("prescriptions.id"), nullable=False, index=True)
    medicine_id = db.Column(db.Integer, db.ForeignKey("medicines.id"), nullable=True)
    medicine_name_snapshot = db.Column(db.String(240), nullable=False)
    strength_snapshot = db.Column(db.String(80), nullable=True)
    dosage = db.Column(db.String(120), nullable=False)
    frequency = db.Column(db.String(120), nullable=False)
    route = db.Column(db.String(80), nullable=True)
    duration = db.Column(db.String(120), nullable=False)
    quantity = db.Column(db.String(80), nullable=True)
    timing = db.Column(db.String(120), nullable=True)
    meal_instruction = db.Column(db.String(120), nullable=True)
    instructions = db.Column(db.String(500), nullable=True)

    prescription = db.relationship("Prescription", back_populates="items")
    medicine = db.relationship("Medicine")

    def to_dict(self):
        return {"id": self.id, "medicine_id": self.medicine_id, "medicine_name": self.medicine_name_snapshot, "strength": self.strength_snapshot, "dosage": self.dosage, "frequency": self.frequency, "route": self.route, "duration": self.duration, "quantity": self.quantity, "timing": self.timing, "meal_instruction": self.meal_instruction, "instructions": self.instructions}


class TestOrder(db.Model, TimestampMixin):
    __tablename__ = "test_orders"

    id = db.Column(db.Integer, primary_key=True)
    prescription_id = db.Column(db.Integer, db.ForeignKey("prescriptions.id"), nullable=False, index=True)
    medical_test_id = db.Column(db.Integer, db.ForeignKey("medical_tests.id"), nullable=True)
    test_name_snapshot = db.Column(db.String(180), nullable=False)
    instructions = db.Column(db.String(500), nullable=True)
    status = db.Column(db.String(40), default="requested", nullable=False)

    prescription = db.relationship("Prescription", back_populates="tests")
    medical_test = db.relationship("MedicalTest")

    def to_dict(self):
        return {"id": self.id, "medical_test_id": self.medical_test_id, "test_name": self.test_name_snapshot, "instructions": self.instructions, "status": self.status}


class MedicalRecord(db.Model, TimestampMixin):
    __tablename__ = "medical_records"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    consultation_id = db.Column(db.Integer, db.ForeignKey("consultations.id"), nullable=True)
    record_type = db.Column(db.String(80), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    summary = db.Column(db.Text, nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)


class LabReport(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "lab_reports"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    test_order_id = db.Column(db.Integer, db.ForeignKey("test_orders.id"), nullable=True, index=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=True, index=True)
    report_title = db.Column(db.String(200), nullable=False)
    test_name = db.Column(db.String(180), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_name = db.Column(db.String(255), nullable=False)
    file_size_bytes = db.Column(db.Integer, nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    uploaded_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    patient = db.relationship("Patient")
    test_order = db.relationship("TestOrder")
    hospital = db.relationship("Hospital")
    uploaded_by = db.relationship("User", foreign_keys=[uploaded_by_user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "test_order_id": self.test_order_id,
            "hospital_id": self.hospital_id,
            "hospital_name": self.hospital.name if self.hospital else None,
            "report_title": self.report_title,
            "test_name": self.test_name,
            "file_name": self.file_name,
            "file_size_bytes": self.file_size_bytes,
            "mime_type": self.mime_type,
            "notes": self.notes,
            "uploaded_at": self.created_at.isoformat() if self.created_at else None,
            "download_url": f"/api/lab-reports/{self.id}/download"
        }


class Notification(db.Model, TimestampMixin):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    event_type = db.Column(db.String(80), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    body = db.Column(db.String(800), nullable=False)
    data = db.Column(db.JSON, nullable=True)
    read_at = db.Column(db.DateTime(timezone=True), nullable=True)

    user = db.relationship("User")


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    role = db.Column(db.String(40), nullable=True, index=True)
    action = db.Column(db.String(120), nullable=False, index=True)
    entity = db.Column(db.String(120), nullable=False, index=True)
    entity_id = db.Column(db.String(80), nullable=True, index=True)
    ip_address = db.Column(db.String(80), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    before = db.Column(db.JSON, nullable=True)
    after = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)


class PlatformSetting(db.Model, TimestampMixin):
    __tablename__ = "platform_settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(120), unique=True, nullable=False)
    value = db.Column(db.JSON, nullable=True)
    description = db.Column(db.String(500), nullable=True)


class BackupStatus(str, Enum):
    """Status of a backup operation."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    RESTORED = "restored"


class BackupType(str, Enum):
    """Types of backups."""
    FULL = "full"
    DATABASE_ONLY = "database_only"
    FILES_ONLY = "files_only"
    INCREMENTAL = "incremental"


class BackupLog(db.Model, TimestampMixin):
    """Tracks backup operations for audit and recovery purposes."""
    __tablename__ = "backup_logs"

    id = db.Column(db.Integer, primary_key=True)
    backup_id = db.Column(db.String(80), unique=True, nullable=False, index=True)
    backup_type = db.Column(db.Enum(BackupType), nullable=False, default=BackupType.FULL)
    status = db.Column(db.Enum(BackupStatus), nullable=False, default=BackupStatus.PENDING, index=True)

    # File details
    file_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size_bytes = db.Column(db.BigInteger, nullable=True)
    checksum = db.Column(db.String(128), nullable=True)  # SHA-256 checksum

    # Metadata
    database_name = db.Column(db.String(120), nullable=True)
    tables_included = db.Column(db.JSON, nullable=True)  # List of tables backed up
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=True)  # NULL = platform-wide

    # Timing
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=True)

    # Restore info
    restored_at = db.Column(db.DateTime(timezone=True), nullable=True)
    restored_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    # Audit
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    # Relationships
    hospital = db.relationship("Hospital")
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])
    restored_by = db.relationship("User", foreign_keys=[restored_by_user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "backup_id": self.backup_id,
            "backup_type": self.backup_type.value,
            "status": self.status.value,
            "file_name": self.file_name,
            "file_path": self.file_path,
            "file_size_bytes": self.file_size_bytes,
            "file_size_mb": round(self.file_size_bytes / (1024 * 1024), 2) if self.file_size_bytes else None,
            "checksum": self.checksum,
            "database_name": self.database_name,
            "tables_included": self.tables_included,
            "hospital_id": self.hospital_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "restored_at": self.restored_at.isoformat() if self.restored_at else None,
            "notes": self.notes,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# VideoSession is kept in a separate module to avoid making the core model file
# harder to maintain. Importing here exposes it to SQLAlchemy metadata discovery.
from .video import VideoSession, VideoProvider


class Invoice(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "invoices"

    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(80), unique=True, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False, index=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), nullable=True, index=True)

    total_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    discount_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    tax_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    payable_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    paid_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    due_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)

    status = db.Column(db.String(40), nullable=False, default=InvoiceStatus.PENDING.value, index=True)
    due_date = db.Column(db.DateTime(timezone=True), nullable=True)
    paid_at = db.Column(db.DateTime(timezone=True), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    patient = db.relationship("Patient")
    hospital = db.relationship("Hospital")
    appointment = db.relationship("Appointment", backref="invoice")
    items = db.relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")
    payments = db.relationship("Payment", back_populates="invoice", cascade="all, delete-orphan")
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "invoice_number": self.invoice_number,
            "patient_id": self.patient_id,
            "patient_name": self.patient.full_name if self.patient else None,
            "hospital_id": self.hospital_id,
            "appointment_id": self.appointment_id,
            "total_amount": float(self.total_amount),
            "discount_amount": float(self.discount_amount),
            "tax_amount": float(self.tax_amount),
            "payable_amount": float(self.payable_amount),
            "paid_amount": float(self.paid_amount),
            "due_amount": float(self.due_amount),
            "status": self.status,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "notes": self.notes
        }


class InvoiceItem(db.Model):
    __tablename__ = "invoice_items"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False, index=True)
    item_type = db.Column(db.String(80), nullable=False)  # consultation, lab_test, medication, procedure, other
    description = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    total_price = db.Column(db.Numeric(10, 2), nullable=False, default=0)

    related_id = db.Column(db.Integer, nullable=True)  # ID of the test/medication/consultation etc.

    invoice = db.relationship("Invoice", back_populates="items")

    def to_dict(self):
        return {
            "id": self.id,
            "invoice_id": self.invoice_id,
            "item_type": self.item_type,
            "description": self.description,
            "quantity": self.quantity,
            "unit_price": float(self.unit_price),
            "total_price": float(self.total_price),
            "related_id": self.related_id
        }


class Payment(db.Model, TimestampMixin):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    payment_number = db.Column(db.String(80), unique=True, nullable=False, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False, index=True)

    amount = db.Column(db.Numeric(10, 2), nullable=False)
    payment_method = db.Column(db.String(40), nullable=False, default=PaymentMethod.CASH.value)
    transaction_id = db.Column(db.String(120), nullable=True)
    status = db.Column(db.String(40), nullable=False, default=PaymentStatus.COMPLETED.value)
    payment_date = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    notes = db.Column(db.String(500), nullable=True)

    received_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    invoice = db.relationship("Invoice", back_populates="payments")
    patient = db.relationship("Patient")
    hospital = db.relationship("Hospital")
    received_by = db.relationship("User", foreign_keys=[received_by_user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "payment_number": self.payment_number,
            "invoice_id": self.invoice_id,
            "patient_id": self.patient_id,
            "hospital_id": self.hospital_id,
            "amount": float(self.amount),
            "payment_method": self.payment_method,
            "transaction_id": self.transaction_id,
            "status": self.status,
            "payment_date": self.payment_date.isoformat() if self.payment_date else None,
            "notes": self.notes
        }


class SymptomRule(db.Model, TimestampMixin):
    __tablename__ = "symptom_rules"

    id = db.Column(db.Integer, primary_key=True)
    keyword = db.Column(db.String(120), nullable=False, index=True)
    specialty_id = db.Column(db.Integer, db.ForeignKey("specialties.id"), nullable=True)
    emergency = db.Column(db.Boolean, default=False, nullable=False)
    message = db.Column(db.String(500), nullable=True)

    specialty = db.relationship("Specialty")


class ConsentType(str, Enum):
    """Types of consent that can be collected from patients."""
    TREATMENT = "treatment"
    DATA_SHARING = "data_sharing"
    RESEARCH = "research"
    MARKETING = "marketing"
    EMERGENCY_TREATMENT = "emergency_treatment"
    TELEHEALTH = "telehealth"


class ConsentStatus(str, Enum):
    """Status of a patient's consent."""
    PENDING = "pending"
    GRANTED = "granted"
    DENIED = "denied"
    REVOKED = "revoked"
    EXPIRED = "expired"


class PatientConsent(db.Model, TimestampMixin):
    """Tracks patient consent for various purposes (HIPAA, treatment, data sharing, etc.)."""
    __tablename__ = "patient_consents"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False, index=True)

    consent_type = db.Column(db.Enum(ConsentType), nullable=False, index=True)
    status = db.Column(db.Enum(ConsentStatus), nullable=False, default=ConsentStatus.PENDING, index=True)

    # Consent details
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    version = db.Column(db.String(20), nullable=False, default="1.0")

    # Tracking
    granted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    denied_at = db.Column(db.DateTime(timezone=True), nullable=True)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Audit
    ip_address = db.Column(db.String(80), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    signature_data = db.Column(db.Text, nullable=True)  # Base64 encoded signature image
    notes = db.Column(db.Text, nullable=True)

    # Relationships
    patient = db.relationship("Patient", backref="consents")
    hospital = db.relationship("Hospital")

    def is_valid(self) -> bool:
        """Check if consent is currently valid (granted and not expired/revoked)."""
        if self.status != ConsentStatus.GRANTED:
            return False
        if self.expires_at and self.expires_at < utcnow():
            return False
        return True

    def to_dict(self):
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "hospital_id": self.hospital_id,
            "consent_type": self.consent_type.value,
            "status": self.status.value,
            "title": self.title,
            "description": self.description,
            "version": self.version,
            "granted_at": self.granted_at.isoformat() if self.granted_at else None,
            "denied_at": self.denied_at.isoformat() if self.denied_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "ip_address": self.ip_address,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class DevicePlatform(str, Enum):
    """Supported mobile platforms."""
    IOS = "ios"
    ANDROID = "android"
    WEB = "web"


class DeviceToken(db.Model, TimestampMixin):
    """Stores device tokens for push notifications."""
    __tablename__ = "device_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=True, index=True)

    token = db.Column(db.String(500), nullable=False, unique=True, index=True)
    platform = db.Column(db.Enum(DevicePlatform), nullable=False, index=True)
    device_name = db.Column(db.String(200), nullable=True)
    device_model = db.Column(db.String(100), nullable=True)
    app_version = db.Column(db.String(50), nullable=True)

    # Status
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    last_used_at = db.Column(db.DateTime(timezone=True), nullable=True)
    deactivated_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Notification preferences
    push_enabled = db.Column(db.Boolean, default=True, nullable=False)
    quiet_hours_start = db.Column(db.Time, nullable=True)
    quiet_hours_end = db.Column(db.Time, nullable=True)

    # Relationships
    user = db.relationship("User", backref="device_tokens")
    hospital = db.relationship("Hospital")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "hospital_id": self.hospital_id,
            "platform": self.platform.value,
            "device_name": self.device_name,
            "device_model": self.device_model,
            "app_version": self.app_version,
            "is_active": self.is_active,
            "push_enabled": self.push_enabled,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class PushNotificationLog(db.Model, TimestampMixin):
    """Logs push notification delivery for audit and analytics."""
    __tablename__ = "push_notification_logs"

    id = db.Column(db.Integer, primary_key=True)
    device_token_id = db.Column(db.Integer, db.ForeignKey("device_tokens.id"), nullable=False, index=True)
    notification_id = db.Column(db.Integer, db.ForeignKey("notifications.id"), nullable=True, index=True)

    # Content
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.String(1000), nullable=False)
    data = db.Column(db.JSON, nullable=True)

    # Delivery status
    status = db.Column(db.String(40), nullable=False, default="pending", index=True)  # pending, sent, delivered, failed
    sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    delivered_at = db.Column(db.DateTime(timezone=True), nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    # Provider response
    provider_message_id = db.Column(db.String(200), nullable=True)
    provider_response = db.Column(db.JSON, nullable=True)

    # Relationships
    device_token = db.relationship("DeviceToken")
    notification = db.relationship("Notification")

    def to_dict(self):
        return {
            "id": self.id,
            "device_token_id": self.device_token_id,
            "notification_id": self.notification_id,
            "title": self.title,
            "body": self.body,
            "data": self.data,
            "status": self.status,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Favorite(db.Model, TimestampMixin):
    """Tracks doctors that patients have favorited."""
    __tablename__ = "favorites"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=False, index=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=True, index=True)

    # Relationships
    patient = db.relationship("Patient", backref="favorites")
    doctor = db.relationship("Doctor", backref="favorited_by")
    hospital = db.relationship("Hospital", backref="favorites")

    # Unique constraint to prevent duplicate favorites
    __table_args__ = (
        db.UniqueConstraint("patient_id", "doctor_id", name="uq_favorite_patient_doctor"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "doctor_id": self.doctor_id,
            "hospital_id": self.hospital_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Review(db.Model, TimestampMixin):
    """Doctor reviews and ratings from patients."""
    __tablename__ = "reviews"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=False, index=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=True, index=True)

    # Rating (1-5 scale)
    rating = db.Column(db.Integer, nullable=False)

    # Review content
    title = db.Column(db.String(200), nullable=True)
    description = db.Column(db.Text, nullable=True)

    # Verification
    verified = db.Column(db.Boolean, default=False, nullable=False, index=True)
    consultation_id = db.Column(db.Integer, db.ForeignKey("consultations.id"), nullable=True)

    # Relationships
    patient = db.relationship("Patient", backref="reviews")
    doctor = db.relationship("Doctor", backref="reviews")
    hospital = db.relationship("Hospital", backref="reviews")
    consultation = db.relationship("Consultation")

    # Unique constraint to prevent duplicate reviews
    __table_args__ = (
        db.UniqueConstraint("patient_id", "doctor_id", name="uq_review_patient_doctor"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "doctor_id": self.doctor_id,
            "rating": self.rating,
            "title": self.title,
            "description": self.description,
            "verified": self.verified,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }