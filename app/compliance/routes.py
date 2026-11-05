from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, send_from_directory)
from flask_login import login_required, current_user
from datetime import datetime, date
import os
from werkzeug.utils import secure_filename
from app import db
from app.models import ComplianceDocument, Property

compliance_bp = Blueprint('compliance', __name__)

UPLOAD_FOLDER = 'app/static/uploads/compliance'
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png'}

DOCUMENT_TYPES = [
    ('Gas Safety Certificate',       1),
    ('Electrical Installation (EICR)', 5),
    ('Energy Performance (EPC)',      10),
    ('Fire Alarm Test',               1),
    ('Emergency Lighting',            1),
    ('PAT Testing',                   1),
    ('HMO Licence',                   5),
    ('Buildings Insurance',           1),
    ('Contents Insurance',            1),
    ('Utility Tariff — Gas',          1),
    ('Utility Tariff — Electric',     1),
    ('Broadband Contract',            2),
    ('Right to Rent Check',           1),
    ('Other',                         1),
]


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_doc_or_404(doc_id):
    return ComplianceDocument.query.filter_by(
        id=doc_id, user_id=current_user.id
    ).first_or_404()


def days_until(expiry_date):
    if not expiry_date:
        return None
    return (expiry_date - date.today()).days


# ── Dashboard ─────────────────────────────────────────────────────────────────

@compliance_bp.route('/')
@login_required
def index():
    if current_user.role == 'admin':
        properties = Property.query.order_by(Property.address_line1).all()
    else:
        properties = Property.query.filter_by(
            user_id=current_user.id
        ).order_by(Property.address_line1).all()

    # Group documents by property
    property_docs = {}
    for prop in properties:
        docs = ComplianceDocument.query.filter_by(
            property_id=prop.id
        ).order_by(ComplianceDocument.document_type).all()

        # Attach days_until for each doc
        for doc in docs:
            doc.days_left = days_until(doc.expiry_date)

        property_docs[prop.id] = {
            'property': prop,
            'docs': docs,
            'expired': [d for d in docs if d.days_left is not None and d.days_left < 0],
            'expiring_soon': [d for d in docs if d.days_left is not None and 0 <= d.days_left <= 60],
            'current': [d for d in docs if d.days_left is None or d.days_left > 60],
        }

    # Overall alert counts for dashboard banner
    total_expired = sum(len(v['expired']) for v in property_docs.values())
    total_soon    = sum(len(v['expiring_soon']) for v in property_docs.values())

    return render_template('compliance/index.html',
                           property_docs=property_docs,
                           total_expired=total_expired,
                           total_soon=total_soon,
                           document_types=DOCUMENT_TYPES,
                           today=date.today())


# ── Add document ──────────────────────────────────────────────────────────────

@compliance_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if current_user.role == 'admin':
        properties = Property.query.order_by(Property.address_line1).all()
    else:
        properties = Property.query.filter_by(
            user_id=current_user.id
        ).order_by(Property.address_line1).all()

    if request.method == 'POST':
        property_id   = request.form.get('property_id', '').strip()
        document_type = request.form.get('document_type', '').strip()
        issue_str     = request.form.get('issue_date', '').strip()
        expiry_str    = request.form.get('expiry_date', '').strip()
        renewal_years = request.form.get('renewal_years', '1').strip()
        notes         = request.form.get('notes', '').strip()

        errors = []
        if not property_id:
            errors.append('Property is required.')
        if not document_type:
            errors.append('Document type is required.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template('compliance/add.html',
                                   properties=properties,
                                   document_types=DOCUMENT_TYPES)

        issue_date  = None
        expiry_date = None
        if issue_str:
            try:
                issue_date = datetime.strptime(issue_str, '%Y-%m-%d').date()
            except ValueError:
                flash('Invalid issue date.', 'error')
                return render_template('compliance/add.html',
                                       properties=properties,
                                       document_types=DOCUMENT_TYPES)
        if expiry_str:
            try:
                expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d').date()
            except ValueError:
                flash('Invalid expiry date.', 'error')
                return render_template('compliance/add.html',
                                       properties=properties,
                                       document_types=DOCUMENT_TYPES)

        # Handle file upload
        file_path = None
        uploaded_file = request.files.get('document_file')
        if uploaded_file and uploaded_file.filename:
            if not allowed_file(uploaded_file.filename):
                flash('Only PDF, JPG and PNG files are allowed.', 'error')
                return render_template('compliance/add.html',
                                       properties=properties,
                                       document_types=DOCUMENT_TYPES)
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            filename = secure_filename(
                f'prop{property_id}_{document_type.replace(" ","_")}'
                f'_{datetime.utcnow().strftime("%Y%m%d%H%M%S")}'
                f'.{uploaded_file.filename.rsplit(".",1)[1].lower()}'
            )
            uploaded_file.save(os.path.join(UPLOAD_FOLDER, filename))
            file_path = filename

        doc = ComplianceDocument(
            property_id=int(property_id),
            user_id=current_user.id,
            document_type=document_type,
            issue_date=issue_date,
            expiry_date=expiry_date,
            renewal_years=int(renewal_years) if renewal_years else 1,
            file_path=file_path,
            notes=notes,
        )
        db.session.add(doc)
        db.session.commit()
        flash(f'{document_type} record added.', 'success')
        return redirect(url_for('compliance.index'))

    return render_template('compliance/add.html',
                           properties=properties,
                           document_types=DOCUMENT_TYPES)


