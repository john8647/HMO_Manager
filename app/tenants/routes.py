from flask import Blueprint

tenants_bp = Blueprint('tenants', __name__)


@tenants_bp.route('/')
def index():
    return '<h1>Tenants</h1><p>Under construction.</p>'
