from app.auth import auth
from app.routes.analytics_routes import analytics
from app.routes.campaign_routes import campaigns
from app.routes.data_routes import data
from app.routes.dashboard_routes import dashboard
from app.routes.entity_routes import entities


def register_routes(app) -> None:
    app.register_blueprint(auth)
    app.register_blueprint(dashboard)
    app.register_blueprint(campaigns, url_prefix="/campaigns")
    app.register_blueprint(entities)
    app.register_blueprint(analytics, url_prefix="/analytics")
    app.register_blueprint(data, url_prefix="/data")
