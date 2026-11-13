from flask import Blueprint, render_template

from app.services.analytics import dashboard_summary, model_comparison, validation_summary


dashboard = Blueprint("dashboard", __name__)


@dashboard.get("/")
def index():
    return render_template(
        "dashboard/index.html",
        summary=dashboard_summary(),
        comparison=model_comparison("test", 8),
        validation=validation_summary(),
    )
