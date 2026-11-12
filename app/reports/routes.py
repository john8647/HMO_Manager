from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, Response)
from flask_login import login_required, current_user
from app.utils import landlord_required
from datetime import date
from app.models import Property, Transaction, Expense
from app.reports.quickfile import (build_quickfile_csv,
                                    build_retained_deposit_rows,
                                    get_tax_year_dates)

reports_bp = Blueprint('reports', __name__)


@reports_bp.route('/')
@login_required
@landlord_required
def index():
    if current_user.role == 'admin':
        properties = Property.query.order_by(Property.address_line1).all()
    else:
        properties = Property.query.filter_by(
            user_id=current_user.id
        ).order_by(Property.address_line1).all()

    current_year = date.today().year
    tax_years    = list(range(2024, current_year + 2))

    return render_template('reports/index.html',
                           properties=properties,
                           tax_years=tax_years,
                           current_year=current_year)


@reports_bp.route('/quickfile/export')
@login_required
@landlord_required
def quickfile_export():
    property_id    = request.args.get('property_id')
    tax_year       = request.args.get('tax_year', type=int)
    sort_code      = request.args.get('sort_code', '').strip()
    account_num    = request.args.get('account_number', '').strip()

    if not property_id or not tax_year:
        flash('Please select a property and tax year.', 'error')
        return redirect(url_for('reports.index'))

    prop = Property.query.filter_by(
        id=int(property_id), user_id=current_user.id
    ).first_or_404()

    period_start, period_end = get_tax_year_dates(tax_year)

    # ── Credits: matched bank import transactions for this user ──────────
    # Exclude internal system debits and deposit credits
    # The quickfile builder handles all filtering internally
    transactions = Transaction.query.filter(
        Transaction.user_id == current_user.id,
        Transaction.transaction_date >= period_start,
        Transaction.transaction_date <= period_end,
        Transaction.is_matched == True,
    ).order_by(Transaction.transaction_date).all()

    # ── Debits: expenses for this property only ──────────────────────────
    expenses = Expense.query.filter(
        Expense.user_id == current_user.id,
        Expense.property_id == int(property_id),
        Expense.expense_date >= period_start,
        Expense.expense_date <= period_end,
    ).order_by(Expense.expense_date).all()

    csv_content = build_quickfile_csv(
        transactions=transactions,
        expenses=expenses,
        prop=prop,
        sort_code=sort_code,
        account_number=account_num,
        period_start=period_start,
        period_end=period_end,
    )

    # Append any retained deposit rows (genuine income)
    deposit_rows = build_retained_deposit_rows(
        user_id=current_user.id,
        property_id=int(property_id),
        period_start=period_start,
        period_end=period_end,
        sort_code=sort_code,
        account_number=account_num,
    )

    if deposit_rows:
        import csv as csv_mod
        import io
        extra = io.StringIO()
        writer = csv_mod.writer(extra, lineterminator='\r\n')
        for row in sorted(deposit_rows, key=lambda r: r['date']):
            writer.writerow([
                row['date'].strftime('%d/%m/%Y'),
                row['type'],
                row['sort_code'],
                row['account'],
                row['description'],
                row['debit'],
                row['credit'],
            ])
        csv_content = csv_content.rstrip('\r\n') + '\r\n' + extra.getvalue()

    filename = (
        f'QuickFile_{prop.property_ref or prop.id}'
        f'_TaxYear{tax_year-1}-{tax_year}.csv'
    )

    return Response(
        csv_content,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )
