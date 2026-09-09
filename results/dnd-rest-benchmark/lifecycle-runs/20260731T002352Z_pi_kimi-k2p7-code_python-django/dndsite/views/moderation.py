"""Campaign moderation reports."""

from django.views.decorators.csrf import csrf_exempt

from django.http import JsonResponse

from ..db import _create_moderation_report, _get_moderation_report, _list_moderation_reports, _resolve_moderation_report, db_conn
from ..http import bad_request, conflict, not_found, parse_json, require_method
from .common import require_play_campaign_dm_owner, require_play_campaign_member_or_owner


def _report_response(row):
    """Build a moderation report response dict."""
    base = {
        "report_id": row["report_id"],
        "target_id": row["target_id"],
        "reason": row["reason"],
        "status": row["status"],
        "reporter": row["reporter"],
        "sequence": row["sequence"],
    }
    if row["status"] == "resolved":
        base.update({
            "action": row["action"],
            "note": row["note"],
            "resolver": row["resolver"],
        })
    return base


def moderation_reports(request, id):
    """Dispatch GET/POST for /v1/play/campaigns/{id}/moderation/reports."""
    if request.method == "POST":
        return submit_moderation_report(request, id)
    if request.method == "GET":
        return list_moderation_reports(request, id)
    return require_method(request, "GET", "POST")


@csrf_exempt
def submit_moderation_report(request, id):
    """POST /v1/play/campaigns/{id}/moderation/reports"""
    err = require_method(request, "POST")
    if err is not None:
        return err

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")

    report_id = body.get("report_id")
    target_id = body.get("target_id")
    reason = body.get("reason")
    if not isinstance(report_id, str) or not report_id:
        return bad_request("report_id is required")
    if not isinstance(target_id, str) or not target_id:
        return bad_request("target_id is required")
    if not isinstance(reason, str) or not reason:
        return bad_request("reason is required")

    try:
        with db_conn() as conn:
            sequence = _create_moderation_report(
                conn, id, report_id, target_id, reason, actor["username"]
            )
            row = _get_moderation_report(conn, id, report_id)
    except Exception:
        return conflict("report already exists")

    return JsonResponse(_report_response(row), status=201)


def list_moderation_reports(request, id):
    """GET /v1/play/campaigns/{id}/moderation/reports"""
    err = require_method(request, "GET")
    if err is not None:
        return err

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        rows = _list_moderation_reports(conn, id)

    return JsonResponse({"reports": [_report_response(row) for row in rows]})


@csrf_exempt
def resolve_moderation_report(request, id, report_id):
    """PUT /v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution"""
    err = require_method(request, "PUT")
    if err is not None:
        return err

    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")

    action = body.get("action")
    note = body.get("note")
    if action not in ("allow", "remove"):
        return bad_request("action must be allow or remove")
    if not isinstance(note, str) or not note:
        return bad_request("note is required")

    with db_conn() as conn:
        row = _get_moderation_report(conn, id, report_id)
        if row is None:
            return not_found("report not found")
        if row["status"] != "open":
            return conflict("report already resolved")
        _resolve_moderation_report(conn, id, report_id, action, note, actor["username"])
        row = _get_moderation_report(conn, id, report_id)

    return JsonResponse(_report_response(row))
