from flask import Blueprint

deposits_bp = Blueprint('deposits', __name__)


@deposits_bp.route('/')
def index():
    return '<h1>Deposits</h1><p>Under construction.</p>'
