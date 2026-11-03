from flask import Blueprint

properties_bp = Blueprint('properties', __name__)


@properties_bp.route('/')
def index():
    return '<h1>Properties</h1><p>Under construction.</p>'
