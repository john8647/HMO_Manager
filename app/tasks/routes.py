from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request)
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
from app import db
from app.models import Task, Property, Room, Tenant

tasks_bp = Blueprint('tasks', __name__)

# ── Constants ─────────────────────────────────────────────────────────────────

CATEGORIES = [
    ('quick_fix',    'Quick Fix',     'A small job that can be done in one visit'),
    ('major_project','Major Project', 'A larger piece of work spanning multiple visits or weeks'),
    ('reminder',     'Reminder',      'A scheduled reminder — no action required, just awareness'),
    ('compliance',   'Compliance',    'Safety checks, certificate renewals, legal obligations'),
    ('admin',        'Admin',         'Paperwork, correspondence, financial admin'),
    ('maintenance',  'Maintenance',   'Routine upkeep and preventative work'),
]

PRIORITIES = [
    ('urgent', 'Urgent',  'Needs attention immediately'),
    ('high',   'High',    'Important, action this week'),
    ('medium', 'Medium',  'Action within the month'),
    ('low',    'Low',     'No immediate deadline'),
]

STATUSES = [
    ('open',        'Open'),
    ('in_progress', 'In Progress'),
    ('complete',    'Complete'),
    ('cancelled',   'Cancelled'),
]

REPEAT_OPTIONS = [
    ('none',    'No repeat — one off'),
    ('weekly',  'Weekly'),
    ('monthly', 'Monthly'),
    ('yearly',  'Yearly'),
]

CATEGORY_COLOURS = {
    'quick_fix':     'badge-green',
    'major_project': 'badge-red',
    'reminder':      'badge-yellow',
    'compliance':    'badge-red',
    'admin':         'badge-grey',
    'maintenance':   'badge-yellow',
}

PRIORITY_COLOURS = {
    'urgent': 'badge-red',
    'high':   'badge-red',
    'medium': 'badge-yellow',
    'low':    'badge-grey',
}


def get_task_or_404(task_id):
    return Task.query.filter_by(
        id=task_id, user_id=current_user.id
    ).first_or_404()


def next_due_date(current_due: date, repeat: str) -> date:
    """Calculate the next due date based on repeat schedule."""
    if repeat == 'weekly':
        return current_due + timedelta(weeks=1)
    elif repeat == 'monthly':
        month = current_due.month + 1
        year  = current_due.year + (1 if month > 12 else 0)
        month = month if month <= 12 else month - 12
        import calendar
        last_day = calendar.monthrange(year, month)[1]
        day = min(current_due.day, last_day)
        return date(year, month, day)
    elif repeat == 'yearly':
        try:
            return current_due.replace(year=current_due.year + 1)
        except ValueError:
            return current_due.replace(year=current_due.year + 1, day=28)
    return current_due


# ── List / Dashboard ──────────────────────────────────────────────────────────

@tasks_bp.route('/')
@login_required
def index():
    status_filter   = request.args.get('status', 'open')
    category_filter = request.args.get('category', '')
    priority_filter = request.args.get('priority', '')
    property_filter = request.args.get('property_id', '')

    query = Task.query.filter_by(user_id=current_user.id)

    if status_filter and status_filter != 'all':
        query = query.filter_by(status=status_filter)
    if category_filter:
        query = query.filter_by(priority=priority_filter) \
            if priority_filter else query
        query = query.filter_by(category=category_filter)
    if priority_filter:
        query = query.filter_by(priority=priority_filter)
    if property_filter:
        query = query.filter_by(property_id=int(property_filter))

    # Sort: urgent first, then by due date
    tasks = query.order_by(
        Task.status.asc(),
        Task.due_date.asc().nullslast(),
    ).all()

    # Attach colour helpers
    for task in tasks:
        task.cat_colour  = CATEGORY_COLOURS.get(task.category or '', 'badge-grey')
        task.pri_colour  = PRIORITY_COLOURS.get(task.priority or '', 'badge-grey')
        task.is_overdue  = (
            task.due_date and
            task.due_date < date.today() and
            task.status not in ('complete', 'cancelled')
        )
        task.due_soon = (
            task.due_date and
            0 <= (task.due_date - date.today()).days <= 7 and
            task.status not in ('complete', 'cancelled')
        )

    if current_user.role == 'admin':
        properties = Property.query.order_by(Property.address_line1).all()
    else:
        properties = Property.query.filter_by(
            user_id=current_user.id
        ).order_by(Property.address_line1).all()

    # Summary counts
    counts = {
        'open':        Task.query.filter_by(user_id=current_user.id, status='open').count(),
        'in_progress': Task.query.filter_by(user_id=current_user.id, status='in_progress').count(),
        'urgent':      Task.query.filter_by(user_id=current_user.id, priority='urgent',
                                             status='open').count(),
        'reminders':   Task.query.filter_by(user_id=current_user.id,
                                             category='reminder', status='open').count(),
        'overdue':     Task.query.filter(
                           Task.user_id == current_user.id,
                           Task.due_date < date.today(),
                           Task.status.notin_(['complete', 'cancelled'])
                       ).count(),
    }

    return render_template('tasks/index.html',
                           tasks=tasks,
                           properties=properties,
                           categories=CATEGORIES,
                           priorities=PRIORITIES,
                           statuses=STATUSES,
                           counts=counts,
                           status_filter=status_filter,
                           category_filter=category_filter,
                           priority_filter=priority_filter,
                           property_filter=property_filter,
                           today=date.today())


