"""Storage introspection and destructive reset, mainly for test fixtures."""

from flask import Blueprint, jsonify

from ..db import SCHEMA_VERSION, db_initialized, reset_db

bp = Blueprint("storage", __name__)


@bp.get("/v1/storage/status")
def storage_status():
    return jsonify(
        driver="sqlite",
        schema_version=SCHEMA_VERSION,
        initialized=db_initialized(),
    )


@bp.post("/v1/storage/reset")
def storage_reset():
    reset_db()
    return jsonify(ok=True, schema_version=SCHEMA_VERSION)
