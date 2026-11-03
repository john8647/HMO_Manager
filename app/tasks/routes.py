from flask import Blueprint

tasks_bp = Blueprint('tasks', __name__)


@tasks_bp.route('/')
def index():
    return '<h1>Tasks</h1><p>Under construction.</p>'