# ── Add ───────────────────────────────────────────────────────────────────────

@tasks_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if current_user.role == 'admin':
        properties = Property.query.order_by(Property.address_line1).all()
    else:
        properties = Property.query.filter_by(
            user_id=current_user.id
        ).order_by(Property.address_line1).all()

    tenants = Tenant.query.filter_by(
        user_id=current_user.id, is_active=True
    ).order_by(Tenant.last_name).all()

    # Pre-fill from query string (for system-generated tasks)
    prefill = {
        'title':       request.args.get('title', ''),
        'category':    request.args.get('category', ''),
        'priority':    request.args.get('priority', 'medium'),
        'property_id': request.args.get('property_id', ''),
        'description': request.args.get('description', ''),
    }

    if request.method == 'POST':
        title       = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        category    = request.form.get('category', '').strip()
        priority    = request.form.get('priority', 'medium').strip()
        property_id = request.form.get('property_id') or None
        room_id     = request.form.get('room_id') or None
        tenant_id   = request.form.get('tenant_id') or None
        due_date_s  = request.form.get('due_date', '').strip()
        repeat      = request.form.get('repeat', 'none').strip()
        time_bound  = request.form.get('time_bound') == 'on'

        if not title:
            flash('Title is required.', 'error')
            return render_template('tasks/add.html',
                                   properties=properties,
                                   tenants=tenants,
                                   categories=CATEGORIES,
                                   priorities=PRIORITIES,
                                   repeat_options=REPEAT_OPTIONS,
                                   prefill=prefill)

        due_date = None
        if due_date_s:
            try:
                due_date = datetime.strptime(due_date_s, '%Y-%m-%d').date()
            except ValueError:
                flash('Invalid due date.', 'error')
                return render_template('tasks/add.html',
                                       properties=properties,
                                       tenants=tenants,
                                       categories=CATEGORIES,
                                       priorities=PRIORITIES,
                                       repeat_options=REPEAT_OPTIONS,
                                       prefill=prefill)

        # Get room options for selected property
        rooms = []
        if property_id:
            rooms = Room.query.filter_by(
                property_id=int(property_id)
            ).order_by(Room.room_name).all()

        task = Task(
            user_id=current_user.id,
            title=title,
            description=description,
            category=category,
            priority=priority,
            status='open',
            property_id=int(property_id) if property_id else None,
            room_id=int(room_id) if room_id else None,
            tenant_id=int(tenant_id) if tenant_id else None,
            due_date=due_date,
            repeat=repeat,
            time_bound=time_bound,
        )
        db.session.add(task)
        db.session.commit()
        flash(f'Task "{title}" created.', 'success')
        return redirect(url_for('tasks.index'))

    # Pre-load rooms for pre-filled property
    rooms = []
    if prefill.get('property_id'):
        try:
            rooms = Room.query.filter_by(
                property_id=int(prefill['property_id'])
            ).order_by(Room.room_name).all()
        except (ValueError, TypeError):
            pass

    return render_template('tasks/add.html',
                           properties=properties,
                           tenants=tenants,
                           rooms=rooms,
                           categories=CATEGORIES,
                           priorities=PRIORITIES,
                           repeat_options=REPEAT_OPTIONS,
                           prefill=prefill)


# ── View / Edit ───────────────────────────────────────────────────────────────

