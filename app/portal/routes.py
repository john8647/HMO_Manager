from flask import Blueprint

portal_bp = Blueprint('portal', __name__)


@portal_bp.route('/')
def index():
    return '<h1>Portal</h1><p>Under construction.</p>'
