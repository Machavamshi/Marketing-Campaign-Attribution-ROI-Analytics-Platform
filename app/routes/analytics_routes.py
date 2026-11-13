from flask import Blueprint, abort, jsonify, render_template, request

from app.services.analytics import (
    PERIODS,
    attribution_coverage,
    campaign_performance,
    channel_performance,
    model_comparison,
)


analytics = Blueprint("analytics", __name__)


def selected_period() -> str:
    period = request.args.get("period", "test")
    if period not in PERIODS:
        abort(400, description="period must be train, validation, or test.")
    return period


@analytics.get("/")
def comparison():
    period = selected_period()
    return render_template(
        "analytics/comparison.html",
        period=period,
        models=model_comparison(period),
        channels=channel_performance(period=period),
        coverage=attribution_coverage(),
    )


@analytics.get("/campaign-roi")
def campaign_roi():
    model = request.args.get("model", "linear")
    period = selected_period()
    if model not in {"first_touch", "last_touch", "linear"}:
        abort(400, description="model must be first_touch, last_touch, or linear.")
    rows = campaign_performance(model, period, 100)
    return render_template("analytics/roi.html", rows=rows, model=model, period=period)


@analytics.get("/api/comparison")
def comparison_api():
    period = selected_period()
    return jsonify({"period": period, "models": model_comparison(period), "channels": channel_performance(period=period)})


@analytics.get("/api/roi")
def roi_api():
    model = request.args.get("model", "linear")
    if model not in {"first_touch", "last_touch", "linear"}:
        abort(400, description="model must be first_touch, last_touch, or linear.")
    return jsonify({"model": model, "period": selected_period(), "campaigns": campaign_performance(model, selected_period())})
