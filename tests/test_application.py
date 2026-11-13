import csv
import io


def test_dashboard_and_analytics_routes_render(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"MARKETING PERFORMANCE" in response.data
    assert client.get("/analytics/").status_code == 200
    assert client.get("/analytics/campaign-roi?model=linear&period=test").status_code == 200


def test_api_reports_three_models_and_coverage(client):
    response = client.get("/analytics/api/comparison?period=test")
    assert response.status_code == 200
    body = response.get_json()
    assert set(body["models"]) == {"first_touch", "last_touch", "linear"}
    assert 0 <= body["channels"][0]["attributed_revenue"]
    assert all(
        value is None or value == value
        for rows in body["models"].values()
        for row in rows
        for value in row.values()
        if isinstance(value, float)
    )
    assert client.get("/analytics/api/roi?model=unknown").status_code == 400
    assert client.get("/analytics/api/comparison?period=unknown").status_code == 400


def test_exceptions_remain_visible_separately(client):
    response = client.get("/data/exceptions")
    assert response.status_code == 200
    for label in (b"duplicate revenue", b"post conversion touch", b"currency mismatch", b"anonymous session link"):
        assert label in response.data.lower()


def test_csv_export_and_validated_import(client):
    export = client.get("/data/export/campaigns.csv")
    assert export.status_code == 200
    assert b"campaign_id,name,channel_id" in export.data

    content = io.StringIO()
    writer = csv.writer(content)
    writer.writerow(["channel_id", "name", "channel_type"])
    writer.writerow(["CH-NEW", "Partner event", "offline"])
    response = client.post(
        "/data/import",
        data={"table": "channels", "file": (io.BytesIO(content.getvalue().encode()), "channels.csv")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Imported 1 rows" in response.data


def test_bad_import_rolls_back_without_partial_rows(client):
    content = "channel_id,name,channel_type\nCH-BAD,Invalid,digital\nCH-BAD,Duplicate,offline\n"
    response = client.post(
        "/data/import",
        data={"table": "channels", "file": (io.BytesIO(content.encode()), "channels.csv")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"must be present and unique" in response.data
    assert b"CH-BAD" not in client.get("/data/export/channels.csv").data


def test_campaign_creation_records_campaign_and_optional_cost(client):
    response = client.post(
        "/campaigns/",
        data={
            "name": "New product launch",
            "budget_amount": "1200.00",
            "actual_spend": "450.25",
            "channel_id": "CH-001",
            "audience_id": "AUD-001",
            "creative_id": "CRE-0001",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"New product launch" in response.data
    assert b"450.25" in response.data

    details = client.get("/campaigns/CMP-2026-000009")
    assert details.status_code == 200
    assert b"campaign_created" in details.data
    revision = client.post(
        "/campaigns/CMP-2026-000009/edit",
        data={"name": "New product launch revised", "budget_amount": "1400.00"},
        follow_redirects=True,
    )
    assert revision.status_code == 200
    assert b"campaign_revised" in revision.data
    assert b"New product launch revised" in revision.data
