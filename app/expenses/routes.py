from flask import Blueprint

expenses_bp = Blueprint('expenses', __name__)


@expenses_bp.route('/')
def index():
    return '<h1>Expenses</h1><p>Under construction.</p>'
