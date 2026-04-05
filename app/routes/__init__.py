def register_routes(app):
    from app.routes.urls import urls_bp
    from app.routes.users import users_bp
    from app.routes.stats import stats_bp
    from app.routes.events import events_bp

    # JSON API
    app.register_blueprint(urls_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(events_bp)
