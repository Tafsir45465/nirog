from app import create_app, db

app = create_app()

with app.app_context():
    # Execute SQL to alter the hospitals table.
    # NOTE: SQLite support for ALTER TABLE is limited, but adding columns is fine.
    try:
        db.session.execute(db.text("ALTER TABLE hospitals ADD COLUMN subscription_tier VARCHAR(50) NOT NULL DEFAULT 'free'"))
        db.session.execute(db.text("ALTER TABLE hospitals ADD COLUMN subscription_status VARCHAR(50) NOT NULL DEFAULT 'active'"))
        db.session.execute(db.text("ALTER TABLE hospitals ADD COLUMN subscription_expires_at DATETIME"))
        db.session.execute(db.text("ALTER TABLE hospitals ADD COLUMN custom_domain VARCHAR(255)"))
        db.session.execute(db.text("ALTER TABLE hospitals ADD COLUMN max_doctors INTEGER NOT NULL DEFAULT 5"))
        db.session.execute(db.text("ALTER TABLE hospitals ADD COLUMN tenant_settings JSON"))
        db.session.commit()
        print("Migration successful")
    except Exception as e:
        print(f"Migration failed (it might have already been applied): {e}")
        db.session.rollback()
