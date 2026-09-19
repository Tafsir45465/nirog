# Nirog Healthcare Platform

A comprehensive, secure, multi-tenant healthcare management platform built with Flask, supporting multiple hospitals, appointment booking, queue management, billing, analytics, and more.

---

## Overview

Nirog is a production-ready healthcare platform designed for scalability and security. It provides role-based access control, multi-tenant architecture, real-time queue displays, video consultations, billing dashboards, advanced analytics, automated backups, and extensive patient/doctor management features.

---

## Key Features

### Core Functionality
- **Multi-Tenant Architecture**: Isolated hospital tenants with custom domains, subscription tiers, and per-tenant settings
- **Role-Based Access Control (RBAC)**: Super Admin, Admin, Doctor, Receptionist, Patient roles with granular permissions
- **Appointments & Scheduling**: Time slot verification, conflict prevention, doctor schedules with breaks, rescheduling, cancellation
- **Smart Queue Management**: Real-time waiting time estimates, emergency/priority/standard queue levels, SSE-powered live displays
- **Prescriptions**: Draft-to-finalized workflow, medical test orders, medicine catalog, PDF generation
- **Consultations**: Clinical notes, diagnoses, observations, advice, follow-up tracking
- **Lab Reports**: Upload PDF/image reports, file validation (content-based MIME detection), secure storage

### Advanced Features
- **Video Consultations**: Zoom, Google Meet, Jitsi integration with meeting link generation
- **Billing & Invoicing**: Invoice generation, partial/full payments, multiple payment methods (cash, card, bKash, Nagad), payment tracking
- **Analytics Dashboard**: Daily appointment volume, revenue trends, specialty distribution, doctor workload, completion rates
- **Data Export**: Formula-injection-safe CSV export, Excel/PDF generation for appointments, invoices, payments, doctor performance
- **Push Notifications**: Device token management, notification logs, cross-platform (iOS, Android, Web)
- **Patient Consent Management**: HIPAA-compliant consent tracking (treatment, data sharing, research, telehealth)
- **QR Code Patient Identification**: Generate and scan QR codes for quick patient lookup
- **Doctor Reviews & Ratings**: Verified reviews from patients with completed consultations
- **Favorites**: Patients can favorite doctors for quick access
- **Automated Backups**: Scheduled database backups with SHA-256 checksums, retention policies, restore capability
- **SMS/Email Notifications**: Multi-channel notifications via SMTP, Twilio
- **Audit Logs**: Comprehensive action tracking for compliance and security

### Security & Compliance
- **JWT Authentication**: Access and refresh tokens with secure storage
- **IDOR Protection**: Tenant isolation, patient access controls
- **CSRF/XSS Mitigations**: Input validation, output escaping, secure headers
- **Content-Based File Validation**: Magic byte inspection to prevent malicious uploads
- **Soft Delete**: Data retention for audit trails
- **Production Secret Validation**: Runtime checks for strong secrets in production mode

---

## Tech Stack

- **Backend**: Python 3.10+, Flask 3.x, Flask-SQLAlchemy, Flask-Migrate, Flask-JWT-Extended
- **Database**: SQLite (dev), PostgreSQL (production-ready)
- **Frontend**: Server-rendered Jinja templates, vanilla JavaScript, Chart.js for analytics
- **Real-Time**: Server-Sent Events (SSE) for queue displays
- **File Processing**: ReportLab (PDF), openpyxl (Excel), Pillow (image processing), qrcode
- **Video**: Zoom SDK, Google Meet API, Jitsi integration
- **Notifications**: SMTP, Twilio (SMS), Web Push (VAPID)
- **Testing**: pytest, pytest-flask

---

## Setup & Installation

### Requirements
- Python 3.10 or higher
- pip package manager
- (Optional) PostgreSQL for production

### Installation Steps

1. **Clone the repository**
   ```bash
   git clone <your-repo-url>
   cd nirog
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   ```

3. **Activate virtual environment**
   - Windows:
     ```bash
     .\venv\Scripts\activate
     ```
   - Linux/macOS:
     ```bash
     source venv/bin/activate
     ```

4. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

5. **Configure environment**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and set:
   - `SECRET_KEY` (generate a strong random key)
   - `JWT_SECRET_KEY` (generate a different strong random key)
   - `DATABASE_URL` (use PostgreSQL URL for production)
   - Video consultation credentials (Zoom, Google Meet)
   - SMTP settings for email notifications
   - SMS provider settings (Twilio)
   - Push notification VAPID keys
   - Backup storage configuration

6. **Initialize database and seed data**
   ```bash
   python -m app.seed
   ```
   This creates:
   - 3 sample hospitals
   - Super admin, admin, receptionist accounts
   - 5 patients, 3 doctors
   - Specialties, schedules, medicines catalog