# ── Edit document ─────────────────────────────────────────────────────────────

@compliance_bp.route('/<int:doc_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(doc_id):
    doc = get_doc_or_404(doc_id)
    if current_user.role == 'admin':
        properties = Property.query.order_by(Property.address_line1).all()
    else:
        properties = Property.query.filter_by(
            user_id=current_user.id
        ).order_by(Property.address_line1).all()

    if request.method == 'POST':
        doc.property_id   = int(request.form.get('property_id', doc.property_id))
        doc.document_type = request.form.get('document_type', doc.document_type).strip()
        doc.renewal_years = int(request.form.get('renewal_years', 1))
        doc.notes         = request.form.get('notes', '').strip()

        issue_str  = request.form.get('issue_date', '').strip()
        expiry_str = request.form.get('expiry_date', '').strip()

        if issue_str:
            try:
                doc.issue_date = datetime.strptime(issue_str, '%Y-%m-%d').date()
            except ValueError:
                flash('Invalid issue date.', 'error')
                return render_template('compliance/edit.html',
                                       doc=doc, properties=properties,
                                       document_types=DOCUMENT_TYPES)
        if expiry_str:
            try:
                doc.expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d').date()
            except ValueError:
                flash('Invalid expiry date.', 'error')
                return render_template('compliance/edit.html',
                                       doc=doc, properties=properties,
                                       document_types=DOCUMENT_TYPES)

        # Handle replacement file upload
        uploaded_file = request.files.get('document_file')
        if uploaded_file and uploaded_file.filename:
            if allowed_file(uploaded_file.filename):
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                filename = secure_filename(
                    f'prop{doc.property_id}_{doc.document_type.replace(" ","_")}'
                    f'_{datetime.utcnow().strftime("%Y%m%d%H%M%S")}'
                    f'.{uploaded_file.filename.rsplit(".",1)[1].lower()}'
                )
                uploaded_file.save(os.path.join(UPLOAD_FOLDER, filename))
                doc.file_path = filename

        db.session.commit()
        flash(f'{doc.document_type} updated.', 'success')
        return redirect(url_for('compliance.index'))

    return render_template('compliance/edit.html',
                           doc=doc,
                           properties=properties,
                           document_types=DOCUMENT_TYPES)


# ── Delete document ───────────────────────────────────────────────────────────

@compliance_bp.route('/<int:doc_id>/delete', methods=['POST'])
@login_required
def delete(doc_id):
    doc = get_doc_or_404(doc_id)
    # Remove file if exists
    if doc.file_path:
        full_path = os.path.join(UPLOAD_FOLDER, doc.file_path)
        if os.path.exists(full_path):
            os.remove(full_path)
    db.session.delete(doc)
    db.session.commit()
    flash('Document record deleted.', 'success')
    return redirect(url_for('compliance.index'))


# ── Download document ─────────────────────────────────────────────────────────

@compliance_bp.route('/<int:doc_id>/download')
@login_required
def download(doc_id):
    doc = get_doc_or_404(doc_id)
    if not doc.file_path:
        flash('No file attached to this record.', 'error')
        return redirect(url_for('compliance.index'))
    return send_from_directory(
        os.path.abspath(UPLOAD_FOLDER),
        doc.file_path,
        as_attachment=True
    )
