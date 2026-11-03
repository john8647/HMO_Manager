from flask import Blueprint

compliance_bp = Blueprint('compliance', __name__)


@compliance_bp.route('/')
def index():
    return '<h1>Compliance</h1><p>Under construction.</p>'
