"""Campaign-management routes.

Covers the "planning" campaign surface: characters, events, quests,
factions, NPCs, inventory, equipment, downtime crafting, session
scheduling, audit/export, and analytics.
"""

from flask import jsonify

import services
import storage
from ._common import (
    SLUG_RE,
    _bad_request,
    _body,
    _conflict,
    _ensure_campaign,
    _load_campaign,
    _not_found,
    _require_strings,
)
from . import api


@api.post("/v1/campaigns")
def create_campaign():
    data = _body()
    camp_id = data.get("id")
    name = data.get("name")
    dm = data.get("dm")
    if not _require_strings(camp_id, name, dm):
        return _bad_request()

    result = storage.create_campaign(camp_id, name, dm)
    if result is None:
        return _conflict("campaign already exists")
    return jsonify(result), 201


@api.post("/v1/campaigns/<id>/characters")
def add_campaign_character(id):
    err = _ensure_campaign(id)
    if err:
        return err

    data = _body()
    char_id = data.get("id")
    name = data.get("name")
    level = data.get("level")
    class_name = data.get("class")

    if not _require_strings(char_id, name, class_name):
        return _bad_request()
    try:
        level = int(level)
    except (TypeError, ValueError):
        return _bad_request()
    if level < 1 or level > 20:
        return _bad_request()

    result = storage.create_campaign_character(id, char_id, name, level, class_name)
    if result is None:
        return _not_found()
    if result is False:
        return _conflict("character already exists")
    return jsonify(result), 201


@api.post("/v1/campaigns/<id>/events")
def add_campaign_event(id):
    err = _ensure_campaign(id)
    if err:
        return err

    data = _body()
    evt_id = data.get("id")
    kind = data.get("kind")
    summary = data.get("summary")

    if not _require_strings(evt_id, kind):
        return _bad_request()
    if summary is not None and not isinstance(summary, str):
        return _bad_request()

    result = storage.create_event(id, evt_id, kind, summary)
    if result is None:
        return _not_found()
    if result is False:
        return _conflict("event already exists")
    return jsonify(result), 201


@api.get("/v1/campaigns/<id>/state")
def get_campaign_state(id):
    campaign, err = _load_campaign(id)
    if err:
        return err

    characters = storage.get_campaign_characters(id)
    log_count = storage.get_event_count(id)
    return jsonify(
        id=campaign["id"],
        name=campaign["name"],
        dm=campaign["dm"],
        characters=characters,
        log_count=log_count,
    )


@api.post("/v1/campaigns/<id>/quests")
def create_quest(id):
    err = _ensure_campaign(id)
    if err:
        return err

    data = _body()
    quest_id = data.get("id")
    title = data.get("title")
    status = data.get("status")
    milestones = data.get("milestones", [])

    if not _require_strings(quest_id, title, status):
        return _bad_request()
    if status not in ("active", "completed", "blocked"):
        return _bad_request()
    if not isinstance(milestones, list):
        return _bad_request()
    for milestone in milestones:
        if not isinstance(milestone, str) or milestone == "":
            return _bad_request()

    result = storage.create_quest(id, quest_id, title, status, milestones)
    if result is None:
        return _not_found()
    if result is False:
        return _conflict("quest already exists")
    return jsonify(result), 201


@api.post("/v1/campaigns/<id>/quests/<quest_id>/progress")
def update_quest_progress(id, quest_id):
    err = _ensure_campaign(id)
    if err:
        return err

    data = _body()
    completed = data.get("completed", [])
    if not isinstance(completed, list):
        return _bad_request()
    for milestone in completed:
        if not isinstance(milestone, str) or milestone == "":
            return _bad_request()

    result = storage.update_quest_progress(id, quest_id, completed)
    if result is None:
        return _not_found()
    if result is False:
        return _bad_request()
    return jsonify(result)


@api.get("/v1/campaigns/<id>/quests/summary")
def get_quest_summary(id):
    err = _ensure_campaign(id)
    if err:
        return err
    return jsonify(storage.get_quest_summary(id))


