from app import create_app, db
from app import models  # noqa: F401 — ensures models are registered

app = create_app('development')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
