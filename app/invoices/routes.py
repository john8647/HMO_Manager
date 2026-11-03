from flask import Blueprint

invoices_bp = Blueprint('invoices', __name__)


@invoices_bp.route('/')
def index():
    return '<h1>Invoices</h1><p>Under construction.</p>'