@tasks_bp.route('/<int:task_id>', methods=['GET', 'POST'])
@login_required
def edit(task_id):
    task = get_task_or_404(task_id)

    if current_user.role == 'admin':
        properties = Property.query.order_by(Property.address_line1).all()
    else:
        properties = Property.query.filter_by(
            user_id=current_user.id
        ).order_by(Property.address_line1).all()

    tenants = Tenant.query.filter_by(
        user_id=current_user.id, is_active=True
    ).order_by(Tenant.last_name).all()

    rooms = []
    if task.property_id:
        rooms = Room.query.filter_by(
            property_id=task.property_id
        ).order_by(Room.room_name).all()

    if request.method == 'POST':
        task.title       = request.form.get('title', '').strip()
        task.description = request.form.get('description', '').strip()
        task.category    = request.form.get('category', '').strip()
        task.priority    = request.form.get('priority', 'medium').strip()
        task.status      = request.form.get('status', 'open').strip()
        task.property_id = int(request.form.get('property_id')) \
                           if request.form.get('property_id') else None
        task.room_id     = int(request.form.get('room_id')) \
                           if request.form.get('room_id') else None
        task.tenant_id   = int(request.form.get('tenant_id')) \
                           if request.form.get('tenant_id') else None
        task.repeat      = request.form.get('repeat', 'none')
        task.time_bound  = request.form.get('time_bound') == 'on'

        due_date_s = request.form.get('due_date', '').strip()
        if due_date_s:
            try:
                task.due_date = datetime.strptime(due_date_s, '%Y-%m-%d').date()
            except ValueError:
                flash('Invalid due date.', 'error')
                return render_template('tasks/edit.html',
                                       task=task,
                                       properties=properties,
                                       tenants=tenants,
                                       rooms=rooms,
                                       categories=CATEGORIES,
                                       priorities=PRIORITIES,
                                       statuses=STATUSES,
                                       repeat_options=REPEAT_OPTIONS)
        else:
            task.due_date = None

        if not task.title:
            flash('Title is required.', 'error')
            return render_template('tasks/edit.html',
                                   task=task,
                                   properties=properties,
                                   tenants=tenants,
                                   rooms=rooms,
                                   categories=CATEGORIES,
                                   priorities=PRIORITIES,
                                   statuses=STATUSES,
                                   repeat_options=REPEAT_OPTIONS)

        db.session.commit()
        flash(f'Task updated.', 'success')
        return redirect(url_for('tasks.index'))

    return render_template('tasks/edit.html',
                           task=task,
                           properties=properties,
                           tenants=tenants,
                           rooms=rooms,
                           categories=CATEGORIES,
                           priorities=PRIORITIES,
                           statuses=STATUSES,
                           repeat_options=REPEAT_OPTIONS)


# ── Complete ──────────────────────────────────────────────────────────────────

@tasks_bp.route('/<int:task_id>/complete', methods=['POST'])
@login_required
def complete(task_id):
    task = get_task_or_404(task_id)
    task.status       = 'complete'
    task.completed_at = datetime.utcnow()

    # If repeating, create the next occurrence automatically
    if task.repeat and task.repeat != 'none' and task.due_date:
        new_due = next_due_date(task.due_date, task.repeat)
        new_task = Task(
            user_id=current_user.id,
            title=task.title,
            description=task.description,
            category=task.category,
            priority=task.priority,
            status='open',
            property_id=task.property_id,
            room_id=task.room_id,
            tenant_id=task.tenant_id,
            due_date=new_due,
            repeat=task.repeat,
            time_bound=task.time_bound,
        )
        db.session.add(new_task)
        flash(
            f'Task completed. Next occurrence scheduled for '
            f'{new_due.strftime("%d %b %Y")}.',
            'success'
        )
    else:
        flash('Task marked as complete.', 'success')

    db.session.commit()
    return redirect(url_for('tasks.index'))


# ── Cancel ────────────────────────────────────────────────────────────────────

@tasks_bp.route('/<int:task_id>/cancel', methods=['POST'])
@login_required
def cancel(task_id):
    task = get_task_or_404(task_id)
    task.status = 'cancelled'
    db.session.commit()
    flash('Task cancelled.', 'success')
    return redirect(url_for('tasks.index'))


# ── Delete ────────────────────────────────────────────────────────────────────

@tasks_bp.route('/<int:task_id>/delete', methods=['POST'])
@login_required
def delete(task_id):
    task = get_task_or_404(task_id)
    db.session.delete(task)
    db.session.commit()
    flash('Task deleted.', 'success')
    return redirect(url_for('tasks.index'))


# ── AJAX room loader ──────────────────────────────────────────────────────────

@tasks_bp.route('/rooms/<int:property_id>')
@login_required
def rooms_for_property(property_id):
    from flask import jsonify
    rooms = Room.query.filter_by(
        property_id=property_id
    ).order_by(Room.room_name).all()
    return jsonify([{'id': r.id, 'name': r.room_name} for r in rooms])
