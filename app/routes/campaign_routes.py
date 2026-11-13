import json
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for

from app.db import get_db


campaigns = Blueprint("campaigns", __name__)


@campaigns.get("/")
def index():
    query = request.args.get("q", "").strip()
    rows = get_db().execute(
        """
        SELECT c.*, ch.name AS channel, a.name AS audience, cr.name AS creative,
               COALESCE(SUM(CASE WHEN cost.currency=? THEN cost.amount END), 0) AS spend
        FROM campaigns c JOIN channels ch USING(channel_id)
        JOIN audiences a USING(audience_id) JOIN creatives cr USING(creative_id)
        LEFT JOIN cost_records cost USING(campaign_id)
        WHERE c.campaign_id LIKE ? OR c.name LIKE ?
        GROUP BY c.campaign_id ORDER BY c.start_date DESC, c.campaign_id LIMIT 500
        """,
        (current_app.config["BASE_CURRENCY"], f"%{query}%", f"%{query}%"),
    ).fetchall()
    masters = {
        "channels": get_db().execute("SELECT * FROM channels ORDER BY name").fetchall(),
        "audiences": get_db().execute("SELECT * FROM audiences ORDER BY name").fetchall(),
        "creatives": get_db().execute("SELECT * FROM creatives ORDER BY name").fetchall(),
    }
    return render_template("campaigns/list.html", campaigns=rows, masters=masters, query=query)


@campaigns.post("/")
def create():
    form = request.form
    try:
        budget = Decimal(form.get("budget_amount", ""))
        actual_spend = Decimal(form["actual_spend"]) if form.get("actual_spend", "").strip() else None
        start = date.fromisoformat(form.get("start_date", ""))
        end = date.fromisoformat(form.get("end_date", ""))
        if budget < 0 or (actual_spend is not None and actual_spend < 0) or start > end:
            raise ValueError("Budget must be non-negative and the end date cannot precede the start date.")
        if not form.get("name", "").strip():
            raise ValueError("Campaign name is required.")
        connection = get_db()
        next_number = connection.execute(
            "SELECT COALESCE(MAX(CAST(substr(campaign_id, 10) AS INTEGER)), 0) + 1 FROM campaigns"
        ).fetchone()[0]
        campaign_id = f"CMP-2026-{next_number:06d}"
        campaign_snapshot = {
            "campaign_id": campaign_id,
            "name": form["name"].strip(),
            "channel_id": form["channel_id"],
            "audience_id": form["audience_id"],
            "creative_id": form["creative_id"],
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "budget_amount": str(budget),
            "budget_currency": current_app.config["BASE_CURRENCY"],
            "status": "completed" if end < date.today() else "active",
        }
        connection.execute(
            """INSERT INTO campaigns
               (campaign_id,name,channel_id,audience_id,creative_id,start_date,end_date,budget_amount,budget_currency,status)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                campaign_id, campaign_snapshot["name"], form["channel_id"], form["audience_id"],
                form["creative_id"], start.isoformat(), end.isoformat(), str(budget),
                current_app.config["BASE_CURRENCY"], campaign_snapshot["status"],
            ),
        )
        connection.execute(
            "INSERT INTO campaign_events VALUES (?,?,?,?,?)",
            (
                f"CME-APP-{campaign_id}-000001",
                campaign_id,
                "campaign_created",
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                json.dumps({"after": campaign_snapshot}, sort_keys=True),
            ),
        )
        if actual_spend is not None:
            connection.execute(
                "INSERT INTO cost_records (cost_record_id,campaign_id,incurred_date,amount,currency,cost_type) VALUES (?,?,?,?,?,?)",
                (
                    f"COST-APP-{campaign_id}",
                    campaign_id,
                    end.isoformat(),
                    str(actual_spend),
                    current_app.config["BASE_CURRENCY"],
                    "campaign_spend",
                ),
            )
        connection.commit()
        flash(f"Created campaign {campaign_id}.", "success")
    except (ValueError, InvalidOperation, KeyError) as error:
        get_db().rollback()
        flash(str(error), "danger")
    except sqlite3.IntegrityError as error:
        get_db().rollback()
        flash(f"Campaign could not be saved: {error}.", "danger")
    return redirect(url_for("campaigns.index"))


@campaigns.route("/<campaign_id>/edit", methods=["GET", "POST"])
def edit(campaign_id: str):
    connection = get_db()
    existing = connection.execute("SELECT * FROM campaigns WHERE campaign_id=?", (campaign_id,)).fetchone()
    if existing is None:
        abort(404)
    if request.method == "GET":
        return render_template("campaigns/edit.html", campaign=existing)
    try:
        name = request.form.get("name", "").strip()
        budget = Decimal(request.form.get("budget_amount", ""))
        if not name or budget < 0:
            raise ValueError("Campaign name is required and budget cannot be negative.")
        before = dict(existing)
        connection.execute(
            "UPDATE campaigns SET name=?, budget_amount=? WHERE campaign_id=?",
            (name, str(budget), campaign_id),
        )
        after = {**before, "name": name, "budget_amount": str(budget)}
        revision_number = connection.execute(
            "SELECT COUNT(*) + 1 FROM campaign_events WHERE campaign_id=?", (campaign_id,)
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO campaign_events VALUES (?,?,?,?,?)",
            (
                f"CME-APP-{campaign_id}-{revision_number:06d}",
                campaign_id,
                "campaign_revised",
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                json.dumps({"before": before, "after": after}, sort_keys=True),
            ),
        )
        connection.commit()
        flash(f"Updated {campaign_id}; the prior campaign values remain in event history.", "success")
    except (ValueError, InvalidOperation) as error:
        connection.rollback()
        flash(str(error), "danger")
    return redirect(url_for("campaigns.detail", campaign_id=campaign_id))


@campaigns.get("/<campaign_id>")
def detail(campaign_id: str):
    row = get_db().execute(
        """
        SELECT c.*, ch.name AS channel, a.name AS audience, cr.name AS creative
        FROM campaigns c JOIN channels ch USING(channel_id)
        JOIN audiences a USING(audience_id) JOIN creatives cr USING(creative_id)
        WHERE c.campaign_id=?
        """, (campaign_id,),
    ).fetchone()
    if row is None:
        abort(404)
    costs = get_db().execute(
        "SELECT * FROM cost_records WHERE campaign_id=? ORDER BY incurred_date", (campaign_id,)
    ).fetchall()
    metrics = get_db().execute(
        "SELECT * FROM campaign_metrics WHERE campaign_id=? ORDER BY model,evaluation_period",
        (campaign_id,),
    ).fetchall()
    events = get_db().execute(
        "SELECT * FROM campaign_events WHERE campaign_id=? ORDER BY occurred_at,campaign_event_id",
        (campaign_id,),
    ).fetchall()
    return render_template("campaigns/detail.html", campaign=row, costs=costs, metrics=metrics, events=events)
