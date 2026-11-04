from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from app.models import Property, Room, TenantContract

properties_bp = Blueprint('properties', __name__)


def get_property_or_404(property_id):
    prop = Property.query.filter_by(
        id=property_id, user_id=current_user.id
    ).first_or_404()
    return prop


# ── Properties ──────────────────────────────────────────────────────────────

@properties_bp.route('/')
@login_required
def index():
    if current_user.role == 'admin':
        properties = Property.query.order_by(Property.address_line1).all()
    else:
        properties = Property.query.filter_by(
            user_id=current_user.id
        ).order_by(Property.address_line1).all()

    # Attach room and tenant counts for display
    for prop in properties:
        prop.room_count = prop.rooms.count()
        prop.occupied_count = prop.rooms.filter_by(is_occupied=True).count()

    return render_template('properties/index.html', properties=properties)


@properties_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if request.method == 'POST':
        address_line1 = request.form.get('address_line1', '').strip()
        address_line2 = request.form.get('address_line2', '').strip()
        city = request.form.get('city', '').strip()
        postcode = request.form.get('postcode', '').strip().upper()
        property_ref = request.form.get('property_ref', '').strip()

        if not address_line1:
            flash('Address is required.', 'error')
            return render_template('properties/add.html')

        prop = Property(
            user_id=current_user.id,
            address_line1=address_line1,
            address_line2=address_line2,
            city=city,
            postcode=postcode,
            property_ref=property_ref,
        )
        db.session.add(prop)
        db.session.commit()
        flash(f'Property "{address_line1}" added successfully.', 'success')
        return redirect(url_for('properties.view', property_id=prop.id))

    return render_template('properties/add.html')


@properties_bp.route('/<int:property_id>')
@login_required
def view(property_id):
    prop = get_property_or_404(property_id)
    rooms = prop.rooms.order_by(Room.room_name).all()

    # Attach active tenant info to each room
    for room in rooms:
        active_contract = TenantContract.query.filter_by(
            room_id=room.id, is_active=True
        ).first()
        room.active_tenant = active_contract.tenant if active_contract else None

    return render_template('properties/view.html', prop=prop, rooms=rooms)


@properties_bp.route('/<int:property_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(property_id):
    prop = get_property_or_404(property_id)

    if request.method == 'POST':
        prop.address_line1 = request.form.get('address_line1', '').strip()
        prop.address_line2 = request.form.get('address_line2', '').strip()
        prop.city = request.form.get('city', '').strip()
        prop.postcode = request.form.get('postcode', '').strip().upper()
        prop.property_ref = request.form.get('property_ref', '').strip()

        if not prop.address_line1:
            flash('Address is required.', 'error')
            return render_template('properties/edit.html', prop=prop)

        db.session.commit()
        flash('Property updated.', 'success')
        return redirect(url_for('properties.view', property_id=prop.id))

    return render_template('properties/edit.html', prop=prop)


@properties_bp.route('/<int:property_id>/delete', methods=['POST'])
@login_required
def delete(property_id):
    prop = get_property_or_404(property_id)

    if prop.rooms.count() > 0:
        flash('Cannot delete a property that has rooms. Remove all rooms first.', 'error')
        return redirect(url_for('properties.view', property_id=prop.id))

    db.session.delete(prop)
    db.session.commit()
    flash('Property deleted.', 'success')
    return redirect(url_for('properties.index'))


# ── Rooms ────────────────────────────────────────────────────────────────────

@properties_bp.route('/<int:property_id>/rooms/add', methods=['GET', 'POST'])
@login_required
def add_room(property_id):
    prop = get_property_or_404(property_id)

    if request.method == 'POST':
        room_name = request.form.get('room_name', '').strip()

        if not room_name:
            flash('Room name is required.', 'error')
            return render_template('properties/add_room.html', prop=prop)

        # Check for duplicate room name in this property
        existing = Room.query.filter_by(
            property_id=prop.id, room_name=room_name
        ).first()
        if existing:
            flash(
                f'A room called "{room_name}" already exists in this property.', 'error')
            return render_template('properties/add_room.html', prop=prop)

        room = Room(property_id=prop.id,
                    room_name=room_name, is_occupied=False)
        db.session.add(room)
        db.session.commit()
        flash(f'Room "{room_name}" added.', 'success')
        return redirect(url_for('properties.view', property_id=prop.id))

    return render_template('properties/add_room.html', prop=prop)


@properties_bp.route('/<int:property_id>/rooms/<int:room_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_room(property_id, room_id):
    prop = get_property_or_404(property_id)
    room = Room.query.filter_by(id=room_id, property_id=prop.id).first_or_404()

    if request.method == 'POST':
        room_name = request.form.get('room_name', '').strip()

        if not room_name:
            flash('Room name is required.', 'error')
            return render_template('properties/edit_room.html', prop=prop, room=room)

        room.room_name = room_name
        db.session.commit()
        flash(f'Room updated to "{room_name}".', 'success')
        return redirect(url_for('properties.view', property_id=prop.id))

    return render_template('properties/edit_room.html', prop=prop, room=room)


@properties_bp.route('/<int:property_id>/rooms/<int:room_id>/delete', methods=['POST'])
@login_required
def delete_room(property_id, room_id):
    prop = get_property_or_404(property_id)
    room = Room.query.filter_by(id=room_id, property_id=prop.id).first_or_404()

    if room.is_occupied:
        flash('Cannot delete an occupied room. Move the tenant out first.', 'error')
        return redirect(url_for('properties.view', property_id=prop.id))

    db.session.delete(room)
    db.session.commit()
    flash(f'Room "{room.room_name}" deleted.', 'success')
    return redirect(url_for('properties.view', property_id=prop.id))
