from flask import current_app

from app.db import dataframe, get_db
from generate import TABLE_COLUMNS


MODELS = ("first_touch", "last_touch", "linear")
PERIODS = ("train", "validation", "test")


def dashboard_summary() -> dict:
    connection = get_db()
    counts = {
        "campaigns": connection.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0],
        "contacts": connection.execute("SELECT COUNT(*) FROM contacts").fetchone()[0],
        "leads": connection.execute("SELECT COUNT(*) FROM leads").fetchone()[0],
        "opportunities": connection.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0],
        "closed_won": connection.execute("SELECT COUNT(*) FROM opportunities WHERE status='closed_won'").fetchone()[0],
    }
    base_currency = current_app.config["BASE_CURRENCY"]
    revenue = connection.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM "
        "(SELECT opportunity_id, MAX(revenue_amount) AS amount FROM orders "
        "WHERE status='closed' AND currency=? GROUP BY opportunity_id)",
        (base_currency,),
    ).fetchone()[0]
    costs = connection.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM cost_records WHERE currency=?", (base_currency,)
    ).fetchone()[0]
    roi = ((float(revenue) - float(costs)) / float(costs) * 100) if costs else None
    exception_count = (
        connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        - connection.execute("SELECT COUNT(DISTINCT opportunity_id) FROM orders").fetchone()[0]
    )
    return {
        **counts,
        "revenue": float(revenue),
        "spend": float(costs),
        "roi_percent": roi,
        "duplicate_orders": exception_count,
        "currency": base_currency,
    }


def campaign_performance(model: str = "linear", period: str = "test", limit: int = 100) -> list[dict]:
    if model not in MODELS or period not in PERIODS:
        raise ValueError("Unsupported attribution model or evaluation period.")
    frame = dataframe(
        """
        SELECT c.campaign_id, c.name, ch.name AS channel, m.attributed_revenue,
               m.attributed_conversions, m.spend_base_currency, m.cost_status, m.roi
        FROM campaigns c
        JOIN channels ch ON ch.channel_id=c.channel_id
        JOIN campaign_metrics m ON m.campaign_id=c.campaign_id
        WHERE m.model=? AND m.evaluation_period=?
        ORDER BY m.attributed_revenue DESC, c.campaign_id
        LIMIT ?
        """,
        (model, period, limit),
    )
    frame = frame.astype(object).where(frame.notna(), None)
    return frame.to_dict(orient="records")


def channel_performance(model: str = "linear", period: str = "test") -> list[dict]:
    if model not in MODELS or period not in PERIODS:
        raise ValueError("Unsupported attribution model or evaluation period.")
    frame = dataframe(
        """
        SELECT ch.channel_id, ch.name AS channel,
               SUM(m.attributed_revenue) AS attributed_revenue,
               SUM(m.attributed_conversions) AS attributed_conversions,
               SUM(m.spend_base_currency) AS spend_base_currency
        FROM campaign_metrics m
        JOIN campaigns c ON c.campaign_id=m.campaign_id
        JOIN channels ch ON ch.channel_id=c.channel_id
        WHERE m.model=? AND m.evaluation_period=?
        GROUP BY ch.channel_id, ch.name ORDER BY attributed_revenue DESC
        """,
        (model, period),
    )
    output = []
    for row in frame.to_dict(orient="records"):
        revenue = float(row["attributed_revenue"] or 0)
        spend = float(row["spend_base_currency"] or 0)
        row["roi"] = (revenue - spend) / spend if spend else None
        row["attributed_revenue"] = revenue
        row["spend_base_currency"] = spend
        output.append(row)
    return output


def model_comparison(period: str = "test", limit: int = 12) -> dict:
    if period not in PERIODS:
        raise ValueError("Unsupported evaluation period.")
    output = {}
    for model in MODELS:
        output[model] = campaign_performance(model, period, limit)
    return output


