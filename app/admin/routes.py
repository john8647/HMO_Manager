from flask import Blueprint

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/')
def index():
    return '<h1>Admin</h1><p>Under construction.</p>'
