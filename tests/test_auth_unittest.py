import unittest

from app import create_app
from app.extensions import db

class TestAuth(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_patient_register_and_login(self):
        resp = self.client.post('/api/auth/register', json={
            "full_name": "Test Patient",
            "email": "testpatient@mail.com",
            "password": "SecurePass123!",
            "phone": "0123456789"
        })
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["user"]["email"], "testpatient@mail.com")
        self.assertEqual(data["data"]["user"]["role"], "patient")
        self.assertIsNotNone(data["data"]["patient"]["patient_code"])

        resp = self.client.post('/api/auth/login', json={
            "email": "testpatient@mail.com",
            "password": "SecurePass123!"
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertIn("access_token", data["data"])
        self.assertEqual(data["data"]["user"]["role"], "patient")

        headers = {"Authorization": f"Bearer {data['data']['access_token']}"}
        resp = self.client.get('/api/appointments', headers=headers)
        self.assertEqual(resp.status_code, 200)

if __name__ == '__main__':
    unittest.main()
