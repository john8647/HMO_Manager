from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, Response)
from flask_login import login_required, current_user
from datetime import datetime
from decimal import Decimal
from app import db
from app.models import (Transaction, BankImport, BankImportRow,
                        TransactionLegend, Tenant, Property,
                        PicklistCharge, PicklistPaymentType, TenantContract)
from app.transactions.importer import parse_bank_csv, auto_match_rows

transactions_bp = Blueprint('transactions', __name__)


# ── Ledger ───────────────────────────────────────────────────────────────────

@transactions_bp.route('/')
@login_required
def index():
    if current_user.role == 'admin':
        transactions = Transaction.query.order_by(
            Transaction.transaction_date.desc()
        ).limit(200).all()
    else:
        transactions = Transaction.query.filter_by(
            user_id=current_user.id
        ).order_by(Transaction.transaction_date.desc()).limit(200).all()

    # Totals summary
    credits = sum(
        t.amount for t in transactions if t.credit_debit == 'cr'
    )
    debits = sum(
        t.amount for t in transactions if t.credit_debit == 'db'
    )

    return render_template('transactions/index.html',
                           transactions=transactions,
                           credits=credits,
                           debits=debits)


# ── Manual transaction entry ──────────────────────────────────────────────────

@transactions_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if current_user.role == 'admin':
        tenants = Tenant.query.order_by(Tenant.last_name).all()
    else:
        tenants = Tenant.query.filter_by(
            user_id=current_user.id
        ).order_by(Tenant.last_name).all()

    charge_types = PicklistCharge.query.order_by(
        PicklistCharge.charge_name).all()

    if request.method == 'POST':
        tenant_id = request.form.get('tenant_id') or None
        amount_str = request.form.get('amount', '').strip()
        credit_debit = request.form.get('credit_debit', 'cr')
        date_str = request.form.get('transaction_date', '').strip()
        type_ = request.form.get('type', '').strip()
        charge_type_id = request.form.get('charge_type_id') or None
        notes = request.form.get('notes', '').strip()
        source = request.form.get('source', 'manual')

        errors = []
        if not amount_str:
            errors.append('Amount is required.')
        if not date_str:
            errors.append('Date is required.')
        if not type_:
            errors.append('Transaction type is required.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template('transactions/add.html',
                                   tenants=tenants,
                                   charge_types=charge_types)

        try:
            amount = Decimal(amount_str)
            trans_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid amount or date.', 'error')
            return render_template('transactions/add.html',
                                   tenants=tenants,
                                   charge_types=charge_types)

        month_year = trans_date.strftime('%B %Y')

        # Dual-entry: credit line
        cr = Transaction(
            tenant_id=int(tenant_id) if tenant_id else None,
            amount=amount,
            credit_debit='cr',
            transaction_date=trans_date,
            user_id=current_user.id,
            type=type_,
            charge_type_id=int(charge_type_id) if charge_type_id else None,
            month_year_period=month_year,
            source=source,
            is_matched=True,
            notes=notes,
        )
        # Dual-entry: debit line
        db_ = Transaction(
            tenant_id=int(tenant_id) if tenant_id else None,
            amount=amount,
            credit_debit='db',
            transaction_date=trans_date,
            user_id=current_user.id,
            type=type_,
            charge_type_id=int(charge_type_id) if charge_type_id else None,
            month_year_period=month_year,
            source=source,
            is_matched=True,
            notes=notes,
        )
        db.session.add(cr)
        db.session.add(db_)
        db.session.commit()

        flash(
            f'Transaction recorded — £{amount} {credit_debit} ({type_}).', 'success')
        return redirect(url_for('transactions.index'))

    return render_template('transactions/add.html',
                           tenants=tenants,
                           charge_types=charge_types)


# ── Bank CSV import ───────────────────────────────────────────────────────────

