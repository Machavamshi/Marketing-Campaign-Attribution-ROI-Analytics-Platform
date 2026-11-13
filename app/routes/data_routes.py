import csv
import io
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
from flask import Blueprint, Response, current_app, flash, jsonify, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from app.db import get_db
from app.services.analytics import known_exceptions, validation_summary
from generate import TABLE_COLUMNS, generate_dataset, SCALE


data = Blueprint("data", __name__)
IMPORTABLE_TABLES = frozenset(TABLE_COLUMNS)


@data.get("/exceptions")
def exceptions():
    return render_template("data/exceptions.html", exceptions=known_exceptions())


@data.get("/validation")
def validation():
    return render_template("data/validation.html", summary=validation_summary())


@data.get("/export/<table_name>.csv")
def export_csv(table_name: str):
    if table_name not in IMPORTABLE_TABLES:
        return jsonify({"error": "Unknown export table."}), 404
    columns = TABLE_COLUMNS[table_name]
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(columns)
    for row in get_db().execute(f"SELECT {', '.join(columns)} FROM {table_name}"):
        writer.writerow(["" if value is None else value for value in row])
    return Response(
        stream.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={secure_filename(table_name)}.csv"},
    )


@data.post("/import")
def import_csv():
    upload = request.files.get("file")
    table = request.form.get("table", "")
    if table not in IMPORTABLE_TABLES or upload is None or not upload.filename:
        flash("Choose a supported table and a CSV file.", "danger")
        return redirect(url_for("data.manage"))
    try:
        frame = pd.read_csv(upload, dtype=str, keep_default_na=False)
        expected = TABLE_COLUMNS[table]
        if list(frame.columns) != expected:
            raise ValueError(f"CSV headers must exactly match: {', '.join(expected)}")
        if frame.empty:
            raise ValueError("The CSV has no data rows.")
        primary_key = expected[0]
        if frame[primary_key].eq("").any() or frame[primary_key].duplicated().any():
            raise ValueError(f"{primary_key} values must be present and unique in the uploaded file.")
        sql = f"INSERT INTO {table} ({', '.join(expected)}) VALUES ({', '.join('?' for _ in expected)})"
        connection = get_db()
        connection.executemany(
            sql,
            (tuple(value if value != "" else None for value in row) for row in frame.itertuples(index=False, name=None)),
        )
        if table == "campaigns":
            for record in frame.to_dict(orient="records"):
                connection.execute(
                    "INSERT INTO campaign_events VALUES (?,?,?,?,?)",
                    (
                        f"CME-IMPORT-{record['campaign_id']}-000001",
                        record["campaign_id"],
                        "campaign_created",
                        datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        json.dumps({"after": record}, sort_keys=True),
                    ),
                )
        connection.commit()
        flash(f"Imported {len(frame)} rows into {table}.", "success")
    except (ValueError, pd.errors.ParserError, UnicodeDecodeError, sqlite3.Error) as error:
        get_db().rollback()
        flash(f"Import failed; no rows were committed: {error}", "danger")
    return redirect(url_for("data.manage"))


@data.get("/")
def manage():
    return render_template("data/manage.html", tables=sorted(IMPORTABLE_TABLES), scales=SCALE)


@data.post("/generate")
def generate():
    scale = request.form.get("scale", "starter")
    if scale not in SCALE:
        flash("Choose starter or full scale.", "danger")
        return redirect(url_for("data.manage"))
    output = Path(current_app.instance_path) / f"generated-{scale}"
    try:
        manifest = generate_dataset(output, SCALE[scale])
    except (OSError, ValueError) as error:
        flash(f"Dataset generation failed: {error}", "danger")
        return redirect(url_for("data.manage"))
    flash(
        f"Generated {scale} data ({manifest['row_counts']['campaigns']} campaigns, "
        f"{manifest['row_counts']['touchpoints']} touchpoints) at {output}. "
        "The active database is unchanged; set DATASET_DIR to this folder before initializing a new database.",
        "success",
    )
    return redirect(url_for("data.manage"))
