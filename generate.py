#!/usr/bin/env python3
"""Generate a deterministic synthetic campaign-attribution dataset."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from faker import Faker

SEED = 20261022
RULE_VERSION = "attribution-v1"
BASE_CURRENCY = "INR"
START_DATE = date(2026, 1, 1)
END_DATE = date(2026, 12, 31)
SCALE = {
    "starter": {"campaigns": 50, "contacts": 5_000, "touchpoints": 20_000, "opportunities": 1_000},
    "full": {"campaigns": 500, "contacts": 50_000, "touchpoints": 200_000, "opportunities": 10_000},
}
CHANNELS = [
    ("CH-001", "Email", "digital"),
    ("CH-002", "Paid Search", "digital"),
    ("CH-003", "Organic Search", "digital"),
    ("CH-004", "Social", "digital"),
    ("CH-005", "Webinar", "digital"),
    ("CH-006", "Display", "digital"),
    ("CH-007", "Direct Mail", "offline"),
    ("CH-008", "Field Sales", "offline"),
]


# Format a monetary value as a two-decimal string.
def money(value: Decimal | float | int) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# Convert a date and minute offset to a UTC ISO timestamp.
def iso_datetime(day: date, minute: int = 0) -> str:
    return (datetime.combine(day, datetime.min.time(), timezone.utc) + timedelta(minutes=minute)).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


# Write table rows to a UTF-8 CSV file and return the number of rows written.
def csv_write(path: Path, rows: Iterable[dict[str, Any]], columns: list[str]) -> int:
    count = 0
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: "" if row.get(column) is None else row.get(column) for column in columns})
            count += 1
    return count


TABLE_COLUMNS: dict[str, list[str]] = {
    "channels": ["channel_id", "name", "channel_type"],
    "audiences": ["audience_id", "name", "segment"],
    "creatives": ["creative_id", "name", "format", "status"],
    "campaigns": ["campaign_id", "name", "channel_id", "audience_id", "creative_id", "start_date", "end_date", "budget_amount", "budget_currency", "status"],
    "campaign_events": ["campaign_event_id", "campaign_id", "event_type", "occurred_at", "details_json"],
    "contacts": ["contact_id", "created_date", "region", "consent_status", "lifecycle_state"],
    "contact_audiences": ["contact_audience_id", "contact_id", "audience_id", "valid_from", "valid_to"],
    "touchpoints": ["touchpoint_id", "contact_id", "campaign_id", "channel_id", "creative_id", "occurred_at", "touch_type", "source"],
    "web_sessions": ["session_id", "contact_id", "touchpoint_id", "lead_id", "opportunity_id", "started_at", "pages_viewed", "session_type"],
    "leads": ["lead_id", "contact_id", "source_session_id", "created_at", "lead_score", "status"],
    "lead_events": ["lead_event_id", "lead_id", "from_status", "to_status", "changed_at", "reason"],
    "opportunities": ["opportunity_id", "lead_id", "contact_id", "created_at", "closed_at", "status", "estimated_amount", "currency"],
    "opportunity_events": ["opportunity_event_id", "opportunity_id", "from_status", "to_status", "changed_at", "reason"],
    "orders": ["order_id", "opportunity_id", "ordered_at", "revenue_amount", "currency", "status"],
    "cost_records": ["cost_record_id", "campaign_id", "incurred_date", "amount", "currency", "cost_type"],
    "attribution_results": ["attribution_result_id", "opportunity_id", "campaign_id", "model", "credit_weight", "attributed_revenue", "conversion_date", "evaluation_period", "rule_version"],
    "campaign_metrics": ["campaign_metric_id", "campaign_id", "model", "evaluation_period", "attributed_revenue", "attributed_conversions", "spend_base_currency", "cost_status", "roi"],
}


# Build the channels, audiences, creatives, and campaigns used by the dataset.
def make_master_data(
    rng: random.Random, campaign_count: int, fake: Faker
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    channels = [
        {"channel_id": key, "name": name, "channel_type": kind}
        for key, name, kind in CHANNELS
    ]
    audiences = [
        {"audience_id": f"AUD-{i:03d}", "name": f"Audience {i:03d}", "segment": ["SMB", "Enterprise", "Mid-market", "New prospects"][i % 4]}
        for i in range(1, 21)
    ]
    creatives = [
        {"creative_id": f"CRE-{i:04d}", "name": f"Creative {i:04d}", "format": ["email", "video", "banner", "webinar", "direct_mail"][i % 5], "status": "active"}
        for i in range(1, max(100, min(500, campaign_count)) + 1)
    ]
    campaigns = []
    for i in range(1, campaign_count + 1):
        start = START_DATE + timedelta(days=rng.randrange(0, 301))
        end = min(start + timedelta(days=rng.randrange(180, 301)), END_DATE)
        if i == 1:
            start, end = START_DATE, END_DATE
        channel = channels[(i - 1) % len(channels)]
        campaigns.append({
            "campaign_id": f"CMP-2026-{i:06d}",
            "name": f"{fake.catch_phrase()} · {channel['name']} {i:04d}",
            "channel_id": channel["channel_id"],
            "audience_id": f"AUD-{rng.randint(1, 20):03d}",
            "creative_id": f"CRE-{rng.randint(1, len(creatives)):04d}",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "budget_amount": money(rng.randint(10_000, 250_000)),
            "budget_currency": BASE_CURRENCY,
            "status": "completed" if end < END_DATE else "active",
        })
    return channels, audiences, creatives, campaigns


# Assign a conversion date to the train, validation, or test period.
def evaluation_period(day: date) -> str:
    if day <= date(2026, 6, 30):
        return "train"
    if day <= date(2026, 9, 30):
        return "validation"
    return "test"


# Calculate first-touch, last-touch, and linear credit for won opportunities.
def attribution_rows(
    opportunities: list[dict[str, Any]],
    touches_by_contact: dict[str, list[tuple[str, str, str]]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for opp in opportunities:
        if opp["status"] != "closed_won":
            continue
        converted = datetime.fromisoformat(opp["closed_at"].replace("Z", "+00:00"))
        eligible = [
            (touch_id, campaign_id, datetime.fromisoformat(occurred.replace("Z", "+00:00")))
            for touch_id, campaign_id, occurred in touches_by_contact[opp["contact_id"]]
            if datetime.fromisoformat(occurred.replace("Z", "+00:00")) <= converted
        ]
        eligible.sort(key=lambda item: (item[2], item[0]))
        if not eligible:
            raise ValueError(f"Won opportunity has no eligible touchpoint: {opp['opportunity_id']}")
        grouped: dict[str, int] = {}
        for _, campaign_id, _ in eligible:
            grouped[campaign_id] = grouped.get(campaign_id, 0) + 1
        first_campaign = eligible[0][1]
        last_campaign = eligible[-1][1]
        total_touches = len(eligible)
        revenue = Decimal(opp["estimated_amount"])
        period = evaluation_period(converted.date())
        allocations = {
            "first_touch": {first_campaign: Decimal("1")},
            "last_touch": {last_campaign: Decimal("1")},
            "linear": {campaign_id: Decimal(count) / Decimal(total_touches) for campaign_id, count in grouped.items()},
        }
        for model in ("first_touch", "last_touch", "linear"):
            shares = list(allocations[model].items())
            rounded: list[tuple[str, Decimal, Decimal]] = []
            allocated = Decimal("0")
            assigned_weight = Decimal("0")
            for index, (campaign_id, weight) in enumerate(shares):
                amount = revenue - allocated if index == len(shares) - 1 else (revenue * weight).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                allocated += amount
                stored_weight = (
                    Decimal("1") - assigned_weight
                    if index == len(shares) - 1
                    else weight.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
                )
                assigned_weight += stored_weight
                rounded.append((campaign_id, stored_weight, amount))
            for campaign_id, weight, amount in rounded:
                results.append({
                    "attribution_result_id": f"ATTR-{len(results) + 1:09d}",
                    "opportunity_id": opp["opportunity_id"],
                    "campaign_id": campaign_id,
                    "model": model,
                    "credit_weight": str(weight),
                    "attributed_revenue": money(amount),
                    "conversion_date": converted.date().isoformat(),
                    "evaluation_period": period,
                    "rule_version": RULE_VERSION,
                })
    return results


# Describe the deliberate data-quality cases included in the generated dataset.
def ground_truth_rows(
    duplicate_order_id: str,
    duplicate_original_order_id: str,
    duplicate_opportunity_id: str,
    future_touch: tuple[str, str],
    currency_record_id: str,
    currency_campaign: str,
    omitted_campaign: str,
    anonymous_session: str,
    anonymous_lead: str,
) -> list[dict[str, Any]]:
    return [
        {"case_id": "GT-001", "issue_type": "duplicate_revenue", "source_table": "orders", "source_record_ids": duplicate_order_id, "related_record_ids": f"{duplicate_original_order_id};{duplicate_opportunity_id}", "expected_decision": "Treat the repeated order for the same opportunity as a duplicate; count canonical opportunity revenue once.", "severity": "high"},
        {"case_id": "GT-002", "issue_type": "post_conversion_touch", "source_table": "touchpoints", "source_record_ids": future_touch[0], "related_record_ids": future_touch[1], "expected_decision": "Exclude this touchpoint because it occurred after the opportunity conversion timestamp.", "severity": "medium"},
        {"case_id": "GT-003", "issue_type": "currency_mismatch", "source_table": "cost_records", "source_record_ids": currency_record_id, "related_record_ids": currency_campaign, "expected_decision": f"Do not include the non-{BASE_CURRENCY} cost in {BASE_CURRENCY} spend or ROI without a documented FX rate.", "severity": "high"},
        {"case_id": "GT-004", "issue_type": "omitted_campaign_cost", "source_table": "campaigns", "source_record_ids": omitted_campaign, "expected_decision": "Report ROI as unavailable; do not infer missing spend as zero.", "severity": "medium"},
        {"case_id": "GT-005", "issue_type": "anonymous_session_link", "source_table": "web_sessions", "source_record_ids": anonymous_session, "related_record_ids": anonymous_lead, "expected_decision": "Flag the session-to-lead link as unsupported because contact and touchpoint evidence are absent.", "severity": "high"},
    ]


# Check generated records for valid keys, relationships, histories, and totals.
def validate_rows(tables: dict[str, list[dict[str, Any]]], results: list[dict[str, Any]], orders: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    checks = Counter()
    id_fields = {name: columns[0] for name, columns in TABLE_COLUMNS.items()}
    for table, rows in tables.items():
        ids = [row[id_fields[table]] for row in rows]
        checks["primary_key_rows_checked"] += len(ids)
        if len(ids) != len(set(ids)):
            errors.append(f"{table}: duplicate primary keys")

    indexes = {
        table: {row[TABLE_COLUMNS[table][0]] for row in rows}
        for table, rows in tables.items()
    }

    # Check that each required foreign-key value exists in its parent table.
    def fk(table: str, field: str, parent: str, optional: bool = False) -> None:
        for row in tables[table]:
            value = row.get(field)
            checks["foreign_key_values_checked"] += 1
            if (value is None or value == "") and optional:
                continue
            if value not in indexes[parent]:
                errors.append(f"{table}.{field}: missing parent {value}")
                return

    for table, field, parent, optional in [
        ("campaigns", "channel_id", "channels", False),
        ("campaigns", "audience_id", "audiences", False),
        ("campaigns", "creative_id", "creatives", False),
        ("campaign_events", "campaign_id", "campaigns", False),
        ("contact_audiences", "contact_id", "contacts", False),
        ("contact_audiences", "audience_id", "audiences", False),
        ("touchpoints", "contact_id", "contacts", False),
        ("touchpoints", "campaign_id", "campaigns", False),
        ("touchpoints", "channel_id", "channels", False),
        ("touchpoints", "creative_id", "creatives", False),
        ("web_sessions", "contact_id", "contacts", True),
        ("web_sessions", "touchpoint_id", "touchpoints", True),
        ("web_sessions", "lead_id", "leads", True),
        ("web_sessions", "opportunity_id", "opportunities", True),
        ("leads", "contact_id", "contacts", False),
        ("leads", "source_session_id", "web_sessions", False),
        ("lead_events", "lead_id", "leads", False),
        ("opportunities", "lead_id", "leads", False),
        ("opportunities", "contact_id", "contacts", False),
        ("opportunity_events", "opportunity_id", "opportunities", False),
        ("orders", "opportunity_id", "opportunities", False),
        ("cost_records", "campaign_id", "campaigns", False),
        ("attribution_results", "opportunity_id", "opportunities", False),
        ("attribution_results", "campaign_id", "campaigns", False),
        ("campaign_metrics", "campaign_id", "campaigns", False),
    ]:
        fk(table, field, parent, optional)

    for row in tables["touchpoints"]:
        if row["occurred_at"][:10] < START_DATE.isoformat() or row["occurred_at"][:10] > END_DATE.isoformat():
            errors.append(f"touchpoints: timestamp outside configured range {row['touchpoint_id']}")
            break
    status_values = {"closed_won", "closed_lost", "qualified"}
    for row in tables["opportunities"]:
        if row["status"] not in status_values:
            errors.append(f"opportunities: invalid status {row['status']}")
        if row["status"] == "closed_won" and not row["closed_at"]:
            errors.append(f"opportunities: closed_won missing closed_at {row['opportunity_id']}")
    canonical = {}
    for order in orders:
        canonical.setdefault(order["opportunity_id"], Decimal(order["revenue_amount"]))
    expected_revenue = sum(canonical.values(), Decimal("0"))
    by_model = defaultdict(Decimal)
    for result in results:
        by_model[result["model"]] += Decimal(result["attributed_revenue"])
    checks["attribution_reconciliation_models_checked"] = len(by_model)
    for model, total in by_model.items():
        if total != expected_revenue:
            errors.append(f"{model}: attributed revenue {total} != canonical order revenue {expected_revenue}")
    checks["duplicate_orders_detected"] = len(orders) - len(canonical)
    campaigns = {row["campaign_id"]: row for row in tables["campaigns"]}
    contacts = {row["contact_id"]: row for row in tables["contacts"]}
    channels = {row["channel_id"]: row for row in tables["channels"]}
    touchpoints = {row["touchpoint_id"]: row for row in tables["touchpoints"]}
    sessions = {row["session_id"]: row for row in tables["web_sessions"]}
    leads = {row["lead_id"]: row for row in tables["leads"]}
    opportunities = {row["opportunity_id"]: row for row in tables["opportunities"]}

    # Check that lifecycle events form a valid sequence ending at the row status.
    def validate_history(
        event_table: str,
        parent_table: str,
        parent_id_field: str,
        status_field: str,
        allowed_statuses: set[str],
    ) -> None:
        histories: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in tables[event_table]:
            histories[event[parent_id_field]].append(event)
        for parent_id, parent in {row[TABLE_COLUMNS[parent_table][0]]: row for row in tables[parent_table]}.items():
            history = sorted(histories[parent_id], key=lambda row: (row["changed_at"], row[TABLE_COLUMNS[event_table][0]]))
            previous = None
            previous_time = ""
            for event in history:
                checks["lifecycle_transitions_checked"] += 1
                if event["from_status"] != previous or event["to_status"] not in allowed_statuses:
                    errors.append(f"{event_table}: invalid transition {event[TABLE_COLUMNS[event_table][0]]}")
                if previous_time and event["changed_at"] < previous_time:
                    errors.append(f"{event_table}: non-monotonic event time {event[TABLE_COLUMNS[event_table][0]]}")
                if previous is None and event["to_status"] != "new":
                    errors.append(f"{event_table}: history must begin in new state {parent_id}")
                elif previous is not None and previous != "new":
                    errors.append(f"{event_table}: transition after terminal state {parent_id}")
                previous = event["to_status"]
                previous_time = event["changed_at"]
            if not history or previous != parent[status_field]:
                errors.append(f"{event_table}: final history state does not match {parent_id}")

    validate_history("lead_events", "leads", "lead_id", "status", {"new", "qualified", "converted", "disqualified"})
    validate_history("opportunity_events", "opportunities", "opportunity_id", "status", {"new", "closed_won", "closed_lost", "qualified"})

    for campaign in campaigns.values():
        checks["campaign_date_ranges_checked"] += 1
        if campaign["start_date"] > campaign["end_date"]:
            errors.append(f"campaigns: start after end {campaign['campaign_id']}")
    for touch in tables["touchpoints"]:
        campaign = campaigns[touch["campaign_id"]]
        contact = contacts[touch["contact_id"]]
        touch_day = touch["occurred_at"][:10]
        checks["touchpoint_date_and_channel_rules_checked"] += 1
        if touch_day < contact["created_date"] or not campaign["start_date"] <= touch_day <= campaign["end_date"]:
            errors.append(f"touchpoints: invalid contact/campaign date ordering {touch['touchpoint_id']}")
        if touch["channel_id"] != campaign["channel_id"] or touch["creative_id"] != campaign["creative_id"]:
            errors.append(f"touchpoints: campaign channel/creative mismatch {touch['touchpoint_id']}")
        expected_type = "offline" if channels[touch["channel_id"]]["channel_type"] == "offline" else "online"
        if touch["touch_type"] != expected_type:
            errors.append(f"touchpoints: channel type mismatch {touch['touchpoint_id']}")
    for session in tables["web_sessions"]:
        if session["touchpoint_id"]:
            touch = touchpoints[session["touchpoint_id"]]
            checks["session_time_orderings_checked"] += 1
            if session["started_at"] < touch["occurred_at"]:
                errors.append(f"web_sessions: started before touchpoint {session['session_id']}")
            if session["contact_id"] and session["contact_id"] != touch["contact_id"]:
                errors.append(f"web_sessions: contact does not match touchpoint {session['session_id']}")
    for lead in tables["leads"]:
        session = sessions[lead["source_session_id"]]
        checks["lead_source_orderings_checked"] += 1
        if lead["created_at"] < session["started_at"]:
            errors.append(f"leads: created before source session {lead['lead_id']}")
        if session["contact_id"] and session["contact_id"] != lead["contact_id"]:
            errors.append(f"leads: contact does not match identified session {lead['lead_id']}")
    for opportunity in tables["opportunities"]:
        lead = leads[opportunity["lead_id"]]
        checks["opportunity_lifecycle_checked"] += 1
        if lead["contact_id"] != opportunity["contact_id"] or opportunity["created_at"] < lead["created_at"]:
            errors.append(f"opportunities: lead/contact/date mismatch {opportunity['opportunity_id']}")
        if opportunity["closed_at"] and opportunity["closed_at"] < opportunity["created_at"]:
            errors.append(f"opportunities: closed before creation {opportunity['opportunity_id']}")
    for cost in tables["cost_records"]:
        campaign = campaigns[cost["campaign_id"]]
        checks["cost_date_ranges_checked"] += 1
        if not campaign["start_date"] <= cost["incurred_date"] <= campaign["end_date"]:
            errors.append(f"cost_records: incurred outside campaign {cost['cost_record_id']}")
    for order in orders:
        opportunity = opportunities[order["opportunity_id"]]
        checks["order_reconciliations_checked"] += 1
        if opportunity["status"] != "closed_won" or order["ordered_at"] != opportunity["closed_at"]:
            errors.append(f"orders: opportunity lifecycle/date mismatch {order['order_id']}")
        if Decimal(order["revenue_amount"]) != Decimal(opportunity["estimated_amount"]) or order["currency"] != opportunity["currency"]:
            errors.append(f"orders: amount/currency mismatch {order['order_id']}")
    weights = defaultdict(Decimal)
    revenue_by_metric_key = defaultdict(Decimal)
    for result in results:
        key = (result["opportunity_id"], result["model"])
        weights[key] += Decimal(result["credit_weight"])
        metric_key = (result["campaign_id"], result["model"], result["evaluation_period"])
        revenue_by_metric_key[metric_key] += Decimal(result["attributed_revenue"])
        opp = opportunities[result["opportunity_id"]]
        if opp["status"] != "closed_won" or result["conversion_date"] != opp["closed_at"][:10]:
            errors.append(f"attribution_results: conversion mismatch {result['attribution_result_id']}")
        if result["evaluation_period"] != evaluation_period(date.fromisoformat(result["conversion_date"])):
            errors.append(f"attribution_results: period mismatch {result['attribution_result_id']}")
    checks["attribution_weight_groups_checked"] = len(weights)
    for key, weight in weights.items():
        if weight != Decimal("1"):
            errors.append(f"attribution_results: weights do not sum to one for {key}")
    for metric in tables["campaign_metrics"]:
        key = (metric["campaign_id"], metric["model"], metric["evaluation_period"])
        if Decimal(metric["attributed_revenue"]) != revenue_by_metric_key[key]:
            errors.append(f"campaign_metrics: revenue mismatch for {key}")
    cost_by_campaign = {row["campaign_id"]: row for row in tables["cost_records"]}
    metrics_by_campaign_model: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for metric in tables["campaign_metrics"]:
        metrics_by_campaign_model[(metric["campaign_id"], metric["model"])].append(metric)
    for (campaign_id, model), rows in metrics_by_campaign_model.items():
        cost = cost_by_campaign.get(campaign_id)
        if cost and cost["currency"] == BASE_CURRENCY:
            spent = sum((Decimal(row["spend_base_currency"]) for row in rows if row["spend_base_currency"] is not None), Decimal("0"))
            if spent != Decimal(cost["amount"]):
                errors.append(f"campaign_metrics: spend does not reconcile for {campaign_id}/{model}")
        elif any(row["spend_base_currency"] is not None or row["roi"] is not None for row in rows):
            errors.append(f"campaign_metrics: invalid ROI for unavailable cost {campaign_id}/{model}")
    return {"passed": not errors, "checks": dict(checks), "errors": errors, "canonical_closed_won_revenue": money(expected_revenue)}


# Generate, validate, and export a deterministic dataset and its manifest.
def generate_dataset(output: Path, counts: dict[str, int], seed: int = SEED) -> dict[str, Any]:
    if any(value <= 0 for value in counts.values()):
        raise ValueError("All scale counts must be greater than zero.")
    if counts["campaigns"] < 2 or counts["contacts"] < 2 or counts["touchpoints"] <= counts["contacts"] or counts["opportunities"] < 2:
        raise ValueError("Use at least two campaigns/contacts/opportunities and more touchpoints than contacts.")
    output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    fake = Faker()
    fake.seed_instance(seed)
    numpy_rng = np.random.default_rng(seed)
    channels, audiences, creatives, campaigns = make_master_data(rng, counts["campaigns"], fake)
    campaign_events = [
        {
            "campaign_event_id": f"CME-2026-{index:06d}",
            "campaign_id": campaign["campaign_id"],
            "event_type": "campaign_created",
            "occurred_at": f"{campaign['start_date']}T00:00:00Z",
            "details_json": json.dumps(campaign, sort_keys=True),
        }
        for index, campaign in enumerate(campaigns, 1)
    ]
    channel_by_id = {row["channel_id"]: row for row in channels}

    contacts = []
    for i in range(1, counts["contacts"] + 1):
        contacts.append({
            "contact_id": f"CON-{i:07d}",
            "created_date": (START_DATE + timedelta(days=rng.randrange(0, 91))).isoformat(),
            "region": str(numpy_rng.choice(["NA", "EMEA", "APAC", "LATAM"], p=[0.38, 0.29, 0.21, 0.12])),
            "consent_status": ["granted", "granted", "granted", "withdrawn"][rng.randrange(4)],
            "lifecycle_state": "customer" if i % 5 == 0 else "prospect",
        })
    contact_ids = [row["contact_id"] for row in contacts]
    touch_counts: Counter[str] = Counter()
    touch_by_contact: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    touch_rows: list[dict[str, Any]] = []
    # Create one touchpoint and index it under the contact for attribution.
    def add_touch(contact_id: str, campaign: dict[str, Any]) -> None:
        touch_counts[contact_id] += 1
        contact = contacts[int(contact_id[-7:]) - 1]
        lower = max(date.fromisoformat(campaign["start_date"]), date.fromisoformat(contact["created_date"]))
        upper = date.fromisoformat(campaign["end_date"])
        when = lower + timedelta(days=rng.randrange((upper - lower).days + 1))
        touch_id = f"TOUCH-{contact_id}-{touch_counts[contact_id]:06d}"
        channel_id = campaign["channel_id"]
        channel_type = channel_by_id[channel_id]["channel_type"]
        creative_id = campaign["creative_id"]
        occurred_at = iso_datetime(when, rng.randrange(1440))
        row = {
            "touchpoint_id": touch_id,
            "contact_id": contact_id,
            "campaign_id": campaign["campaign_id"],
            "channel_id": channel_id,
            "creative_id": creative_id,
            "occurred_at": occurred_at,
            "touch_type": "offline" if channel_type == "offline" else "online",
            "source": "field_sales" if channel_id == "CH-008" else ("direct_mail" if channel_id == "CH-007" else "campaign"),
        }
        touch_rows.append(row)
        touch_by_contact[contact_id].append((touch_id, campaign["campaign_id"], occurred_at))

    for contact_id in contact_ids:
        add_touch(contact_id, campaigns[rng.randrange(len(campaigns))])
    for _ in range(counts["touchpoints"] - 1 - len(contacts)):
        add_touch(contact_ids[rng.randrange(len(contact_ids))], campaigns[rng.randrange(len(campaigns))])

    audience_rows = []
    for i, contact in enumerate(contacts, 1):
        audience_rows.append({
            "contact_audience_id": f"CA-{i:07d}",
            "contact_id": contact["contact_id"],
            "audience_id": f"AUD-{rng.randint(1, 20):03d}",
            "valid_from": contact["created_date"],
            "valid_to": None,
        })

    sessions: list[dict[str, Any]] = []
    leads: list[dict[str, Any]] = []
    lead_events: list[dict[str, Any]] = []
    opportunities: list[dict[str, Any]] = []
    opportunity_events: list[dict[str, Any]] = []
    orders: list[dict[str, Any]] = []
    lead_sequence = 0
    opportunity_contacts = [contact_ids[i % len(contact_ids)] for i in range(counts["opportunities"])]
    rng.shuffle(opportunity_contacts)
    anonymous_session_id = ""
    anonymous_lead_id = ""
    for i, contact_id in enumerate(opportunity_contacts, 1):
        touch_journey = sorted(touch_by_contact[contact_id], key=lambda item: (item[2], item[0]))
        anchor = touch_journey[rng.randrange(len(touch_journey))]
        anchor_day = date.fromisoformat(anchor[2][:10])
        converted_day = min(anchor_day + timedelta(days=rng.randrange(1, 181)), END_DATE)
        conversion_minute = 1439 if converted_day == END_DATE else 720
        conversion_dt = datetime.combine(converted_day, datetime.min.time(), timezone.utc) + timedelta(minutes=conversion_minute)
        eligible = [item for item in touch_journey if datetime.fromisoformat(item[2].replace("Z", "+00:00")) <= conversion_dt]
        campaign_count = len({item[1] for item in eligible})
        session_id = f"SES-2026-{i:06d}"
        lead_id = f"LEAD-2026-{i:06d}"
        pages = rng.randint(1, 10)
        session_touch = eligible[-1] if eligible else anchor
        sessions.append({
            "session_id": session_id,
            "contact_id": contact_id,
            "touchpoint_id": session_touch[0],
            "lead_id": lead_id,
            "opportunity_id": f"OPP-2026-{i:06d}",
            "started_at": session_touch[2],
            "pages_viewed": pages,
            "session_type": "identified",
        })
        score = min(100, 15 + min(40, len(eligible) * 7) + min(20, campaign_count * 5) + min(20, pages * 2))
        status = "closed_won" if score >= 70 else ("qualified" if score >= 40 else "closed_lost")
        lead_status = "converted" if status == "closed_won" else ("qualified" if score >= 40 else "disqualified")
        lead_sequence += 1
        lead_created = session_touch[2]
        leads.append({
            "lead_id": lead_id, "contact_id": contact_id, "source_session_id": session_id,
            "created_at": lead_created, "lead_score": score, "status": lead_status,
        })
        lead_events.append({
            "lead_event_id": f"LE-{lead_sequence:09d}-001", "lead_id": lead_id,
            "from_status": None, "to_status": "new", "changed_at": lead_created, "reason": "lead_created",
        })
        if lead_status != "new":
            lead_events.append({
                "lead_event_id": f"LE-{lead_sequence:09d}-002", "lead_id": lead_id,
                "from_status": "new", "to_status": lead_status,
                "changed_at": iso_datetime(converted_day, conversion_minute), "reason": "derived_from_journey_score",
            })
        amount = Decimal(500 + ((i * 7919) % 49_500)).quantize(Decimal("0.01"))
        opportunity_id = f"OPP-2026-{i:06d}"
        closed_at = iso_datetime(converted_day, conversion_minute) if status in {"closed_won", "closed_lost"} else None
        opportunities.append({
            "opportunity_id": opportunity_id, "lead_id": lead_id, "contact_id": contact_id,
            "created_at": lead_created, "closed_at": closed_at, "status": status,
            "estimated_amount": money(amount), "currency": BASE_CURRENCY,
        })
        opportunity_events.append({
            "opportunity_event_id": f"OE-{i:06d}-001", "opportunity_id": opportunity_id,
            "from_status": None, "to_status": "new", "changed_at": lead_created, "reason": "opportunity_created",
        })
        if status != "new":
            opportunity_events.append({
                "opportunity_event_id": f"OE-{i:06d}-002", "opportunity_id": opportunity_id,
                "from_status": "new", "to_status": status,
                "changed_at": closed_at or lead_created, "reason": "derived_from_lead_score",
            })
        if status == "closed_won":
            orders.append({
                "order_id": f"ORD-2026-{len(orders) + 1:06d}", "opportunity_id": opportunity_id,
                "ordered_at": closed_at, "revenue_amount": money(amount), "currency": BASE_CURRENCY,
                "status": "closed",
            })

    extra_leads = max(1, counts["opportunities"] // 10)
    for j in range(1, extra_leads + 1):
        contact_id = contact_ids[(j * 17) % len(contact_ids)]
        journey = touch_by_contact[contact_id]
        touch = journey[0]
        lead_sequence += 1
        lead_id = f"LEAD-2026-{counts['opportunities'] + j:06d}"
        session_id = f"SES-2026-{counts['opportunities'] + j:06d}"
        pages = rng.randint(1, 5)
        sessions.append({
            "session_id": session_id, "contact_id": contact_id, "touchpoint_id": touch[0],
            "lead_id": lead_id, "opportunity_id": None, "started_at": touch[2],
            "pages_viewed": pages, "session_type": "identified",
        })
        score = min(100, 15 + min(40, len(journey) * 7) + min(20, len({item[1] for item in journey}) * 5) + min(20, pages * 2))
        leads.append({
            "lead_id": lead_id, "contact_id": contact_id, "source_session_id": session_id,
            "created_at": touch[2], "lead_score": score,
            "status": "qualified" if score >= 40 else "new",
        })
        lead_events.append({
            "lead_event_id": f"LE-{lead_sequence:09d}-001", "lead_id": lead_id,
            "from_status": None, "to_status": "new", "changed_at": touch[2], "reason": "lead_created",
        })
        if score >= 40:
            lead_events.append({
                "lead_event_id": f"LE-{lead_sequence:09d}-002", "lead_id": lead_id,
                "from_status": "new", "to_status": "qualified", "changed_at": touch[2],
                "reason": "derived_from_journey_score",
            })

    anonymous_session = sessions[0]
    anonymous_session["contact_id"] = None
    anonymous_session["touchpoint_id"] = None
    anonymous_session["session_type"] = "anonymous"
    anonymous_session_id = anonymous_session["session_id"]
    anonymous_lead_id = anonymous_session["lead_id"]

    # Inject one post-conversion event after all baseline touchpoints have been generated.
    first_won = next(
        (opp for opp in opportunities if opp["status"] == "closed_won" and date.fromisoformat(opp["closed_at"][:10]) < END_DATE),
        None,
    )
    if first_won is None:
        raise ValueError("Scale/seed produced no closed-won opportunities; increase scale or change seed.")
    target_contact = first_won["contact_id"]
    touch_counts[target_contact] += 1
    future_touch_id = f"TOUCH-{target_contact}-{touch_counts[target_contact]:06d}"
    converted_day = date.fromisoformat(first_won["closed_at"][:10])
    future_day = converted_day
    future_minute = 900
    future_campaign = campaigns[0]
    touch_rows.append({
        "touchpoint_id": future_touch_id, "contact_id": target_contact,
        "campaign_id": future_campaign["campaign_id"], "channel_id": future_campaign["channel_id"],
        "creative_id": future_campaign["creative_id"], "occurred_at": iso_datetime(future_day, future_minute),
        "touch_type": "online", "source": "campaign",
    })
    touch_by_contact[target_contact].append((future_touch_id, future_campaign["campaign_id"], iso_datetime(future_day, future_minute)))

    duplicate_order_id = ""
    duplicate_original_order_id = ""
    duplicate_opportunity_id = ""
    if orders:
        original = orders[0]
        duplicate_original_order_id = original["order_id"]
        duplicate_opportunity_id = original["opportunity_id"]
        duplicate_order_id = f"ORD-2026-{len(orders) + 1:06d}"
        orders.append({**original, "order_id": duplicate_order_id})
    else:
        raise ValueError("No closed-won orders were generated.")

    cost_records = []
    omitted_campaign = campaigns[-1]["campaign_id"]
    currency_campaign = campaigns[-2]["campaign_id"]
    for campaign in campaigns:
        cost_records.append({
            "cost_record_id": f"COST-{len(cost_records) + 1:06d}",
            "campaign_id": campaign["campaign_id"],
            "incurred_date": campaign["end_date"],
            "amount": money(Decimal(campaign["budget_amount"]) * Decimal("0.8")),
            "currency": BASE_CURRENCY,
            "cost_type": "campaign_spend",
        })
    currency_record = next(row for row in cost_records if row["campaign_id"] == currency_campaign)
    currency_record["currency"] = "EUR"
    cost_records = [row for row in cost_records if row["campaign_id"] != omitted_campaign]

    attribution = attribution_rows(opportunities, touch_by_contact)
    cost_by_campaign = {row["campaign_id"]: row for row in cost_records}
    currency_record_id = cost_by_campaign[currency_campaign]["cost_record_id"]
    revenue_by_key: dict[tuple[str, str, str], Decimal] = defaultdict(Decimal)
    conversions_by_key: dict[tuple[str, str, str], Decimal] = defaultdict(Decimal)
    for row in attribution:
        key = (row["campaign_id"], row["model"], row["evaluation_period"])
        revenue_by_key[key] += Decimal(row["attributed_revenue"])
        conversions_by_key[key] += Decimal(row["credit_weight"])
    period_bounds = {
        "train": (START_DATE, date(2026, 6, 30)),
        "validation": (date(2026, 7, 1), date(2026, 9, 30)),
        "test": (date(2026, 10, 1), END_DATE),
    }
    metric_rows = []
    metric_seq = 0
    for campaign in campaigns:
        cost = cost_by_campaign.get(campaign["campaign_id"])
        if cost is None:
            cost_status, period_spend = "missing", {period: None for period in period_bounds}
        elif cost["currency"] != BASE_CURRENCY:
            cost_status, period_spend = "currency_mismatch", {period: None for period in period_bounds}
        else:
            cost_status = "available"
            campaign_start = date.fromisoformat(campaign["start_date"])
            campaign_end = date.fromisoformat(campaign["end_date"])
            total_days = Decimal((campaign_end - campaign_start).days + 1)
            active_days = {
                period: max(0, (min(campaign_end, end) - max(campaign_start, start)).days + 1)
                for period, (start, end) in period_bounds.items()
            }
            period_spend = {}
            remaining = Decimal(cost["amount"])
            active_periods = [period for period in period_bounds if active_days[period] > 0]
            for index, period in enumerate(active_periods):
                if index == len(active_periods) - 1:
                    allocated = remaining
                else:
                    allocated = (Decimal(cost["amount"]) * Decimal(active_days[period]) / total_days).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    remaining -= allocated
                period_spend[period] = allocated
            for period in period_bounds:
                period_spend.setdefault(period, Decimal("0"))
        for model in ("first_touch", "last_touch", "linear"):
            for period in ("train", "validation", "test"):
                key = (campaign["campaign_id"], model, period)
                revenue = revenue_by_key[key]
                spend = period_spend[period]
                metric_seq += 1
                roi = None if spend is None else money((revenue - spend) / spend) if spend else None
                metric_rows.append({
                    "campaign_metric_id": f"CM-{metric_seq:09d}",
                    "campaign_id": campaign["campaign_id"], "model": model, "evaluation_period": period,
                    "attributed_revenue": money(revenue),
                    "attributed_conversions": str(conversions_by_key[key].quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
                    "spend_base_currency": money(spend) if spend is not None else None,
                    "cost_status": cost_status, "roi": roi,
                })

    tables = {
        "channels": channels, "campaigns": campaigns, "campaign_events": campaign_events,
        "creatives": creatives, "audiences": audiences,
        "contacts": contacts, "contact_audiences": audience_rows, "touchpoints": touch_rows,
        "web_sessions": sessions, "leads": leads, "lead_events": lead_events,
        "opportunities": opportunities, "opportunity_events": opportunity_events, "orders": orders,
        "cost_records": cost_records, "attribution_results": attribution, "campaign_metrics": metric_rows,
    }
    truth = ground_truth_rows(
        duplicate_order_id, duplicate_original_order_id, duplicate_opportunity_id,
        (future_touch_id, first_won["opportunity_id"]), currency_record_id, currency_campaign,
        omitted_campaign, anonymous_session_id, anonymous_lead_id,
    )
    validation = validate_rows(tables, attribution, orders)
    if not validation["passed"]:
        raise ValueError("Generated data failed validation: " + "; ".join(validation["errors"][:10]))

    for name, rows in tables.items():
        csv_write(output / f"{name}.csv", rows, TABLE_COLUMNS[name])
    csv_write(output / "ground_truth.csv", truth, ["case_id", "issue_type", "source_table", "source_record_ids", "related_record_ids", "expected_decision", "severity"])
    (output / "ground_truth.json").write_text(json.dumps(truth, indent=2) + "\n", encoding="utf-8")
    (output / "validation_summary.json").write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")

    schema_path = Path(__file__).with_name("schema.sql")
    shutil.copyfile(schema_path, output / "schema.sql")
    export_seed_sql(output)

    file_manifest = {}
    row_counts = {}
    for name in TABLE_COLUMNS:
        path = output / f"{name}.csv"
        file_manifest[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        row_counts[name] = len(tables[name])
    for name in ("ground_truth.csv", "ground_truth.json", "validation_summary.json", "schema.sql", "seed.sql"):
        path = output / name
        file_manifest[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "dataset": "synthetic_campaign_attribution",
        "seed": seed,
        "base_currency": BASE_CURRENCY,
        "date_range": {"start": START_DATE.isoformat(), "end": END_DATE.isoformat()},
        "requested_scale": counts,
        "row_counts": row_counts,
        "checksums_sha256": file_manifest,
        "rules_version": RULE_VERSION,
        "provenance": "Entirely synthetic; no external or personal data used.",
    }
    (output / "source_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


# Combine the generated schema and CSV records into a SQL seed script.
def export_seed_sql(output: Path) -> None:
    schema = (output / "schema.sql").read_text(encoding="utf-8").rstrip()
    with (output / "seed.sql").open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(schema + "\n\nBEGIN;\n")
        for table, columns in TABLE_COLUMNS.items():
            path = output / f"{table}.csv"
            with path.open("r", newline="", encoding="utf-8") as source:
                reader = csv.DictReader(source)
                for row in reader:
                    values = []
                    for column in columns:
                        value = row[column]
                        values.append("NULL" if value == "" else "'" + value.replace("'", "''") + "'")
                    handle.write(
                        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(values)});\n"
                    )
        handle.write("COMMIT;\n")


# Parse command-line options and generate the requested dataset.
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scale", choices=sorted(SCALE), default="starter")
    parser.add_argument("--output", type=Path, default=Path("data"))
    parser.add_argument("--seed", type=int, default=SEED)
    for key in ("campaigns", "contacts", "touchpoints", "opportunities"):
        parser.add_argument(f"--{key}", type=int, default=None)
    args = parser.parse_args()
    counts = dict(SCALE[args.scale])
    for key in counts:
        if getattr(args, key) is not None:
            counts[key] = getattr(args, key)
    manifest = generate_dataset(args.output, counts, args.seed)
    print(json.dumps({
        "output": str(args.output.resolve()),
        "seed": args.seed,
        "row_counts": manifest["row_counts"],
        "validation": "passed",
        "manifest": str((args.output / "source_manifest.json").resolve()),
    }, indent=2))


if __name__ == "__main__":
    main()
