from pathlib import Path

from flask import Flask

from config import Config, ROOT


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_path=str(ROOT / "instance"), instance_relative_config=True)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    from app.db import init_app, initialize_database

    init_app(app)
    with app.app_context():
        if app.config.get("AUTO_INIT_DB", True):
            initialize_database()
        from app.auth import ensure_auth_schema

        ensure_auth_schema()

    from app.routes import register_routes

    register_routes(app)
    return app
