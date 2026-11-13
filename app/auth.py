import hashlib
import re
import secrets
import smtplib
import sqlite3
import time
from email.message import EmailMessage
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app.db import get_db


auth = Blueprint("auth", __name__)
PASSWORD_MIN_LENGTH = 6


def _password_policy_error(password: str) -> str | None:
    if len(password) < PASSWORD_MIN_LENGTH:
        return "Use a password with at least 6 characters."
    if not any(character.isupper() for character in password):
        return "Include at least one uppercase letter."
    if not any(character.isdigit() for character in password):
        return "Include at least one number."
    if not any(not character.isalnum() and not character.isspace() for character in password):
        return "Include at least one special character."
    return None


def ensure_auth_schema() -> None:
    get_db().executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            expires_at INTEGER NOT NULL,
            used_at INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_password_reset_user
            ON password_reset_tokens(user_id);
        """
    )


def _csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


@auth.app_context_processor
def provide_auth_template_helpers():
    return {"csrf_token": _csrf_token}


@auth.before_app_request
def require_login():
    g.current_user = None
    if request.endpoint is None or request.endpoint.startswith(("auth.", "static")):
        return None

    user_id = session.get("user_id")
    if user_id is not None:
        user = get_db().execute(
            "SELECT user_id, email FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if user is not None:
            g.current_user = user
            return None
        session.clear()
    return redirect(url_for("auth.login"))


def _require_valid_csrf() -> None:
    submitted = request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    if not submitted or not expected or not secrets.compare_digest(submitted, expected):
        abort(400, description="Your form session expired. Reload the page and try again.")


def _email_reset_link(email: str, link: str) -> None:
    message = EmailMessage()
    message["Subject"] = "Reset your Campaign Atlas password"
    message["From"] = current_app.config["MAIL_DEFAULT_SENDER"]
    message["To"] = email
    message.set_content(
        "A password reset was requested for your Campaign Atlas account.\n\n"
        f"Use this one-time link within one hour:\n{link}\n\n"
        "If you did not request this, you can ignore this email."
    )

    with smtplib.SMTP(
        current_app.config["MAIL_SERVER"],
        current_app.config["MAIL_PORT"],
        timeout=10,
    ) as smtp:
        if current_app.config["MAIL_USE_TLS"]:
            smtp.starttls()
        username = current_app.config["MAIL_USERNAME"]
        if username:
            smtp.login(username, current_app.config["MAIL_PASSWORD"])
        smtp.send_message(message)


def _reset_token_record(token: str):
    return get_db().execute(
        """SELECT user_id FROM password_reset_tokens
           WHERE token_hash = ? AND expires_at > ? AND used_at IS NULL""",
        (hashlib.sha256(token.encode("utf-8")).hexdigest(), int(time.time())),
    ).fetchone()


@auth.get("/login")
def login():
    return render_template("auth/login.html")


@auth.post("/login")
def login_submit():
    _require_valid_csrf()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    user = get_db().execute(
        "SELECT user_id, email, password_hash FROM users WHERE email = ? COLLATE NOCASE",
        (email,),
    ).fetchone()
    if user is None or not check_password_hash(user["password_hash"], password):
        flash("The email or password is incorrect.", "danger")
        return render_template("auth/login.html"), 401

    session.clear()
    session["user_id"] = user["user_id"]
    session["user_email"] = user["email"]
    _csrf_token()
    return redirect(url_for("dashboard.index"))


@auth.get("/register")
def register():
    return render_template("auth/register.html")


@auth.post("/register")
def register_submit():
    _require_valid_csrf()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    confirmation = request.form.get("confirm_password", "")

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        flash("Enter a valid email address.", "danger")
        return render_template("auth/register.html"), 400
    password_error = _password_policy_error(password)
    if password_error:
        flash(password_error, "danger")
        return render_template("auth/register.html"), 400
    if password != confirmation:
        flash("The passwords do not match.", "danger")
        return render_template("auth/register.html"), 400

    try:
        with get_db():
            get_db().execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, generate_password_hash(password)),
            )
    except sqlite3.IntegrityError:
        flash("An account with that email already exists. Sign in instead.", "danger")
        return render_template("auth/register.html"), 409

    flash("Your account is ready. Sign in to continue.", "success")
    return redirect(url_for("auth.login"))


@auth.get("/forgot-password")
def forgot_password():
    return render_template("auth/forgot_password.html")


@auth.post("/forgot-password")
def forgot_password_submit():
    _require_valid_csrf()
    public_base_url = current_app.config.get("PUBLIC_BASE_URL") or ""
    parsed_base_url = urlsplit(public_base_url)
    if not all(
        current_app.config.get(key)
        for key in ("MAIL_SERVER", "MAIL_DEFAULT_SENDER")
    ) or not (
        parsed_base_url.scheme in {"http", "https"} and parsed_base_url.netloc
    ) or (
        current_app.config.get("MAIL_USERNAME")
        and not current_app.config.get("MAIL_PASSWORD")
    ):
        current_app.logger.error(
            "Password reset requested but SMTP or PUBLIC_BASE_URL configuration is missing or invalid."
        )
        flash("Password reset email is not configured. Contact the application administrator.", "danger")
        return render_template("auth/forgot_password.html"), 503

    email = request.form.get("email", "").strip().lower()
    user = get_db().execute(
        "SELECT user_id, email FROM users WHERE email = ? COLLATE NOCASE",
        (email,),
    ).fetchone()
    if user is not None:
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        try:
            with get_db():
                get_db().execute(
                    """INSERT INTO password_reset_tokens (token_hash, user_id, expires_at)
                       VALUES (?, ?, ?)""",
                    (token_hash, user["user_id"], int(time.time()) + 3600),
                )
            reset_path = url_for("auth.reset_password", token=token)
            _email_reset_link(
                user["email"],
                f"{public_base_url.rstrip('/')}{reset_path}",
            )
        except (OSError, smtplib.SMTPException) as error:
            with get_db():
                get_db().execute(
                    "DELETE FROM password_reset_tokens WHERE token_hash = ?", (token_hash,)
                )
            current_app.logger.error("Password reset email delivery failed: %s", error, exc_info=True)

    flash("If an account exists for that email, a password reset link will be sent.", "info")
    return redirect(url_for("auth.login"))


@auth.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    if _reset_token_record(token) is None:
        flash("That password reset link is invalid or has expired.", "danger")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        _require_valid_csrf()
        password = request.form.get("password", "")
        confirmation = request.form.get("confirm_password", "")
        password_error = _password_policy_error(password)
        if password_error:
            flash(password_error, "danger")
            return render_template("auth/reset_password.html"), 400
        if password != confirmation:
            flash("The passwords do not match.", "danger")
            return render_template("auth/reset_password.html"), 400

        record = _reset_token_record(token)
        if record is None:
            flash("That password reset link is invalid or has expired.", "danger")
            return redirect(url_for("auth.forgot_password"))
        with get_db():
            get_db().execute(
                "UPDATE users SET password_hash = ? WHERE user_id = ?",
                (generate_password_hash(password), record["user_id"]),
            )
            get_db().execute(
                "UPDATE password_reset_tokens SET used_at = ? WHERE user_id = ? AND used_at IS NULL",
                (int(time.time()), record["user_id"]),
            )
        flash("Your password has been updated. Sign in with your new password.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html")


@auth.post("/logout")
def logout():
    _require_valid_csrf()
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))
