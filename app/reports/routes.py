from flask import Blueprint

reports_bp = Blueprint('reports', __name__)


@reports_bp.route('/')
def index():
    return '<h1>Reports</h1><p>Under construction.</p>'