7. **Run the application**
   ```bash
   python run.py
   ```
   Access the platform at [http://localhost:5000](http://localhost:5000)

---

## Usage

### Default Accounts (from seed data)
- **Super Admin**: `super@admin.com` / `admin123`
- **Admin**: `admin@nirog.com` / `admin123`
- **Receptionist**: `receptionist@nirog.com` / `recept123`
- **Doctor**: Check console output after seeding
- **Patient**: Check console output after seeding

### Key URLs
- **Main Dashboard**: `http://localhost:5000/`
- **Queue Display (TV)**: `http://localhost:5000/queue-display`
- **Admin Portal**: `http://localhost:5000/admin/dashboard`
- **Doctor Portal**: `http://localhost:5000/doctor/dashboard`
- **Patient Portal**: `http://localhost:5000/patient/dashboard`
- **Analytics**: `http://localhost:5000/admin/analytics`
- **Billing**: `http://localhost:5000/admin/billing`

---

## API Documentation

### Authentication
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login and receive JWT
- `POST /api/auth/refresh` - Refresh access token
- `POST /api/auth/logout` - Logout (invalidate refresh token)

### Appointments
- `GET /api/appointments` - List appointments
- `POST /api/appointments` - Book appointment
- `PATCH /api/appointments/<id>` - Update appointment
- `DELETE /api/appointments/<id>` - Cancel appointment

### Queue Management
- `POST /api/smart-queue/queue/<queue_id>/check-in/<appointment_id>` - Check in patient
- `POST /api/smart-queue/queue/<queue_id>/call-next` - Call next token
- `GET /api/smart-queue/queue/<queue_id>/position/<patient_id>` - Get patient position
- `GET /api/smart-queue/hospital/<hospital_id>/queue-status` - Get full queue status

### Prescriptions & Lab Reports
- `POST /api/prescriptions` - Create prescription
- `GET /api/prescriptions/<id>` - Get prescription
- `POST /api/lab-reports/upload` - Upload lab report
- `GET /api/lab-reports/<id>/download` - Download lab report

### Billing
- `POST /api/billing/invoices` - Create invoice
- `GET /api/billing/invoices/<id>` - Get invoice
- `POST /api/billing/payments` - Record payment
- `GET /api/billing/dashboard` - Billing analytics

### Analytics
- `GET /api/analytics/dashboard?days=<N>` - Summary statistics
- `GET /api/analytics/daily-volume?days=<N>` - Appointment volume chart
- `GET /api/analytics/revenue-trend?days=<N>` - Revenue trend
- `GET /api/analytics/doctor-workload?days=<N>` - Doctor performance

### Exports
- `GET /api/exports/appointments/csv` - Export appointments as CSV
- `GET /api/exports/invoices/csv` - Export invoices as CSV
- `GET /api/exports/payments/csv` - Export payments as CSV
- `GET /api/exports/doctors/performance/csv` - Export doctor performance

### Backups
- `POST /api/backups/create` - Create backup
- `GET /api/backups` - List backups
- `POST /api/backups/<backup_id>/restore` - Restore from backup

---

## Testing

Run the test suite:
```bash
pytest
```

Run with coverage:
```bash
pytest --cov=app --cov-report=html
```

Run specific test file:
```bash
pytest test_auth.py
```

---

## Database Migrations

Generate migration after model changes:
```bash
flask db migrate -m "Description of changes"
```

Apply migrations:
```bash
flask db upgrade
```

Rollback migration:
```bash
flask db downgrade
```

---

## Production Deployment

### Environment Variables (Production)
Set these in your production environment:
- `FLASK_ENV=production`
- `SECRET_KEY` - Strong random key (32+ chars)
- `JWT_SECRET_KEY` - Different strong random key
- `DATABASE_URL` - PostgreSQL connection string
- `CORS_ORIGINS` - Your production domain(s)
- Video/notification/backup credentials as needed

### Production Checklist
- [ ] Set strong `SECRET_KEY` and `JWT_SECRET_KEY`
- [ ] Use PostgreSQL (not SQLite)
- [ ] Enable HTTPS/TLS
- [ ] Configure proper CORS origins
- [ ] Set up automated backups
- [ ] Configure email/SMS notifications
- [ ] Enable rate limiting with Redis
- [ ] Set up monitoring and logging
- [ ] Review and apply database migrations
- [ ] Configure video consultation providers
- [ ] Set file upload size limits appropriately

### Recommended Production Stack
- **WSGI Server**: Gunicorn
- **Reverse Proxy**: Nginx
- **Database**: PostgreSQL 14+
- **Cache/Sessions**: Redis
- **Hosting**: AWS, GCP, Azure, DigitalOcean
- **Backup Storage**: S3, Google Cloud Storage, or local with rotation

---

## Architecture

### Multi-Tenant Design
- Each hospital is a tenant with isolated data
- Tenant resolution via:
  - `X-Hospital-Id` header
  - `X-Tenant-Slug` header
  - Custom domain mapping
- All queries filtered by hospital_id

### Role Hierarchy
1. **SUPER_ADMIN**: Platform-wide access
2. **ADMIN**: Hospital-level management
3. **DOCTOR**: Medical operations within assigned hospitals
4. **RECEPTIONIST**: Front-desk operations
5. **PATIENT**: Self-service portal

### Key Models
- `Hospital` - Tenant entity with subscription management
- `User` - Authentication and role assignment
- `Patient`, `Doctor`, `AdminProfile`, `ReceptionistProfile` - Role-specific profiles
- `Appointment` - Scheduling with conflict detection
- `Queue`, `QueueToken` - Real-time queue management
- `Consultation`, `Prescription` - Clinical workflow
- `Invoice`, `Payment` - Billing operations
- `BackupLog` - Backup tracking and audit

---

## File Structure

```
nirog/
├── app/
│   ├── __init__.py          # Application factory
│   ├── config.py            # Environment configuration
│   ├── models/              # Database models
│   ├── routes/              # API blueprints
│   ├── services/            # Business logic layer
│   ├── templates/           # Jinja templates
│   ├── static/              # CSS, JS, images
│   ├── utils/               # Helper functions
│   ├── security.py          # Auth & authorization
│   ├── errors.py            # Error handling
│   └── seed.py              # Database seeding
├── migrations/              # Flask-Migrate files
├── tests/                   # Test suite
├── requirements.txt         # Python dependencies
├── .env.example             # Environment template
├── run.py                   # Application entry point
└── README.md                # This file
```

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## License

This project is licensed under the MIT License.

---

## Support

For issues, questions, or feature requests, please open an issue on the GitHub repository.

---

## Acknowledgments

Built with Flask, SQLAlchemy, and modern web technologies to deliver a comprehensive healthcare management solution.