@api.post("/v1/campaigns/<id>/factions")
def create_campaign_faction(id):
    err = _ensure_campaign(id)
    if err:
        return err

    data = _body()
    faction_id = data.get("id")
    name = data.get("name")
    stance = data.get("stance")

    if not _require_strings(faction_id, name, stance):
        return _bad_request()

    result = storage.create_faction(id, faction_id, name, stance)
    if result is None:
        return _not_found()
    if result is False:
        return _conflict("faction already exists")
    return jsonify(result), 201


@api.post("/v1/campaigns/<id>/npcs")
def create_campaign_npc(id):
    err = _ensure_campaign(id)
    if err:
        return err

    data = _body()
    npc_id = data.get("id")
    name = data.get("name")
    faction_id = data.get("faction_id")
    disposition = data.get("disposition")

    if not _require_strings(npc_id, name, faction_id):
        return _bad_request()
    try:
        disposition = int(disposition)
    except (TypeError, ValueError):
        return _bad_request()

    result = storage.create_npc(id, npc_id, name, faction_id, disposition)
    if result is None:
        return _not_found()
    if result is False:
        return _conflict("npc already exists")
    return jsonify(result), 201


@api.get("/v1/campaigns/<id>/relationships")
def get_campaign_relationships(id):
    err = _ensure_campaign(id)
    if err:
        return err
    return jsonify(storage.get_relationship_summary(id))


@api.post("/v1/campaigns/<id>/inventory")
def add_inventory_item(id):
    err = _ensure_campaign(id)
    if err:
        return err

    data = _body()
    item_slug = data.get("item_slug")
    quantity = data.get("quantity")
    owner = data.get("owner")

    if not isinstance(item_slug, str) or not SLUG_RE.fullmatch(item_slug):
        return _bad_request()
    if not isinstance(owner, str) or owner == "":
        return _bad_request()
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return _bad_request()
    if quantity <= 0:
        return _bad_request()

    result = storage.create_inventory_item(id, item_slug, quantity, owner)
    if result is None:
        return _not_found()
    return jsonify(result), 201


@api.post("/v1/campaigns/<id>/characters/<character_id>/equipment")
def assign_character_equipment(id, character_id):
    err = _ensure_campaign(id)
    if err:
        return err

    data = _body()
    item_slug = data.get("item_slug")
    quantity = data.get("quantity")

    if not isinstance(item_slug, str) or not SLUG_RE.fullmatch(item_slug):
        return _bad_request()
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return _bad_request()
    if quantity <= 0:
        return _bad_request()

    result = storage.assign_equipment(id, character_id, item_slug, quantity)
    if result is None:
        return _not_found()
    if result is False:
        return _bad_request()
    return jsonify(result), 200


@api.get("/v1/campaigns/<id>/inventory/summary")
def get_campaign_inventory_summary(id):
    err = _ensure_campaign(id)
    if err:
        return err
    return jsonify(storage.get_inventory_summary(id))


@api.post("/v1/campaigns/<id>/downtime/crafting")
def create_crafting_project(id):
    err = _ensure_campaign(id)
    if err:
        return err

    data = _body()
    project_id = data.get("id")
    character_id = data.get("character_id")
    item_slug = data.get("item_slug")
    days_required = data.get("days_required")
    cost_gp = data.get("cost_gp")

    if not _require_strings(project_id, character_id, item_slug):
        return _bad_request()
    if not SLUG_RE.fullmatch(item_slug):
        return _bad_request()
    try:
        days_required = int(days_required)
        cost_gp = int(cost_gp)
    except (TypeError, ValueError):
        return _bad_request()
    if days_required <= 0 or cost_gp < 0:
        return _bad_request()

    result = storage.create_crafting_project(id, project_id, character_id, item_slug, days_required, cost_gp)
    if result is None:
        return _not_found()
    if result == "character_not_found":
        return _bad_request()
    if result == "duplicate":
        return _conflict("project already exists")
    return jsonify(result), 201


