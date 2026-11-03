from flask import Blueprint

transactions_bp = Blueprint('transactions', __name__)


@transactions_bp.route('/')
def index():
    return '<h1>Transactions</h1><p>Under construction.</p>'
