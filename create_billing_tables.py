from app import create_app, db

app = create_app()

with app.app_context():
    # Only creates tables that don't exist yet, safe to run.
    db.create_all()
    print("Database updated and missing tables created successfully.")