def known_exceptions() -> list[dict]:
    import csv
    from pathlib import Path

    path = Path(current_app.config["DATASET_DIR"]) / "ground_truth.csv"
    if not path.is_file():
        return []
    with path.open("r", newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def attribution_coverage() -> dict:
    connection = get_db()
    total = connection.execute("SELECT COUNT(*) FROM opportunities WHERE status='closed_won'").fetchone()[0]
    covered = connection.execute(
        "SELECT COUNT(DISTINCT opportunity_id) FROM attribution_results"
    ).fetchone()[0]
    return {"won_opportunities": total, "attributed_opportunities": covered,
            "coverage_percent": round(covered / total * 100, 2) if total else 0}


def validation_summary() -> dict:
    connection = get_db()
    foreign_keys = [dict(row) for row in connection.execute("PRAGMA foreign_key_check").fetchall()]
    primary_key_duplicates = 0
    for table, columns in TABLE_COLUMNS.items():
        primary_key = columns[0]
        primary_key_duplicates += connection.execute(
            f"SELECT COUNT(*) FROM (SELECT {primary_key} FROM {table} GROUP BY {primary_key} HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        primary_key_duplicates += connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {primary_key} IS NULL OR {primary_key}=''"
        ).fetchone()[0]
    revenue = connection.execute(
        "SELECT SUM(revenue_amount) FROM "
        "(SELECT opportunity_id, MAX(revenue_amount) AS revenue_amount FROM orders GROUP BY opportunity_id)"
    ).fetchone()[0] or 0
    attribution = connection.execute(
        "SELECT model, SUM(attributed_revenue) AS revenue FROM attribution_results GROUP BY model"
    ).fetchall()
    reconciliation = {row["model"]: abs(float(row["revenue"] or 0) - float(revenue)) < 0.02 for row in attribution}
    checks = {
        "foreign_key_violations": len(foreign_keys),
        "primary_key_duplicates": primary_key_duplicates,
        "canonical_order_revenue": float(revenue),
        "attribution_reconciles": reconciliation,
        "attribution_coverage": attribution_coverage(),
    }
    checks["passed"] = (
        checks["foreign_key_violations"] == 0
        and checks["primary_key_duplicates"] == 0
        and all(reconciliation.values())
    )
    return checks


def journey_for_contact(contact_id: str) -> dict | None:
    contact = get_db().execute("SELECT * FROM contacts WHERE contact_id=?", (contact_id,)).fetchone()
    if contact is None:
        return None
    connection = get_db()
    touches = [dict(row) for row in connection.execute(
        """
        SELECT t.touchpoint_id AS id, t.occurred_at AS occurred_at, 'touchpoint' AS event_type,
               c.name AS label, ch.name AS detail
        FROM touchpoints t JOIN campaigns c USING(campaign_id) JOIN channels ch USING(channel_id)
        WHERE t.contact_id=?
        """, (contact_id,),
    ).fetchall()]
    sales = connection.execute(
        """
        SELECT l.lead_id, l.created_at AS lead_created, l.status AS lead_status,
               o.opportunity_id, o.created_at AS opportunity_created, o.closed_at, o.status AS opportunity_status,
               o.estimated_amount, ord.order_id, ord.ordered_at, ord.revenue_amount, ord.currency AS order_currency
        FROM leads l LEFT JOIN opportunities o USING(lead_id)
        LEFT JOIN orders ord ON ord.opportunity_id=o.opportunity_id AND ord.status='closed'
        WHERE l.contact_id=? ORDER BY l.created_at
        """, (contact_id,),
    ).fetchall()
    for row in sales:
        touches.append({"id": row["lead_id"], "occurred_at": row["lead_created"], "event_type": "lead", "label": "Lead created", "detail": row["lead_status"]})
        if row["opportunity_id"]:
            touches.append({"id": row["opportunity_id"], "occurred_at": row["opportunity_created"], "event_type": "opportunity", "label": "Opportunity created", "detail": row["opportunity_status"]})
        if row["ordered_at"]:
            touches.append({"id": row["order_id"], "occurred_at": row["ordered_at"], "event_type": "order", "label": "Purchase completed", "detail": f"{row['revenue_amount']} {row['order_currency']}"})
    touches.sort(key=lambda row: (row["occurred_at"], row["id"]))
    return {"contact": dict(contact), "events": touches, "sales": [dict(row) for row in sales]}