@transactions_bp.route('/import', methods=['GET', 'POST'])
@login_required
def import_csv():
    if request.method == 'POST':
        uploaded = request.files.get('csv_file')
        if not uploaded or not uploaded.filename.endswith('.csv'):
            flash('Please upload a valid CSV file.', 'error')
            return render_template('transactions/import.html')

        try:
            content = uploaded.stream.read().decode('utf-8-sig')
        except UnicodeDecodeError:
            content = uploaded.stream.read().decode('latin-1')

        try:
            rows = parse_bank_csv(content)
        except ValueError as e:
            flash(f'CSV format error: {e}', 'error')
            return render_template('transactions/import.html')

        if not rows:
            flash('No rows found in CSV file.', 'error')
            return render_template('transactions/import.html')

        # Load legend for auto-matching
        legends = TransactionLegend.query.filter_by(
            user_id=current_user.id
        ).all()
        rows = auto_match_rows(rows, legends)

        # Create import batch record
        bank_import = BankImport(
            user_id=current_user.id,
            filename=uploaded.filename,
            row_count=len(rows),
            matched_count=sum(1 for r in rows if r['match_status'] == 'auto'),
            unmatched_count=sum(
                1 for r in rows if r['match_status'] == 'unmatched'),
        )
        db.session.add(bank_import)
        db.session.flush()

        # Save all rows
        for row in rows:
            bir = BankImportRow(
                import_id=bank_import.id,
                transaction_date=row['transaction_date'],
                transaction_type=row.get('transaction_type', ''),
                sort_code=row.get('sort_code', ''),
                account_number=row.get('account_number', ''),
                description=row['description'],
                debit_amount=row.get('debit_amount'),
                credit_amount=row.get('credit_amount'),
                match_status=row['match_status'],
            )
            db.session.add(bir)

        db.session.commit()
        flash(
            f'Imported {len(rows)} rows — '
            f'{bank_import.matched_count} auto-matched, '
            f'{bank_import.unmatched_count} need review.',
            'success'
        )
        return redirect(url_for('transactions.match', import_id=bank_import.id))

    return render_template('transactions/import.html')


# ── Match / review import ─────────────────────────────────────────────────────

@transactions_bp.route('/match/<int:import_id>', methods=['GET', 'POST'])
@login_required
def match(import_id):
    bank_import = BankImport.query.filter_by(
        id=import_id, user_id=current_user.id
    ).first_or_404()

    rows = BankImportRow.query.filter_by(
        import_id=import_id
    ).order_by(BankImportRow.transaction_date.desc()).all()

    tenants = Tenant.query.filter_by(
        user_id=current_user.id
    ).order_by(Tenant.last_name).all()

    charge_types = PicklistCharge.query.order_by(
        PicklistCharge.charge_name).all()

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'confirm_all':
            # Confirm all auto-matched rows and create transactions
            confirmed = 0
            for row in rows:
                if row.match_status == 'auto' and not row.transaction_id:
                    _create_transaction_from_row(row)
                    confirmed += 1
            db.session.commit()
            flash(f'{confirmed} auto-matched transactions confirmed.', 'success')
            return redirect(url_for('transactions.match', import_id=import_id))

        elif action == 'manual_match':
            row_id = request.form.get('row_id')
            tenant_id = request.form.get('tenant_id') or None
            type_ = request.form.get('type', '').strip()
            charge_id = request.form.get('charge_type_id') or None
            notes = request.form.get('notes', '').strip()

            row = BankImportRow.query.get_or_404(int(row_id))
            row.match_status = 'manual'
            _create_transaction_from_row(
                row,
                tenant_id=int(tenant_id) if tenant_id else None,
                type_=type_,
                charge_type_id=int(charge_id) if charge_id else None,
                notes=notes,
            )
            db.session.commit()
            flash('Row manually matched and transaction created.', 'success')
            return redirect(url_for('transactions.match', import_id=import_id))

        elif action == 'split':
            # Split one row into two transactions
            row_id = request.form.get('row_id')
            row = BankImportRow.query.get_or_404(int(row_id))

            split1_amount = request.form.get('split1_amount', '').strip()
            split1_type = request.form.get('split1_type', '').strip()
            split1_tenant = request.form.get('split1_tenant_id') or None
            split2_amount = request.form.get('split2_amount', '').strip()
            split2_type = request.form.get('split2_type', '').strip()
            split2_tenant = request.form.get('split2_tenant_id') or None

            try:
                amt1 = Decimal(split1_amount)
                amt2 = Decimal(split2_amount)
            except Exception:
                flash('Invalid split amounts.', 'error')
                return redirect(url_for('transactions.match', import_id=import_id))

            total = row.credit_amount or row.debit_amount or Decimal('0')
            if abs((amt1 + amt2) - total) > Decimal('0.02'):
                flash(
                    f'Split amounts £{amt1} + £{amt2} = £{amt1+amt2} '
                    f'do not match row total £{total}.', 'error'
                )
                return redirect(url_for('transactions.match', import_id=import_id))

            month_year = row.transaction_date.strftime('%B %Y')
            cd = 'cr' if row.credit_amount else 'db'

            for amt, type_, tid in [
                (amt1, split1_type, split1_tenant),
                (amt2, split2_type, split2_tenant),
            ]:
                t = Transaction(
                    tenant_id=int(tid) if tid else None,
                    amount=amt,
                    credit_debit=cd,
                    transaction_date=row.transaction_date,
                    user_id=current_user.id,
                    type=type_,
                    month_year_period=month_year,
                    source='bank_import',
                    bank_import_id=import_id,
                    is_matched=True,
                    notes=f'{row.description} {type_}',
                )
                db.session.add(t)

            row.match_status = 'split'
            db.session.commit()
            flash(
                f'Row split into two transactions of £{amt1} and £{amt2}.', 'success')
            return redirect(url_for('transactions.match', import_id=import_id))

        elif action == 'skip':
            row_id = request.form.get('row_id')
            row = BankImportRow.query.get_or_404(int(row_id))
            row.match_status = 'skipped'
            db.session.commit()
            flash('Row skipped.', 'success')
            return redirect(url_for('transactions.match', import_id=import_id))

    unmatched = [r for r in rows if r.match_status in ('unmatched',)]
    auto = [r for r in rows if r.match_status == 'auto']
    confirmed = [r for r in rows if r.match_status in (
        'manual', 'split') or r.transaction_id]
    skipped = [r for r in rows if r.match_status == 'skipped']

    return render_template('transactions/match.html',
                           bank_import=bank_import,
                           rows=rows,
                           unmatched=unmatched,
                           auto=auto,
                           confirmed=confirmed,
                           skipped=skipped,
                           tenants=tenants,
                           charge_types=charge_types)


