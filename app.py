import os
from flask import Flask
from flask_login import LoginManager


def create_app():
    app = Flask(__name__)
    app.config.from_object('config.ActiveConfig')

    # Ensure upload directory exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Initialize database
    from blog import init_db, db
    init_db(app)

    # Initialize login manager
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'admin.login'
    login_manager.login_message = '\u8bf7\u5148\u767b\u5f55'

    from blog.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Register blueprints
    from blog import blog_bp, admin_bp
    app.register_blueprint(blog_bp)
    app.register_blueprint(admin_bp)

    return app


if __name__ == '__main__':
    app = create_app()
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)
