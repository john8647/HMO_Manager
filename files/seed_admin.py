"""
Run this once to create the first admin user.
Usage:  uv run python seed_admin.py
"""

from app import create_app, db
from app.models import User

app = create_app('development')

with app.app_context():
    # Change these values before running
    USERNAME = 'admin'
    EMAIL    = 'admin@landlordapp.local'
    PASSWORD = 'changeme123'
    ROLE     = 'admin'

    existing = User.query.filter_by(username=USERNAME).first()
    if existing:
        print(f'User "{USERNAME}" already exists. Nothing created.')
    else:
        user = User(username=USERNAME, email=EMAIL, role=ROLE)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
        print(f'Admin user created.')
        print(f'  Username : {USERNAME}')
        print(f'  Password : {PASSWORD}')
        print(f'  Role     : {ROLE}')
        print()
        print('Log in at http://127.0.0.1:5000/auth/login')
        print('Change your password after first login!')
