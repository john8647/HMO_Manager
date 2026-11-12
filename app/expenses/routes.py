from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.utils import landlord_required
from datetime import datetime
from decimal import Decimal
from app import db
from app.models import Expense, Property, PicklistCharge, Transaction

expenses_bp = Blueprint('expenses', __name__)


def get_expense_or_404(expense_id):
    return Expense.query.filter_by(
        id=expense_id, user_id=current_user.id
    ).first_or_404()


# ── List ──────────────────────────────────────────────────────────────────────

@expenses_bp.route('/')
@login_required
@landlord_required
def index():
    if current_user.role == 'admin':
        properties = Property.query.order_by(Property.address_line1).all()
        expenses = Expense.query.order_by(
            Expense.expense_date.desc()
        ).limit(200).all()
    else:
        properties = Property.query.filter_by(
            user_id=current_user.id
        ).order_by(Property.address_line1).all()
        expenses = Expense.query.filter_by(
            user_id=current_user.id
        ).order_by(Expense.expense_date.desc()).limit(200).all()

    # Property filter
    filter_property = request.args.get('property_id')
    if filter_property:
        expenses = [e for e in expenses
                    if str(e.property_id) == filter_property]

    # Totals
    total = sum(e.amount for e in expenses)

    # Group by HMRC category for summary
    by_category = {}
    for e in expenses:
        cat = e.charge_type.hmrc_category if e.charge_type else 'Uncategorised'
        name = e.charge_type.charge_name if e.charge_type else 'Uncategorised'
        key = name
        by_category[key] = by_category.get(key, Decimal('0')) + Decimal(str(e.amount))

    return render_template('expenses/index.html',
                           expenses=expenses,
                           properties=properties,
                           filter_property=filter_property,
                           total=total,
                           by_category=by_category)


# ── Add ───────────────────────────────────────────────────────────────────────

@expenses_bp.route('/add', methods=['GET', 'POST'])
@login_required
@landlord_required
def add():
    if current_user.role == 'admin':
        properties = Property.query.order_by(Property.address_line1).all()
    else:
        properties = Property.query.filter_by(
            user_id=current_user.id
        ).order_by(Property.address_line1).all()

    charge_types = PicklistCharge.query.order_by(PicklistCharge.charge_name).all()

    if request.method == 'POST':
        property_id    = request.form.get('property_id') or None
        charge_type_id = request.form.get('charge_type_id') or None
        description    = request.form.get('description', '').strip()
        amount_str     = request.form.get('amount', '').strip()
        date_str       = request.form.get('expense_date', '').strip()
        source         = request.form.get('source', 'manual')
        notes          = request.form.get('notes', '').strip()
        create_transaction = request.form.get('create_transaction') == 'on'

        errors = []
        if not description:
            errors.append('Description is required.')
        if not amount_str:
            errors.append('Amount is required.')
        if not date_str:
            errors.append('Date is required.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template('expenses/add.html',
                                   properties=properties,
                                   charge_types=charge_types)

        try:
            amount = Decimal(amount_str)
            expense_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid amount or date.', 'error')
            return render_template('expenses/add.html',
                                   properties=properties,
                                   charge_types=charge_types)

        expense = Expense(
            user_id=current_user.id,
            property_id=int(property_id) if property_id else None,
            charge_type_id=int(charge_type_id) if charge_type_id else None,
            description=description,
            amount=amount,
            expense_date=expense_date,
            source=source,
            notes=notes,
        )
        db.session.add(expense)
        db.session.flush()

        # Optionally create a debit transaction in the ledger
        if create_transaction:
            month_year = expense_date.strftime('%B %Y')

            # Debit (money out)
            t_db = Transaction(
                amount=amount,
                credit_debit='db',
                transaction_date=expense_date,
                user_id=current_user.id,
                type=expense.charge_type.charge_name if expense.charge_type else 'Expense',
                charge_type_id=int(charge_type_id) if charge_type_id else None,
                month_year_period=month_year,
                source=source,
                is_matched=True,
                notes=description,
            )
            db.session.add(t_db)

        db.session.commit()

        msg = f'Expense "{description}" £{amount} recorded.'
        if create_transaction:
            msg += ' Debit transaction added to ledger.'
        flash(msg, 'success')
        return redirect(url_for('expenses.index'))

    return render_template('expenses/add.html',
                           properties=properties,
                           charge_types=charge_types)


# ── Edit ──────────────────────────────────────────────────────────────────────

@expenses_bp.route('/<int:expense_id>/edit', methods=['GET', 'POST'])
@login_required
@landlord_required
def edit(expense_id):
    expense = get_expense_or_404(expense_id)
    if current_user.role == 'admin':
        properties = Property.query.order_by(Property.address_line1).all()
    else:
        properties = Property.query.filter_by(
            user_id=current_user.id
        ).order_by(Property.address_line1).all()

    charge_types = PicklistCharge.query.order_by(PicklistCharge.charge_name).all()

    if request.method == 'POST':
        expense.property_id    = request.form.get('property_id') or None
        expense.charge_type_id = request.form.get('charge_type_id') or None
        expense.description    = request.form.get('description', '').strip()
        expense.source         = request.form.get('source', 'manual')
        expense.notes          = request.form.get('notes', '').strip()

        amount_str = request.form.get('amount', '').strip()
        date_str   = request.form.get('expense_date', '').strip()

        if not expense.description or not amount_str or not date_str:
            flash('Description, amount and date are required.', 'error')
            return render_template('expenses/edit.html',
                                   expense=expense,
                                   properties=properties,
                                   charge_types=charge_types)

        try:
            expense.amount       = Decimal(amount_str)
            expense.expense_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid amount or date.', 'error')
            return render_template('expenses/edit.html',
                                   expense=expense,
                                   properties=properties,
                                   charge_types=charge_types)

        if expense.property_id:
            expense.property_id = int(expense.property_id)
        if expense.charge_type_id:
            expense.charge_type_id = int(expense.charge_type_id)

        db.session.commit()
        flash('Expense updated.', 'success')
        return redirect(url_for('expenses.index'))

    return render_template('expenses/edit.html',
                           expense=expense,
                           properties=properties,
                           charge_types=charge_types)


# ── Delete ────────────────────────────────────────────────────────────────────

@expenses_bp.route('/<int:expense_id>/delete', methods=['POST'])
@login_required
@landlord_required
def delete(expense_id):
    expense = get_expense_or_404(expense_id)
    db.session.delete(expense)
    db.session.commit()
    flash('Expense deleted.', 'success')
    return redirect(url_for('expenses.index'))
