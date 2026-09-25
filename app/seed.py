from __future__ import annotations

from datetime import datetime, timezone, time, date, timedelta

from app import create_app
from app.extensions import db
from app.models import (
    AdminHospitalAssignment,
    AdminProfile,
    Doctor,
    DoctorHospitalAssignment,
    DoctorSchedule,
    Hospital,
    Medicine,
    MedicineCategory,
    Patient,
    PharmacistHospitalAssignment,
    PharmacistProfile,
    ReceptionistHospitalAssignment,
    ReceptionistProfile,
    Specialty,
    User,
    Role,
    UserStatus,
)


def seed():
    app = create_app("development")
    with app.app_context():
        db.create_all()

        # Specialties
        specialty_data = [
            ("Cardiology", "Heart conditions"),
            ("Neurology", "Brain and nervous system"),
            ("Dermatology", "Skin conditions"),
            ("Pediatrics", "Children's health"),
            ("Orthopedics", "Bones and joints"),
            ("Ophthalmology", "Eye care"),
            ("ENT", "Ear, nose, throat"),
            ("Gynecology", "Women's health"),
            ("Psychiatry", "Mental health"),
            ("General Medicine", "General practice"),
            ("Dentistry", "Dental care"),
            ("Urology", "Urinary system"),
            ("Gastroenterology", "Digestive system"),
            ("Pulmonology", "Lungs and breathing"),
            ("Endocrinology", "Hormonal disorders"),
        ]
        specials = []
        for name, desc in specialty_data:
            if not Specialty.query.filter_by(name=name).first():
                s = Specialty(name=name, description=desc)
                db.session.add(s)
                specials.append(s)
        db.session.flush()
        specialty_map = {s.name: s for s in Specialty.query.all()}

        # Hospitals
        hospitals = [
            ("Dhaka General Hospital", "dhaka-general", "123 Medical Road, Dhaka", "+880-2-1111111"),
            ("Chittagong Heart Center", "chittagong-heart", "456 Cardiac Lane, Chittagong", "+880-3-2222222"),
            ("Sylhet Women's Hospital", "sylhet-womens", "789 Health Avenue, Sylhet", "+880-4-3333333"),
        ]
        for name, slug, addr, phone in hospitals:
            if not Hospital.query.filter_by(slug=slug).first():
                db.session.add(Hospital(name=name, slug=slug, address=addr, phone=phone))
        db.session.flush()
        hospital_map = {h.slug: h for h in Hospital.query.all()}

        # Super admin
        if not User.query.filter_by(email="superadmin@nirog.test").first():
            admin_user = User(
                full_name="Super Admin",
                email="superadmin@nirog.test",
                role=Role.SUPER_ADMIN,
                status=UserStatus.ACTIVE,
            )
            admin_user.set_password("NirogAdmin@123")
            db.session.add(admin_user)
        db.session.flush()

        # Hospital Admin
        if not User.query.filter_by(email="admin@dhaka.test").first():
            hosp_admin = User(
                full_name="Dhaka Admin",
                email="admin@dhaka.test",
                role=Role.ADMIN,
                status=UserStatus.ACTIVE,
            )
            hosp_admin.set_password("Admin@123")
            db.session.add(hosp_admin)
            db.session.flush()
            adm_prof = AdminProfile(user_id=hosp_admin.id, title="Hospital Admin")
            db.session.add(adm_prof)
            db.session.flush()
            dhaka_hosp = hospital_map.get("dhaka-general")
            if dhaka_hosp:
                db.session.add(AdminHospitalAssignment(admin_profile_id=adm_prof.id, hospital_id=dhaka_hosp.id, is_active=True))

        # Receptionist
        if not User.query.filter_by(email="receptionist@dhaka.test").first():
            rec_user = User(
                full_name="Dhaka Receptionist",
                email="receptionist@dhaka.test",
                role=Role.RECEPTIONIST,
                status=UserStatus.ACTIVE,
            )
            rec_user.set_password("Reception@123")
            db.session.add(rec_user)
            db.session.flush()
            rec_prof = ReceptionistProfile(user_id=rec_user.id, employee_code="REC-001")
            db.session.add(rec_prof)
            db.session.flush()
            dhaka_hosp = hospital_map.get("dhaka-general")
            if dhaka_hosp:
                db.session.add(ReceptionistHospitalAssignment(receptionist_profile_id=rec_prof.id, hospital_id=dhaka_hosp.id, is_active=True))

        # Pharmacist
        if not User.query.filter_by(email="pharmacist@dhaka.test").first():
            pharm_user = User(
                full_name="Dhaka Pharmacist",
                email="pharmacist@dhaka.test",
                role=Role.PHARMACIST,
                status=UserStatus.ACTIVE,
            )
            pharm_user.set_password("Pharmacist@123")
            db.session.add(pharm_user)
            db.session.flush()
            pharm_prof = PharmacistProfile(user_id=pharm_user.id, employee_code="PHARM-001", license_number="PHARM-LIC-001")
            db.session.add(pharm_prof)
            db.session.flush()
            dhaka_hosp = hospital_map.get("dhaka-general")
            if dhaka_hosp:
                db.session.add(PharmacistHospitalAssignment(pharmacist_profile_id=pharm_prof.id, hospital_id=dhaka_hosp.id, is_active=True))

        # Patients
        patients = []
        for i in range(1, 6):
            key = f"patient{i}@nirog.test"
            p = User.query.filter_by(email=key).first()
            if not p:
                p = User(full_name=f"Patient {i}", email=key, role=Role.PATIENT, status=UserStatus.ACTIVE)
                p.set_password("Patient@123")
                db.session.add(p)
            db.session.flush()
            if not Patient.query.filter_by(user_id=p.id).first():
                pat = Patient(
                    user_id=p.id,
                    patient_code=f"P{p.id:06d}",
                    date_of_birth=datetime(1980 + i, 1, 1).date(),
                    gender="Other",
                    blood_group="A+",
                )
                db.session.add(pat)
                patients.append(pat)

        # Doctors
        doctor_data = [
            ("Dr. Rahman", "cardiology@nirog.test", "LICENSE-001", specialty_map["Cardiology"], hospital_map["dhaka-general"], 15, 500),
            ("Dr. Karim", "neurology@nirog.test", "LICENSE-002", specialty_map["Neurology"], hospital_map["chittagong-heart"], 20, 600),
            ("Dr. Akter", "dermatology@nirog.test", "LICENSE-003", specialty_map["Dermatology"], hospital_map["sylhet-womens"], 10, 300),
        ]
        for name, email, lic, spec, hosp, exp, fee in doctor_data:
            doc = Doctor.query.join(Doctor.user).filter(User.email == email).first()
            if not doc:
                user = User(full_name=name, email=email, role=Role.DOCTOR, status=UserStatus.ACTIVE)
                user.set_password("Doctor@123")
                db.session.add(user)
                db.session.flush()
                doc = Doctor(
                    user_id=user.id,
                    specialty_id=spec.id,
                    license_number=lic,
                    experience_years=exp,
                    consultation_fee=fee,
                    verification_status=UserStatus.ACTIVE,
                )
                db.session.add(doc)
                db.session.flush()
            else:
                doc.user.status = UserStatus.ACTIVE
                doc.verification_status = UserStatus.ACTIVE

            if not DoctorHospitalAssignment.query.filter_by(doctor_id=doc.id, hospital_id=hosp.id).first():
                db.session.add(DoctorHospitalAssignment(doctor_id=doc.id, hospital_id=hosp.id, is_active=True))

            # Add missing default schedules (Mon-Fri, 9am-5pm, lunch 1-2pm).
            for weekday in range(0, 5):
                if not DoctorSchedule.query.filter_by(doctor_id=doc.id, hospital_id=hosp.id, weekday=weekday).first():
                    db.session.add(DoctorSchedule(
                        doctor_id=doc.id,
                        hospital_id=hosp.id,
                        weekday=weekday,
                        start_time=time(9, 0),
                        end_time=time(17, 0),
                        break_start=time(13, 0),
                        break_end=time(14, 0),
                        appointment_duration_minutes=15,
                        max_appointments=32,
                        is_active=True,
                    ))

        # Medicines
        # Create categories first
        categories = {
            "Analgesics": "Pain relief medications",
            "Antibiotics": "Antibacterial medications",
            "Antidiabetics": "Diabetes medications",
            "Gastrointestinal": "Digestive system medications",
        }
        cat_map = {}
        for name, desc in categories.items():
            cat = MedicineCategory.query.filter_by(name=name).first()
            if not cat:
                cat = MedicineCategory(name=name, description=desc)
                db.session.add(cat)
            db.session.flush()
            cat_map[name] = cat

        medicines = [
            ("Paracetamol", "500 mg", "Tablet", "Analgesics", 2.50, 1.20, 5.0, False, False),
            ("Ibuprofen", "400 mg", "Tablet", "Analgesics", 3.00, 1.50, 5.0, False, False),
            ("Amoxicillin", "500 mg", "Capsule", "Antibiotics", 12.00, 6.00, 5.0, True, False),
            ("Metformin", "850 mg", "Tablet", "Antidiabetics", 8.00, 4.00, 5.0, True, False),
            ("Omeprazole", "20 mg", "Capsule", "Gastrointestinal", 5.00, 2.50, 5.0, True, False),
        ]
        for generic, strength, form, cat_name, unit_price, purchase_price, tax_pct, rx_only, controlled in medicines:
            if not Medicine.query.filter_by(generic_name=generic).first():
                db.session.add(Medicine(
                    generic_name=generic,
                    brand_name=generic,
                    strength=strength,
                    dosage_form=form,
                    category_id=cat_map[cat_name].id,
                    unit_price=unit_price,
                    purchase_price=purchase_price,
                    tax_percentage=tax_pct,
                    is_prescription_only=rx_only,
                    controlled_substance=controlled,
                    is_active=True,
                ))

        db.session.commit()
        print("Seed complete")


if __name__ == "__main__":
    seed()