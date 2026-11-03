from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from config import config

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()


def create_app(config_name='default'):
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'

    from app.auth.routes import auth_bp
    from app.dashboard.routes import dashboard_bp
    from app.properties.routes import properties_bp
    from app.tenants.routes import tenants_bp
    from app.bills.routes import bills_bp
    from app.invoices.routes import invoices_bp
    from app.transactions.routes import transactions_bp
    from app.expenses.routes import expenses_bp
    from app.reports.routes import reports_bp
    from app.compliance.routes import compliance_bp
    from app.tasks.routes import tasks_bp
    from app.deposits.routes import deposits_bp
    from app.portal.routes import portal_bp
    from app.admin.routes import admin_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(dashboard_bp, url_prefix='/')
    app.register_blueprint(properties_bp, url_prefix='/properties')
    app.register_blueprint(tenants_bp, url_prefix='/tenants')
    app.register_blueprint(bills_bp, url_prefix='/bills')
    app.register_blueprint(invoices_bp, url_prefix='/invoices')
    app.register_blueprint(transactions_bp, url_prefix='/transactions')
    app.register_blueprint(expenses_bp, url_prefix='/expenses')
    app.register_blueprint(reports_bp, url_prefix='/reports')
    app.register_blueprint(compliance_bp, url_prefix='/compliance')
    app.register_blueprint(tasks_bp, url_prefix='/tasks')
    app.register_blueprint(deposits_bp, url_prefix='/deposits')
    app.register_blueprint(portal_bp, url_prefix='/portal')
    app.register_blueprint(admin_bp, url_prefix='/admin')

    return app