@api.post("/v1/campaigns/<id>/downtime/crafting/<project_id>/advance")
def advance_crafting_project(id, project_id):
    err = _ensure_campaign(id)
    if err:
        return err

    data = _body()
    try:
        days = int(data["days"])
    except (KeyError, TypeError, ValueError):
        return _bad_request()
    if days <= 0:
        return _bad_request()

    result = storage.advance_crafting_project(id, project_id, days)
    if result is None:
        return _not_found()
    if result is False:
        return _bad_request()
    return jsonify(result)


@api.post("/v1/campaigns/<id>/sessions")
def create_session(id):
    err = _ensure_campaign(id)
    if err:
        return err

    data = _body()
    session_id = data.get("id")
    starts_at = data.get("starts_at")
    duration_minutes = data.get("duration_minutes")
    agenda = data.get("agenda", [])

    if not _require_strings(session_id, starts_at):
        return _bad_request()
    try:
        duration_minutes = int(duration_minutes)
    except (TypeError, ValueError):
        return _bad_request()
    if duration_minutes <= 0:
        return _bad_request()
    if not isinstance(agenda, list) or any(not isinstance(item, str) or item == "" for item in agenda):
        return _bad_request()

    result = storage.create_session(id, session_id, starts_at, duration_minutes, agenda)
    if result is None:
        return _not_found()
    if result is False:
        return _conflict("session already exists")
    return jsonify(result), 201


@api.post("/v1/campaigns/<id>/sessions/<session_id>/attendance")
def record_session_attendance(id, session_id):
    err = _ensure_campaign(id)
    if err:
        return err

    data = _body()
    present = data.get("present", [])
    absent = data.get("absent", [])

    if not isinstance(present, list) or not isinstance(absent, list):
        return _bad_request()
    if any(not isinstance(char_id, str) or char_id == "" for char_id in present + absent):
        return _bad_request()
    if set(present) & set(absent):
        return _bad_request()

    result = storage.record_attendance(id, session_id, present, absent)
    if result is None:
        return _not_found()
    if result is False:
        return _bad_request()
    return jsonify(result)


@api.get("/v1/campaigns/<id>/sessions/next")
def get_next_session(id):
    err = _ensure_campaign(id)
    if err:
        return err

    result = storage.get_next_session(id)
    if result is None:
        return _not_found()
    return jsonify(result)


@api.get("/v1/campaigns/<id>/audit")
def get_campaign_audit(id):
    err = _ensure_campaign(id)
    if err:
        return err
    return jsonify(
        campaign_id=id,
        events=storage.get_event_count(id),
        quests=storage.get_quest_count(id),
        npcs=storage.get_npc_count(id),
        sessions=storage.get_session_count(id),
    )


@api.get("/v1/campaigns/<id>/export")
def export_campaign(id):
    campaign, err = _load_campaign(id)
    if err:
        return err
    return jsonify(
        campaign_id=campaign["id"],
        name=campaign["name"],
        characters=storage.get_character_count(id),
        quests=storage.get_quest_count(id),
        npcs=storage.get_npc_count(id),
        inventory_items=storage.get_inventory_item_count(id),
        sessions=storage.get_session_count(id),
        schema_version=storage.SCHEMA_VERSION,
    )


@api.get("/v1/campaigns/<id>/analytics/summary")
def get_campaign_analytics_summary(id):
    result = services.build_analytics_summary(id)
    if result is None:
        return _not_found()
    return jsonify(result)


@api.post("/v1/campaigns/<id>/analytics/risk-report")
def get_campaign_risk_report(id):
    data = _body()
    include_zeroes = data.get("include_zeroes", True)
    if not isinstance(include_zeroes, bool):
        return _bad_request()

    result = services.build_risk_report(id, include_zeroes)
    if result is None:
        return _not_found()
    return jsonify(result)
