from flask import Blueprint, abort, render_template, request

from app.db import get_db
from app.services.analytics import journey_for_contact


entities = Blueprint("entities", __name__)
ENTITY_PAGES = {
    "contacts": ("Contact directory", "contacts", "contact_id, created_date, region, consent_status, lifecycle_state"),
    "leads": ("Lead pipeline", "leads", "lead_id, contact_id, created_at, lead_score, status"),
    "opportunities": ("Opportunities", "opportunities", "opportunity_id, lead_id, contact_id, created_at, closed_at, status, estimated_amount, currency"),
    "orders": ("Orders and revenue", "orders", "order_id, opportunity_id, ordered_at, revenue_amount, currency, status"),
    "touchpoints": ("Recent touchpoints", "touchpoints", "touchpoint_id, contact_id, campaign_id, channel_id, occurred_at, touch_type"),
}


@entities.get("/<entity>")
def list_entity(entity: str):
    config = ENTITY_PAGES.get(entity)
    if config is None:
        abort(404)
    title, table, columns = config
    search = request.args.get("q", "").strip()
    fields = columns.split(", ")
    where = " OR ".join(f"{field} LIKE ?" for field in fields)
    rows = get_db().execute(
        f"SELECT {columns} FROM {table} WHERE {where} ORDER BY 1 DESC LIMIT 300",
        tuple(f"%{search}%" for _ in fields),
    ).fetchall()
    return render_template("entities/list.html", title=title, entity=entity, rows=rows, columns=fields, query=search)


@entities.get("/contacts/<contact_id>/journey")
def contact_journey(contact_id: str):
    journey = journey_for_contact(contact_id)
    if journey is None:
        abort(404)
    return render_template("entities/journey.html", **journey)
