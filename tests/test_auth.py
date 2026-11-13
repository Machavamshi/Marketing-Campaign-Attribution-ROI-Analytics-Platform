from urllib.parse import urlsplit


def _csrf_token(client):
    with client.session_transaction() as browser_session:
        return browser_session["csrf_token"]


def test_workspace_requires_login_and_registration_validates_passwords(client):
    client.post("/logout", data={"csrf_token": _csrf_token(client)})
    response = client.get("/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")

    response = client.get("/register")
    assert response.status_code == 200
    csrf_token = _csrf_token(client)
    for weak_password in ("Aa1!", "lowercase1!", "NoNumber!", "NoSpecial1"):
        response = client.post(
            "/register",
            data={
                "csrf_token": csrf_token,
                "email": "new@example.test",
                "password": weak_password,
                "confirm_password": weak_password,
            },
        )
        assert response.status_code == 400

    response = client.post(
        "/register",
        data={
            "csrf_token": csrf_token,
            "email": "new@example.test",
            "password": "Strong1!",
            "confirm_password": "Strong1!",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_password_reset_link_is_one_time_and_updates_password(client, monkeypatch):
    client.post("/logout", data={"csrf_token": _csrf_token(client)})
    client.application.config.update(
        MAIL_SERVER="smtp.example.test",
        MAIL_DEFAULT_SENDER="noreply@example.test",
        PUBLIC_BASE_URL="https://campaign.example.test",
    )
    sent = {}

    def capture_reset_email(email, link):
        sent["email"] = email
        sent["link"] = link

    monkeypatch.setattr("app.auth._email_reset_link", capture_reset_email)
    client.get("/forgot-password")
    response = client.post(
        "/forgot-password",
        data={
            "csrf_token": _csrf_token(client),
            "email": "analytics@example.test",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"If an account exists" in response.data
    assert sent["email"] == "analytics@example.test"

    reset_path = urlsplit(sent["link"]).path
    response = client.get(reset_path)
    assert response.status_code == 200
    response = client.post(
        reset_path,
        data={
            "csrf_token": _csrf_token(client),
            "password": "New-correct-9!",
            "confirm_password": "New-correct-9!",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")
    assert client.get(reset_path).headers["Location"].endswith("/forgot-password")

    client.get("/login")
    response = client.post(
        "/login",
        data={
            "csrf_token": _csrf_token(client),
            "email": "analytics@example.test",
            "password": "New-correct-9!",
        },
    )
    assert response.status_code == 302
    assert client.get("/").status_code == 200


def test_forgot_password_reports_missing_smtp_configuration(client):
    client.post("/logout", data={"csrf_token": _csrf_token(client)})
    client.get("/forgot-password")
    response = client.post(
        "/forgot-password",
        data={"csrf_token": _csrf_token(client), "email": "analytics@example.test"},
    )
    assert response.status_code == 503
    assert b"not configured" in response.data