def _create_transaction_from_row(row, tenant_id=None, type_=None,
                                 charge_type_id=None, notes=None):
    """Create a Transaction record from a BankImportRow."""
    amount = row.credit_amount or row.debit_amount or Decimal('0')
    cd = 'cr' if row.credit_amount else 'db'
    month_year = row.transaction_date.strftime('%B %Y')

    t = Transaction(
        tenant_id=tenant_id,
        amount=amount,
        credit_debit=cd,
        transaction_date=row.transaction_date,
        user_id=row.import_batch.user_id,
        type=type_ or row.income_type if hasattr(
            row, 'income_type') else type_,
        charge_type_id=charge_type_id,
        month_year_period=month_year,
        source='bank_import',
        bank_import_id=row.import_id,
        is_matched=True,
        notes=notes or row.description,
    )
    db.session.add(t)
    db.session.flush()
    row.transaction_id = t.id
    return t


# ── Transaction Legend (auto-match rules) ─────────────────────────────────────

@transactions_bp.route('/legend')
@login_required
def legend():
    legends = TransactionLegend.query.filter_by(
        user_id=current_user.id
    ).order_by(TransactionLegend.description_pattern).all()

    tenants = Tenant.query.filter_by(
        user_id=current_user.id, is_active=True
    ).order_by(Tenant.last_name).all()

    return render_template('transactions/legend.html',
                           legends=legends,
                           tenants=tenants)


@transactions_bp.route('/legend/add', methods=['POST'])
@login_required
def legend_add():
    pattern = request.form.get('description_pattern', '').strip().upper()
    tenant_id = request.form.get('tenant_id') or None
    income_type = request.form.get('income_type', '').strip()
    expense_type = request.form.get('expense_type', '').strip()
    preferred = request.form.get('preferred_description', '').strip()

    if not pattern:
        flash('Description pattern is required.', 'error')
        return redirect(url_for('transactions.legend'))

    existing = TransactionLegend.query.filter_by(
        user_id=current_user.id,
        description_pattern=pattern
    ).first()
    if existing:
        flash(f'Pattern "{pattern}" already exists.', 'error')
        return redirect(url_for('transactions.legend'))

    legend = TransactionLegend(
        user_id=current_user.id,
        description_pattern=pattern,
        tenant_id=int(tenant_id) if tenant_id else None,
        income_type=income_type,
        expense_type=expense_type,
        preferred_description=preferred,
    )
    db.session.add(legend)
    db.session.commit()
    flash(f'Legend rule added for "{pattern}".', 'success')
    return redirect(url_for('transactions.legend'))


@transactions_bp.route('/legend/<int:legend_id>/delete', methods=['POST'])
@login_required
def legend_delete(legend_id):
    leg = TransactionLegend.query.filter_by(
        id=legend_id, user_id=current_user.id
    ).first_or_404()
    db.session.delete(leg)
    db.session.commit()
    flash('Legend rule deleted.', 'success')
    return redirect(url_for('transactions.legend'))


# ── Import history ────────────────────────────────────────────────────────────

@transactions_bp.route('/imports')
@login_required
def imports():
    all_imports = BankImport.query.filter_by(
        user_id=current_user.id
    ).order_by(BankImport.import_date.desc()).all()
    return render_template('transactions/imports.html', imports=all_imports)
