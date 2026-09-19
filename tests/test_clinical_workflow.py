import pytest
from datetime import datetime, timedelta, timezone
from app import create_app
from app.extensions import db
from app.models import (
    User, UserRole, UserStatus, Hospital, Department, Specialty, Doctor,
    DoctorSchedule, Patient, Appointment, AppointmentStatus, Consultation,
    Prescription, PrescriptionStatus, Medicine, MedicalTest, utcnow
)

@pytest.fixture
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def seed_data(app):
    with app.app_context():
        hospital = Hospital(
            name="Dhaka Central Hospital",
            code="DCH-01",
            address="Dhanmondi, Dhaka",
            phone="+8801700000001",
            email="info@dhakacentral.com",
            is_active=True
        )
        db.session.add(hospital)
        db.session.flush()

        spec_cardio = Specialty(name="Cardiology", code="CARD", description="Heart specialist")
        spec_gp = Specialty(name="General Medicine", code="GEN", description="General physician")
        db.session.add_all([spec_cardio, spec_gp])
        db.session.flush()

        dept = Department(hospital_id=hospital.id, name="Cardiology Dept", code="CARD-DEPT")
        db.session.add(dept)
        db.session.flush()

        doc_user = User(
            email="doctor@test.com",
            full_name="Dr. Sarah Khan",
            phone="01711111111",
            role=UserRole.DOCTOR,
            status=UserStatus.ACTIVE
        )
        doc_user.set_password("Doctor@123")
        db.session.add(doc_user)
        db.session.flush()

        doc = Doctor(
            user_id=doc_user.id,
            hospital_id=hospital.id,
            department_id=dept.id,
            specialty_id=spec_cardio.id,
            license_number="BMDC-12345",
            consultation_fee=1000.0,
            slot_duration_minutes=15,
            verification_status="verified",
            is_accepting_appointments=True
        )
        db.session.add(doc)
        db.session.flush()

        # Doctor schedule for all days 9am - 5pm
        for day in range(7):
            sched = DoctorSchedule(
                doctor_id=doc.id,
                hospital_id=hospital.id,
                day_of_week=day,
                start_time="09:00",
                end_time="17:00",
                slot_duration_minutes=15,
                is_active=True
            )
            db.session.add(sched)

        # Receptionist user
        rec_user = User(
            email="reception@test.com",
            full_name="Receptionist Rahima",
            phone="01722222222",
            role=UserRole.RECEPTIONIST,
            status=UserStatus.ACTIVE
        )
        rec_user.set_password("Reception@123")
        db.session.add(rec_user)
        db.session.flush()

        from app.models import ReceptionistProfile, ReceptionistHospitalAssignment
        rec_profile = ReceptionistProfile(user_id=rec_user.id, employee_id="REC-001")
        db.session.add(rec_profile)
        db.session.flush()
        db.session.add(ReceptionistHospitalAssignment(receptionist_id=rec_profile.id, hospital_id=hospital.id, is_primary=True))

        # Admin user
        admin_user = User(
            email="admin@test.com",
            full_name="Hospital Admin",
            phone="01733333333",
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE
        )
        admin_user.set_password("Admin@123")
        db.session.add(admin_user)
        db.session.flush()

        from app.models import AdminProfile, AdminHospitalAssignment
        admin_prof = AdminProfile(user_id=admin_user.id)
        db.session.add(admin_prof)
        db.session.flush()
        db.session.add(AdminHospitalAssignment(admin_id=admin_prof.id, hospital_id=hospital.id, is_primary=True))

        # Medicines and Tests
        med = Medicine(brand_name="Napa Extra", generic_name="Paracetamol + Caffeine", strength="500mg+65mg", form="Tablet")
        test = MedicalTest(name="Complete Blood Count (CBC)", code="CBC", category="Blood")
        db.session.add_all([med, test])

        db.session.commit()
        return {
            "hospital_id": hospital.id,
            "doctor_id": doc.id,
            "doctor_user_id": doc_user.id,
            "cardio_id": spec_cardio.id,
            "gp_id": spec_gp.id,
            "med_id": med.id,
            "test_id": test.id
        }

