import pytest
from app import create_app
from app.extensions import db

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

def test_patient_register_and_login(client):
    resp = client.post('/api/auth/register', json={
        "full_name": "Test Patient",
        "email": "testpatient@mail.com",
        "password": "SecurePass123!",
        "phone": "0123456789"
    })
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["success"] is True
    assert data["data"]["user"]["email"] == "testpatient@mail.com"
    assert data["data"]["user"]["role"] == "patient"
    assert data["data"]["patient"]["patient_code"] is not None

    resp = client.post('/api/auth/login', json={
        "email": "testpatient@mail.com",
        "password": "SecurePass123!"
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "access_token" in data["data"]
    assert data["data"]["user"]["role"] == "patient"

    headers = {"Authorization": f"Bearer {data['data']['access_token']}"}
    resp = client.get('/api/appointments', headers=headers)
    assert resp.status_code == 200
