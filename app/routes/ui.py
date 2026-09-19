from flask import Blueprint, redirect, render_template, session

bp = Blueprint("ui", __name__)


@bp.get("/")
def index():
    return render_template("index.html")


# Auth routes
@bp.get("/auth/login")
def login_page():
    return render_template("auth/login.html")


@bp.get("/auth/register")
def register_page():
    return render_template("auth/register.html")


@bp.get("/auth/logout")
def logout():
    session.clear()
    return redirect("/auth/login")


# Patient routes
@bp.get("/patient/dashboard")
def patient_dashboard():
    return render_template("patient/dashboard.html")


@bp.get("/patient/appointments")
def patient_appointments():
    return render_template("patient/appointments.html")


@bp.get("/patient/appointments/<int:appointment_id>")
def patient_appointment_detail(appointment_id):
    return render_template("patient/appointments.html")


@bp.get("/patient/prescriptions")
def patient_prescriptions():
    return render_template("patient/prescriptions.html")


@bp.get("/patient/prescriptions/<int:prescription_id>")
def patient_prescription_detail(prescription_id):
    return render_template("patient/prescriptions.html")


@bp.get("/patient/profile")
def patient_profile():
    return render_template("patient/profile.html")


@bp.get("/patient/lab-reports")
def patient_lab_reports():
    return render_template("patient/lab_reports.html")


@bp.get("/patient/billing")
def patient_billing():
    return render_template("patient/billing.html")


@bp.get("/patient/consent")
def patient_consent():
    return render_template("patient/consent.html")


@bp.get("/doctor/profile")
def doctor_profile():
    return render_template("doctor/dashboard.html")


@bp.get("/patient/find-doctor")
@bp.get("/find-doctor")
def patient_find_doctor():
    return render_template("patient/find_doctor.html")


@bp.get("/hospitals")
def hospitals_page():
    return render_template("patient/find_doctor.html")


@bp.get("/recommend")
def recommendation_page():
    return render_template("patient/find_doctor.html")


# Doctor routes
@bp.get("/doctor/dashboard")
def doctor_dashboard():
    return render_template("doctor/dashboard.html")


@bp.get("/doctor/queue")
def doctor_queue():
    return render_template("doctor/queue.html")


@bp.get("/doctor/consultation/<int:appointment_id>")
def doctor_consultation(appointment_id):
    return render_template("doctor/consultation.html", appointment_id=appointment_id)


# Receptionist routes
@bp.get("/receptionist/dashboard")
def receptionist_dashboard():
    return render_template("receptionist/dashboard.html")


# Admin routes
@bp.get("/admin/dashboard")
def admin_dashboard():
    return render_template("admin/dashboard.html")


@bp.get("/admin/doctors")
def admin_doctors():
    return render_template("admin/doctors.html")


@bp.get("/admin/hospitals")
def admin_hospitals():
    return render_template("admin/hospitals.html")


@bp.get("/admin/tenants")
def admin_tenants():
    return render_template("admin/tenants.html")


@bp.get("/admin/appointments")
def admin_appointments():
    return render_template("admin/appointments.html")


@bp.get("/admin/billing")
def admin_billing():
    return render_template("admin/billing.html")


@bp.get("/admin/analytics")
def admin_analytics():
    return render_template("admin/analytics.html")


# Receptionist routes
@bp.get("/receptionist/check-in")
def receptionist_check_in():
    return render_template("receptionist/check_in.html")


@bp.get("/receptionist/queue")
def receptionist_queue():
    return render_template("receptionist/queue.html")


# Public Queue TV Display with SSE
@bp.get("/queue-display")
def queue_display():
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hospital Queue Display</title>
<style>
:root{color-scheme:light}
body{margin:0;font-family:system-ui;background:#0b1220;color:#fff;display:flex;min-height:100vh;align-items:center;justify-content:center}
.box{width:min(90vw,1100px);text-align:center}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:24px}
.card{background:#111827;border:1px solid #1f2937;border-radius:18px;padding:28px 22px}
.big{font-size:clamp(64px,10vw,120px);font-weight:800;letter-spacing:2px}
.label{font-size:28px;letter-spacing:3px;color:#9ca3af;text-transform:uppercase}
.info{margin-top:18px;font-size:24px;color:#d1d5db}
.title{font-size:44px;font-weight:800}
.status{margin-top:16px;padding:12px;border-radius:999px;background:#064e3b;color:#a7f3d0;display:inline-block}
</style>
</head>
<body>
<main class="box">
  <div class="title">NOW SERVING</div>
  <div class="card"><div class="label">Current Token</div><div id="current" class="big">A-000</div></div>
  <div class="grid">
    <div class="card"><div class="label">Next</div><div id="next" class="big">A-001</div></div>
    <div class="card"><div class="label">Doctor / Room</div><div id="doctor" class="info">-</div><div id="room" class="info">-</div><div id="status" class="status">Live</div></div>
  </div>
</main>
<script>
const hID = new URLSearchParams(location.search).get('hospital_id') || '1';
async function init(){
  const res=await fetch('/api/queues/display?hospital_id='+hID);
  const data=await res.json();
  update(data?.data);
}
function update(d){
  document.getElementById('current').textContent=d?.current_token?.token_number||'-';
  document.getElementById('next').textContent=d?.next_token?.token_number||'-';
  document.getElementById('doctor').textContent=d?.doctor||'-';
  document.getElementById('room').textContent=d?.room||'-';
}
const es = new EventSource('/api/queues/stream?hospital_id='+hID);
es.addEventListener('queue_update', e => {
  const d = JSON.parse(e.data);
  update(d);
  document.getElementById('status').textContent='Live • Updated';
  setTimeout(()=>document.getElementById('status').textContent='Live',2000);
});
es.onerror = () => { document.getElementById('status').textContent='Reconnecting…'; };
init();
</script>
</body>
</html>"""
