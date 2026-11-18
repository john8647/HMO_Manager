from app import create_app, db
from app import models  # noqa: F401 — ensures models are registered
import os
# app = create_app('development')
app = create_app(os.environ.get('FLASK_ENV', 'default'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