def test_full_clinical_workflow(client, seed_data):
    # 1. Register a Patient
    resp = client.post('/api/auth/register', json={
        "full_name": "Test Patient",
        "email": "patient@test.com",
        "password": "Patient@123",
        "phone": "01799999999"
    })
    assert resp.status_code == 201
    pat_data = resp.get_json()
    assert pat_data["success"] is True

    # 2. Login Patient
    resp = client.post('/api/auth/login', json={
        "email": "patient@test.com",
        "password": "Patient@123"
    })
    assert resp.status_code == 200
    pat_token = resp.get_json()["data"]["access_token"]
    pat_headers = {"Authorization": f"Bearer {pat_token}"}

    # 3. Symptom recommendation
    resp = client.post('/api/recommend/specialty', json={
        "problem": "I have severe chest pain and breathlessness"
    })
    assert resp.status_code == 200
    recom_data = resp.get_json()["data"]
    assert "recommended_specialties" in recom_data

    # 4. Search Doctors
    resp = client.get('/api/doctors?specialty_id=' + str(seed_data["cardio_id"]))
    assert resp.status_code == 200
    docs = resp.get_json()["data"]["doctors"]
    assert len(docs) >= 1

    # 5. Book Appointment (valid future slot on the 15-min boundary)
    # Next day at 10:00 AM UTC
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    resp = client.post('/api/appointments', headers=pat_headers, json={
        "doctor_id": seed_data["doctor_id"],
        "hospital_id": seed_data["hospital_id"],
        "scheduled_start": tomorrow.isoformat(),
        "appointment_type": "in_person",
        "reason": "Chest checkup"
    })
    assert resp.status_code == 201
    appt = resp.get_json()["data"]
    appt_id = appt["id"]
    assert appt["status"] == "booked"

    # 6. Login Receptionist and Check-in Patient
    resp = client.post('/api/auth/login', json={
        "email": "reception@test.com",
        "password": "Reception@123"
    })
    assert resp.status_code == 200
    rec_token = resp.get_json()["data"]["access_token"]
    rec_headers = {"Authorization": f"Bearer {rec_token}"}

    resp = client.post(f'/api/appointments/{appt_id}/checkin', headers=rec_headers)
    assert resp.status_code == 200
    checkin_data = resp.get_json()["data"]
    assert "token" in checkin_data
    token_num = checkin_data["token"]["token_number"]
    assert token_num is not None

    # 7. Login Doctor and Start Consultation
    resp = client.post('/api/auth/login', json={
        "email": "doctor@test.com",
        "password": "Doctor@123"
    })
    assert resp.status_code == 200
    doc_token = resp.get_json()["data"]["access_token"]
    doc_headers = {"Authorization": f"Bearer {doc_token}"}

    resp = client.post(f'/api/appointments/{appt_id}/consultation', headers=doc_headers, json={
        "symptoms": "Chest pain for 2 days",
        "observations": "BP 130/85, Pulse 78",
        "notes": "ECG recommended"
    })
    assert resp.status_code == 201
    cons_data = resp.get_json()["data"]["consultation"]
    cons_id = cons_data["id"]

    # 8. Create Prescription
    resp = client.post(f'/api/appointments/{appt_id}/prescription', headers=doc_headers, json={
        "diagnosis_summary": "Mild angina / muscle strain",
        "advice": "Take rest and avoid heavy lifting",
        "follow_up_date": (datetime.now(timezone.utc).date() + timedelta(days=7)).isoformat(),
        "items": [
            {
                "medicine_id": seed_data["med_id"],
                "dosage": "1 tablet",
                "frequency": "1-0-1",
                "duration": "5 days",
                "meal_instruction": "After meal",
                "instructions": "If pain occurs"
            }
        ],
        "tests": [
            {
                "medical_test_id": seed_data["test_id"],
                "instructions": "Fasting sample"
            }
        ]
    })
    assert resp.status_code == 201
    rx = resp.get_json()["data"]["prescription"]
    rx_id = rx["id"]
    assert rx["status"] == "draft"

    # 9. Finalize Prescription
    resp = client.post(f'/api/prescriptions/{rx_id}/finalize', headers=doc_headers)
    assert resp.status_code == 200
    finalized_rx = resp.get_json()["data"]
    assert finalized_rx["status"] == "finalized"

    # 10. Complete Consultation
    resp = client.post(f'/api/consultations/{cons_id}/complete', headers=doc_headers, json={
        "advice": "Drink plenty of water"
    })
    assert resp.status_code == 200

    # 11. Patient Download Prescription PDF
    resp = client.get(f'/api/prescriptions/{rx_id}/pdf', headers=pat_headers)
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert len(resp.data) > 100
