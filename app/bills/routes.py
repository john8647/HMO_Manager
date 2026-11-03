from flask import Blueprint

bills_bp = Blueprint('bills', __name__)


@bills_bp.route('/')
def index():
    return '<h1>Bills</h1><p>Under construction.</p>'
