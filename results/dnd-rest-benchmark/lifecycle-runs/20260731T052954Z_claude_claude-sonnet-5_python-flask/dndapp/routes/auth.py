"""User registration and login. Sessions are a placeholder token, not a real auth scheme."""

from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from ..db import get_db
from ..validation import USERNAME_RE

bp = Blueprint("auth", __name__)


def hash_password(password):
    return generate_password_hash(password)


def verify_password(password, password_hash):
    return check_password_hash(password_hash, password)


@bp.post("/v1/auth/register")
def register_user():
    data = request.get_json(silent=True) or {}
    username = data.get("username")
    password = data.get("password")
    role = data.get("role")

    if not isinstance(username, str) or not USERNAME_RE.match(username):
        return jsonify(error="invalid username"), 400
    if not isinstance(password, str) or len(password) < 8:
        return jsonify(error="invalid password"), 400
    if role not in ("dm", "player"):
        return jsonify(error="invalid role"), 400

    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT username FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing is not None:
            return jsonify(error="username already exists"), 409

        conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, hash_password(password), role),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(username=username, role=role), 201


@bp.post("/v1/auth/login")
def login_user():
    data = request.get_json(silent=True) or {}
    username = data.get("username")
    password = data.get("password")

    if not isinstance(username, str) or not isinstance(password, str):
        return jsonify(error="invalid request"), 400

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT username, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    finally:
        conn.close()

    if row is None or not verify_password(password, row["password_hash"]):
        return jsonify(error="invalid credentials"), 401

    return jsonify(username=username, token=f"session-{username}")
