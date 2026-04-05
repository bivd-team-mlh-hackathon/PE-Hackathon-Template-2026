def register_routes(app):
    from app.routes.events import events_bp
    from app.routes.frontend import frontend_bp
    from app.routes.urls import urls_bp
    from app.routes.users import users_bp
    from app.routes.stats import stats_bp

    # JSON API — register first so they take priority over frontend for
    # overlapping GET /users, GET /urls, etc.
    app.register_blueprint(urls_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(stats_bp)

    # Frontend (Jinja2 templates) — prefix with /view to avoid route conflicts
    app.register_blueprint(frontend_bp, url_prefix="/view")
