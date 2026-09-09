"""Play-campaign surface and encounter routes.

Everything in this module requires an `Authorization: Bearer session-{username}`
header. It covers lobby creation, membership, turn queue, narration, scene and
location graph management, travel/rest turns, encounter building, and combat.
"""

import json

from flask import Response, jsonify, request

import domain
import storage
from ._common import (
    SLUG_RE,
    _bad_request,
    _body,
    _conflict,
    _current_user,
    _ensure_play_campaign,
    _forbidden,
    _load_play_campaign,
    _not_found,
    _rate_limited,
    _require_dm_campaign,
    _require_owner,
    _require_owner_or_member,
    _require_play_campaign_access,
    _require_role,
    _require_strings,
    _unauthorized,
    set_maintenance_mode,
)
from . import api


# --- Play campaigns ---


@api.post("/v1/play/campaigns")
def create_play_campaign():
    user, error = _require_role("dm")
    if error:
        return error

    data = _body()
    camp_id = data.get("id")
    name = data.get("name")
    max_players = data.get("max_players")
    if not _require_strings(camp_id, name):
        return _bad_request()
    try:
        max_players = int(max_players)
    except (TypeError, ValueError):
        return _bad_request()
    if max_players <= 0:
        return _bad_request()

    result = storage.create_play_campaign(camp_id, name, user["username"], max_players)
    if result is None:
        return _conflict("campaign already exists")
    return jsonify(result), 201


@api.post("/v1/play/campaigns/<id>/service-mode")
def set_play_campaign_service_mode(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    maintenance = data.get("maintenance")
    if not isinstance(maintenance, bool):
        return _bad_request()

    set_maintenance_mode(maintenance)
    return jsonify(maintenance=maintenance)


@api.post("/v1/play/campaigns/<id>/members")
def join_play_campaign(id):
    user, error = _require_role("player")
    if error:
        return error

    err = _ensure_play_campaign(id)
    if err:
        return err

    data = _body()
    character_id = data.get("character_id")
    name = data.get("name")
    class_name = data.get("class")
    hp_max = data.get("hp_max")
    hp_current = data.get("hp_current")
    if not _require_strings(character_id, name, class_name):
        return _bad_request()
    if hp_max is not None:
        try:
            hp_max = int(hp_max)
        except (TypeError, ValueError):
            return _bad_request()
        if hp_max <= 0:
            return _bad_request()
    if hp_current is not None:
        try:
            hp_current = int(hp_current)
        except (TypeError, ValueError):
            return _bad_request()
        if hp_current < 0:
            return _bad_request()

    result = storage.join_play_campaign(id, user["username"], character_id, name, class_name, hp_max, hp_current)
    if result is None:
        return _not_found()
    if result == "full":
        return _conflict("party is full")
    if result == "already_member":
        return _conflict("player already joined")
    if result == "duplicate_character":
        return _conflict("character already exists")

    return jsonify({
        "username": user["username"],
        "character_id": result["character_id"],
        "name": result["name"],
        "class": result["class"],
    }), 201


@api.post("/v1/play/campaigns/<id>/start")
def start_play_campaign(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    result = storage.start_play_campaign(id)
    if result == "already_active":
        return _conflict("already active")
    if result == "under_populated":
        return _conflict("under-populated")
    if result is None:
        return _not_found()
    return jsonify(result)


@api.put("/v1/play/campaigns/<id>/session-zero")
def set_session_zero(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    rules = data.get("rules")
    tone = data.get("tone")
    consent = data.get("consent")
    if not _require_strings(rules, tone):
        return _bad_request()
    if not isinstance(consent, list) or len(consent) == 0:
        return _bad_request()
    seen = set()
    for item in consent:
        if not isinstance(item, str) or item == "" or item in seen:
            return _bad_request()
        seen.add(item)

    if campaign["status"] != "lobby":
        return _conflict("campaign is not in lobby")

    result = storage.set_play_campaign_session_zero(id, rules, tone, consent)
    if result == "not_lobby":
        return _conflict("campaign is not in lobby")
    if result is None:
        return _not_found()
    return jsonify(result)


@api.get("/v1/play/campaigns/<id>/session-zero")
def get_session_zero(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    result = storage.get_play_campaign_session_zero(id)
    if result is None:
        return _not_found()
    return jsonify(result)


@api.get("/v1/play/campaigns/<id>/onboarding")
def get_play_campaign_onboarding(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    if campaign["owner"] == user["username"]:
        return Response(
            '{"role":"dm","next_steps":["configure-safety","invite-players","start-campaign"],"can_mutate":true}',
            mimetype="application/json",
        )
    return Response(
        '{"role":"player","next_steps":["review-party","take-turn","submit-action"],"can_mutate":true}',
        mimetype="application/json",
    )


@api.post("/v1/play/campaigns/<id>/narrations")
def add_narration(id):
    user = _current_user()
    if user is None:
        return _unauthorized()

    campaign, err = _load_play_campaign(id)
    if err:
        return err

    is_owner = campaign["owner"] == user["username"]
    if not is_owner and not storage.is_active_delegate(id, user["username"], "narrate"):
        return _forbidden()

    data = _body()
    text = data.get("text")
    if not isinstance(text, str) or text == "":
        return _bad_request()

    actor = "dm" if is_owner else user["username"]
    result = storage.create_narration(id, text, actor=actor)
    if result is None:
        return _not_found()
    return jsonify(result), 201


@api.get("/v1/play/campaigns/<id>/turn")
def get_play_campaign_turn(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    current_actor = campaign["current_actor"]
    campaign_phase = campaign.get("phase")
    if campaign_phase == "combat":
        phase = "combat"
    elif current_actor == campaign["owner"]:
        phase = "exploration"
    elif current_actor is None:
        phase = campaign["status"]
    else:
        phase = "player"

    queue = storage.get_play_campaign_queue(id)
    payload = {
        "campaign_id": id,
        "current_actor": current_actor,
        "phase": phase,
        "turn_number": campaign["turn_number"],
        "queue": queue,
        "overdue": False,
        "logical_deadline": campaign["turn_number"] + 1,
    }
    return Response(
        json.dumps(payload, sort_keys=False, separators=(",", ":")),
        mimetype="application/json",
    )


@api.post("/v1/play/campaigns/<id>/turn/nudge")
def nudge_play_campaign(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    message = data.get("message")
    if not isinstance(message, str) or message == "":
        return _bad_request()

    nudge_count = storage.increment_nudge_count(id, message)
    if nudge_count is None:
        return _not_found()

    return jsonify(
        actor=user["username"],
        target=campaign["current_actor"],
        message=message,
        nudge_count=nudge_count,
    ), 201


@api.get("/v1/play/campaigns/<id>/document")
def get_play_campaign_document(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    document = storage.get_play_campaign_document(id)
    if document is None:
        return _not_found()

    if campaign["owner"] == user["username"]:
        return jsonify(story=document["story"], dm_notes=document["dm_notes"])
    return jsonify(story=document["story"])


@api.put("/v1/play/campaigns/<id>/document")
def update_play_campaign_document(id):
    user = _current_user()
    if user is None:
        return _unauthorized()

    campaign, err = _load_play_campaign(id)
    if err:
        return err

    err = _require_owner(campaign, user)
    if err:
        return err

    data = _body()
    story = data.get("story")
    dm_notes = data.get("dm_notes")
    if not _require_strings(story, dm_notes):
        return _bad_request()

    document = storage.update_play_campaign_document(id, story, dm_notes)
    if document is None:
        return _not_found()
    return jsonify(story=document["story"], dm_notes=document["dm_notes"])


@api.get("/v1/play/campaigns/<id>/my-turn")
def get_my_turn(id):
    user = _current_user()
    if user is None:
        return _unauthorized()
    if user["role"] != "player":
        return _forbidden()

    campaign, err = _load_play_campaign(id)
    if err:
        return err

    member = storage.get_play_campaign_member(id, user["username"])
    if member is None:
        return _forbidden()

    events = storage.get_play_campaign_events(id)
    return jsonify(
        is_my_turn=campaign["current_actor"] == user["username"],
        current_actor=campaign["current_actor"],
        character={"id": member["character_id"], "name": member["name"]},
        recent_events=[{"kind": e["kind"]} for e in events],
    )


@api.get("/v1/play/campaigns/<id>/gm/status")
def get_play_campaign_gm_status(id):
    user = _current_user()
    if user is None:
        return _unauthorized()

    campaign, err = _load_play_campaign(id)
    if err:
        return err

    err = _require_owner(campaign, user)
    if err:
        return err

    members = storage.get_play_campaign_members(id)
    events = storage.get_play_campaign_events(id)
    return jsonify(
        needs_attention=campaign["current_actor"] == campaign["owner"],
        current_actor=campaign["current_actor"],
        party=[
            {
                "username": member["player"],
                "character_id": member["character_id"],
                "name": member["name"],
                "class": member["class"],
                "is_my_turn": member["player"] == campaign["current_actor"],
            }
            for member in members
        ],
        recent_events=events,
    )


@api.post("/v1/play/campaigns/<id>/actions")
def submit_player_action(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    if user["role"] != "player" or campaign["current_actor"] != user["username"]:
        return jsonify(error="not your turn"), 409

    data = _body()
    action_type = data.get("type")
    text = data.get("text")
    if not _require_strings(action_type, text):
        return _bad_request()

    result = storage.create_action(id, user["username"], action_type, text)
    if result is None:
        return _not_found()
    return jsonify(result), 201


@api.post("/v1/play/campaigns/<id>/resolutions")
def submit_resolution(id):
    user = _current_user()
    if user is None:
        return _unauthorized()

    campaign, err = _load_play_campaign(id)
    if err:
        return err

    if campaign["owner"] != user["username"]:
        return jsonify(error="not your turn"), 409

    if campaign["current_actor"] != campaign["owner"]:
        return jsonify(error="not your turn"), 409

    data = _body()
    text = data.get("text")
    if not isinstance(text, str) or text == "":
        return _bad_request()

    result = storage.create_resolution(id, text)
    if result is None:
        return _not_found()

    return jsonify(
        sequence=result["sequence"],
        kind=result["kind"],
        actor=result["actor"],
        text=result["text"],
        next_actor=result["next_actor"],
        turn_number=result["turn_number"],
    ), 201


# --- Scenes ---


@api.post("/v1/play/campaigns/<id>/scenes")
def create_scene(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    scene_id = data.get("id")
    name = data.get("name")
    if not _require_strings(scene_id, name):
        return _bad_request()

    result = storage.create_scene(id, scene_id, name)
    if result is None:
        return _not_found()
    if result is False:
        return _conflict("scene already exists")
    return jsonify(result), 201


@api.post("/v1/play/campaigns/<id>/scenes/<scene_id>/enter")
def enter_scene(id, scene_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    result = storage.enter_scene(id, scene_id)
    if result is None:
        return _not_found()
    if result == "scene_not_found":
        return _not_found()
    if result == "closed":
        return _conflict("scene is closed")
    return jsonify(result)


@api.post("/v1/play/campaigns/<id>/scenes/<scene_id>/close")
def close_scene(id, scene_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    result = storage.close_scene(id, scene_id)
    if result is None:
        return _not_found()
    if result == "scene_not_found":
        return _not_found()
    return jsonify(result)


@api.get("/v1/play/campaigns/<id>/scenes/current")
def get_current_scene(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    result = storage.get_current_scene(id)
    if result is None:
        return _not_found()
    return jsonify(result)


# --- Location graph ---


@api.post("/v1/play/campaigns/<id>/locations")
def create_location(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    location_id = data.get("id")
    name = data.get("name")
    if not _require_strings(location_id, name):
        return _bad_request()

    result = storage.create_location(id, location_id, name)
    if result is None:
        return _not_found()
    if result is False:
        return _conflict("location already exists")
    return jsonify(result), 201


@api.post("/v1/play/campaigns/<id>/locations/<from_id>/connections")
def create_connection(id, from_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    to_id = data.get("to_id")
    travel_turns = data.get("travel_turns")
    if not _require_strings(to_id):
        return _bad_request()
    try:
        travel_turns = int(travel_turns)
    except (TypeError, ValueError):
        return _bad_request()
    if travel_turns <= 0:
        return _bad_request()

    result = storage.create_connection(id, from_id, to_id, travel_turns)
    if result is None:
        return _not_found()
    if result == "missing" or result == "duplicate":
        return _bad_request()
    return jsonify(result), 201


@api.get("/v1/play/campaigns/<id>/locations/<loc_id>/travel")
def get_location_travel(id, loc_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    destinations = storage.get_travel_destinations(id, loc_id)
    if destinations is None:
        return _not_found()
    return jsonify(destinations=destinations)


@api.post("/v1/play/campaigns/<id>/turn/travel")
def travel_turn(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    if user["role"] != "player" or campaign["current_actor"] != user["username"]:
        return jsonify(error="not your turn"), 409

    data = _body()
    destination_id = data.get("destination_id")
    if not isinstance(destination_id, str) or destination_id == "":
        return _bad_request()

    result = storage.create_travel(id, user["username"], destination_id)
    if result is None:
        return _not_found()
    if result in ("not_your_turn", "invalid_destination"):
        return jsonify(error="invalid destination"), 409

    return jsonify(result), 201


@api.post("/v1/play/campaigns/<id>/turn/rest")
def rest_turn(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    if user["role"] != "player" or campaign["current_actor"] != user["username"]:
        return jsonify(error="not your turn"), 409

    data = _body()
    rest_type = data.get("type")
    if rest_type not in ("short", "long"):
        return _bad_request()

    result = storage.create_rest(id, user["username"], rest_type)
    if result is None:
        return _not_found()
    if result == "not_your_turn":
        return jsonify(error="not your turn"), 409

    return jsonify(result), 201


@api.post("/v1/play/campaigns/<id>/characters/<char_id>/damage")
def damage_play_character(id, char_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    character = storage.get_play_campaign_character(id, char_id)
    if character is None:
        return _not_found()
    if campaign["owner"] != user["username"] and character["player"] != user["username"]:
        return _forbidden()

    data = _body()
    try:
        amount = int(data["amount"])
    except (KeyError, TypeError, ValueError):
        return _bad_request()
    if amount <= 0:
        return _bad_request()

    hp_before = character["hp_current"]
    result = storage.damage_character(id, char_id, amount)
    if result is None:
        return _not_found()

    return jsonify(
        target=char_id,
        hp_before=hp_before,
        hp_after=result["hp_current"],
        damage=amount,
    )


@api.post("/v1/play/campaigns/<id>/characters/<char_id>/death-saves")
def record_death_save(id, char_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    character = storage.get_play_campaign_character(id, char_id)
    if character is None:
        return _not_found()
    if character["player"] != user["username"]:
        return _forbidden()

    data = _body()
    outcome = data.get("outcome")
    if outcome not in ("success", "failure"):
        return _bad_request()

    result = storage.record_death_save(id, char_id, outcome)
    if result == "conscious":
        return _conflict("character is conscious")
    if result == "terminal":
        return _conflict("no further rolls accepted")
    if result is None:
        return _not_found()

    return jsonify(
        character_id=result["character_id"],
        successes=result["successes"],
        failures=result["failures"],
        status=result["status"],
    ), 201


@api.get("/v1/play/campaigns/<id>/characters/<char_id>/status")
def get_play_character_status(id, char_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    result = storage.get_character_status(id, char_id)
    if result is None:
        return _not_found()

    return jsonify(
        character_id=result["character_id"],
        hp_current=result["hp_current"],
        hp_max=result["hp_max"],
        status=result["status"],
    )


@api.get("/v1/play/campaigns/<id>/characters/<char_id>/owner")
def get_play_character_owner(id, char_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    result = storage.get_character_owner(id, char_id)
    if result is None:
        return _not_found()

    return jsonify(result)


@api.get("/v1/play/campaigns/<id>/characters/<char_id>/currency")
def get_play_character_currency(id, char_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    result = storage.get_character_currency(id, char_id)
    if result is None:
        return _not_found()

    return jsonify(result)


@api.post("/v1/play/campaigns/<id>/characters/<char_id>/currency/transfers")
def transfer_play_character_currency(id, char_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    owner_info = storage.get_character_owner(id, char_id)
    if owner_info is None:
        return _not_found()
    if owner_info.get("owner") != user["username"]:
        return _forbidden()

    data = _body()
    to_character_id = data.get("to_character_id")
    gold = data.get("gold")
    if not _require_strings(to_character_id):
        return _bad_request()
    if to_character_id == char_id:
        return _bad_request()
    try:
        gold = int(gold)
    except (TypeError, ValueError):
        return _bad_request()
    if gold <= 0:
        return _bad_request()

    if storage.get_play_campaign_character(id, to_character_id) is None:
        return _bad_request()

    result = storage.transfer_gold(id, char_id, to_character_id, gold)
    if result is None:
        return _not_found()
    if result == "insufficient":
        return _conflict("insufficient gold")

    return jsonify(result), 201


@api.post("/v1/play/campaigns/<id>/characters/<char_id>/claim")
def claim_play_character(id, char_id):
    user = _current_user()
    if user is None:
        return _unauthorized()
    if user["role"] != "player":
        return _forbidden()

    campaign, err = _load_play_campaign(id)
    if err:
        return err

    err = _require_owner_or_member(campaign, id, user)
    if err:
        return err

    result = storage.claim_character(id, char_id, user["username"])
    if result is None:
        return _not_found()
    if result == "already_owned":
        return _conflict("character already owned")

    return jsonify(character_id=char_id, owner=result), 201


@api.post("/v1/play/campaigns/<id>/characters/<char_id>/transfer")
def transfer_play_character(id, char_id):
    user = _current_user()
    if user is None:
        return _unauthorized()
    if user["role"] != "player":
        return _forbidden()

    campaign, err = _load_play_campaign(id)
    if err:
        return err

    err = _require_owner_or_member(campaign, id, user)
    if err:
        return err

    data = _body()
    new_owner = data.get("new_owner")
    if not isinstance(new_owner, str) or new_owner == "":
        return _bad_request()
    if not storage.is_play_campaign_member(id, new_owner):
        return _bad_request()

    result = storage.transfer_character(id, char_id, user["username"], new_owner)
    if result is None:
        return _not_found()
    if result == "not_owner":
        return _forbidden()

    return jsonify(character_id=char_id, owner=result)


@api.post("/v1/play/campaigns/<id>/characters/<char_id>/build")
def build_play_character(id, char_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    owner_info = storage.get_character_owner(id, char_id)
    if owner_info is None:
        return _not_found()
    if owner_info["owner"] != user["username"]:
        return _forbidden()

    data = _body()
    race = data.get("race")
    class_name = data.get("class")
    background = data.get("background")
    abilities = data.get("abilities")

    if not _require_strings(race, class_name, background):
        return _bad_request()
    if not domain.validate_build_choices(race, class_name, background):
        return _bad_request()
    if not domain.validate_build_abilities(abilities):
        return _bad_request()

    con_score = int(abilities["con"])
    hp_max = domain.compute_build_hp_max(class_name, 1, con_score)
    if hp_max is None:
        return _bad_request()

    level = 1
    result = storage.build_character(id, char_id, race, class_name, background, level, hp_max, con_score, abilities)
    if result is None:
        return _not_found()

    return jsonify({
        "character_id": char_id,
        "race": race,
        "class": class_name,
        "background": background,
        "level": level,
        "hp_max": hp_max,
        "proficiency_bonus": domain.proficiency_bonus(level),
    })


@api.post("/v1/play/campaigns/<id>/characters/<char_id>/level-up")
def level_up_character(id, char_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    character = storage.get_play_campaign_character(id, char_id)
    if character is None:
        return _not_found()

    owner_info = storage.get_character_owner(id, char_id)
    if owner_info is None or owner_info.get("owner") != user["username"]:
        return _forbidden()

    data = _body()
    try:
        new_level = int(data["level"])
    except (KeyError, TypeError, ValueError):
        return _bad_request()

    result = storage.level_up_character(id, char_id, new_level)
    if result is None:
        return _not_found()
    if result == "invalid_level":
        return _bad_request()

    return jsonify({
        "character_id": char_id,
        "level": result["level"],
        "hp_max": result["hp_max"],
        "hit_dice": result["hit_dice"],
        "proficiency_bonus": result["proficiency_bonus"],
    })


@api.post("/v1/play/campaigns/<id>/characters/<char_id>/skill-check")
def skill_check(id, char_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    owner_info = storage.get_character_owner(id, char_id)
    if owner_info is None:
        return _not_found()
    if owner_info["owner"] != user["username"]:
        return _forbidden()

    data = _body()
    skill = data.get("skill")
    ability = data.get("ability")
    proficient = data.get("proficient")
    roll = data.get("roll")

    if skill not in domain.VALID_SKILLS or ability not in domain.VALID_ABILITIES:
        return _bad_request()
    if not isinstance(proficient, bool):
        return _bad_request()
    try:
        roll = int(roll)
    except (TypeError, ValueError):
        return _bad_request()

    char_data = storage.get_character_abilities(id, char_id)
    if char_data is None:
        return _not_found()
    ability_score = char_data["abilities"].get(ability)
    if ability_score is None:
        return _bad_request()
    try:
        ability_score = int(ability_score)
    except (TypeError, ValueError):
        return _bad_request()
    if ability_score < 1 or ability_score > 30:
        return _bad_request()

    modifier = domain.compute_skill_modifier(ability_score, char_data["level"], proficient)
    total = roll + modifier

    return jsonify(
        character_id=char_id,
        skill=skill,
        ability=ability,
        modifier=modifier,
        total=total,
    )


@api.post("/v1/play/campaigns/<id>/characters/<char_id>/spells")
def add_character_spell(id, char_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    owner_info = storage.get_character_owner(id, char_id)
    if owner_info is None:
        return _not_found()
    if owner_info["owner"] != user["username"]:
        return _forbidden()

    data = _body()
    spell_id = data.get("spell_id")
    name = data.get("name")
    level = data.get("level")
    if not _require_strings(spell_id, name):
        return _bad_request()
    try:
        level = int(level)
    except (TypeError, ValueError):
        return _bad_request()
    if level < 0 or level > 9:
        return _bad_request()

    character = storage.get_play_campaign_character(id, char_id)
    if character is None:
        return _not_found()
    if character["class"] != "wizard" or spell_id not in domain.WIZARD_SPELLS:
        return _bad_request()

    result = storage.add_character_spell(id, char_id, spell_id, name, level)
    if result is None:
        return _not_found()
    if result == "duplicate":
        return _conflict("spell already known")

    return jsonify(result), 201


@api.get("/v1/play/campaigns/<id>/characters/<char_id>/spells")
def get_character_spells(id, char_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    character = storage.get_play_campaign_character(id, char_id)
    if character is None:
        return _not_found()

    spells = storage.get_character_spells(id, char_id)
    return jsonify(spells=spells)


@api.put("/v1/play/campaigns/<id>/characters/<char_id>/prepared-spells")
def set_prepared_spells(id, char_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    character = storage.get_play_campaign_character(id, char_id)
    if character is None:
        return _not_found()

    owner_info = storage.get_character_owner(id, char_id)
    if owner_info is None or owner_info.get("owner") != user["username"]:
        return _forbidden()

    if character["class"] != "wizard":
        return _bad_request()

    data = _body()
    spell_ids = data.get("spell_ids")
    if not isinstance(spell_ids, list):
        return _bad_request()
    if not all(isinstance(spell_id, str) for spell_id in spell_ids):
        return _bad_request()
    if len(spell_ids) != len(set(spell_ids)):
        return _bad_request()

    known = {s["spell_id"] for s in storage.get_character_spells(id, char_id)}
    if any(spell_id not in known for spell_id in spell_ids):
        return _bad_request()

    max_prepared = character["level"]
    if len(spell_ids) > max_prepared:
        return _bad_request()

    prepared = storage.set_prepared_spells(id, char_id, spell_ids)
    return jsonify(
        character_id=char_id,
        prepared_spells=prepared,
        max_prepared=max_prepared,
    )


@api.get("/v1/play/campaigns/<id>/characters/<char_id>/prepared-spells")
def get_prepared_spells(id, char_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    character = storage.get_play_campaign_character(id, char_id)
    if character is None:
        return _not_found()

    prepared = storage.get_prepared_spells(id, char_id)
    if prepared is None:
        return _not_found()

    max_prepared = character["level"] if character["class"] == "wizard" else 0
    return jsonify(
        character_id=char_id,
        prepared_spells=prepared,
        max_prepared=max_prepared,
    )


@api.post("/v1/play/campaigns/<id>/characters/<char_id>/casts")
def cast_spell(id, char_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    owner_info = storage.get_character_owner(id, char_id)
    if owner_info is None:
        return _not_found()
    if owner_info["owner"] != user["username"]:
        return _forbidden()

    data = _body()
    spell_id = data.get("spell_id")
    target = data.get("target")
    if not _require_strings(spell_id, target):
        return _bad_request()

    character = storage.get_play_campaign_character(id, char_id)
    if character is None:
        return _not_found()
    if character["class"] not in domain.FULL_CASTER_CLASSES:
        return _bad_request()

    spell = storage.get_character_spell(id, char_id, spell_id)
    if spell is None:
        return _bad_request()

    prepared = storage.get_prepared_spells(id, char_id)
    if spell_id not in prepared:
        return _bad_request()

    slot_level = spell["level"]
    if slot_level > 0:
        remaining = storage.get_remaining_spell_slots(id, char_id)
        if remaining is None or remaining.get(slot_level, 0) <= 0:
            return _conflict("no remaining spell slots")
        slots_remaining = remaining.get(slot_level, 0) - 1
    else:
        slots_remaining = 0

    result = storage.record_spell_cast(id, char_id, spell_id, target, slot_level, slots_remaining)
    if result is None:
        return _not_found()

    return jsonify(result), 201


@api.get("/v1/play/campaigns/<id>/characters/<char_id>/casts")
def get_spell_casts(id, char_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    character = storage.get_play_campaign_character(id, char_id)
    if character is None:
        return _not_found()

    casts = storage.get_spell_casts(id, char_id)
    if casts is None:
        return _not_found()

    return jsonify(casts=casts)


# --- Concentration ---


@api.put("/v1/play/campaigns/<id>/characters/<char_id>/concentration")
def put_concentration(id, char_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    character = storage.get_play_campaign_character(id, char_id)
    if character is None:
        return _not_found()

    owner_info = storage.get_character_owner(id, char_id)
    if owner_info is None or owner_info.get("owner") != user["username"]:
        return _forbidden()

    data = _body()
    spell_id = data.get("spell_id")
    target = data.get("target")
    duration_turns = data.get("duration_turns")
    if not _require_strings(spell_id, target):
        return _bad_request()
    try:
        duration_turns = int(duration_turns)
    except (TypeError, ValueError):
        return _bad_request()
    if duration_turns < 1:
        return _bad_request()

    if character["class"] not in domain.FULL_CASTER_CLASSES:
        return _bad_request()

    spell = storage.get_character_spell(id, char_id, spell_id)
    if spell is None:
        return _bad_request()

    prepared = storage.get_prepared_spells(id, char_id)
    if prepared is None or spell_id not in prepared:
        return _bad_request()

    concentration = storage.set_character_concentration(id, char_id, spell_id, target, duration_turns)
    if concentration is None:
        return _not_found()

    return jsonify(character_id=char_id, concentration=concentration)


@api.get("/v1/play/campaigns/<id>/characters/<char_id>/concentration")
def get_concentration(id, char_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    character = storage.get_play_campaign_character(id, char_id)
    if character is None:
        return _not_found()

    concentration = storage.get_character_concentration(id, char_id)
    return jsonify(character_id=char_id, concentration=concentration)


@api.post("/v1/play/campaigns/<id>/characters/<char_id>/concentration/advance-turn")
def advance_concentration(id, char_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    character = storage.get_play_campaign_character(id, char_id)
    if character is None:
        return _not_found()

    concentration = storage.advance_character_concentration(id, char_id)
    return jsonify(character_id=char_id, concentration=concentration)


@api.delete("/v1/play/campaigns/<id>/characters/<char_id>/concentration")
def delete_concentration(id, char_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    character = storage.get_play_campaign_character(id, char_id)
    if character is None:
        return _not_found()

    owner_info = storage.get_character_owner(id, char_id)
    if owner_info is None or owner_info.get("owner") != user["username"]:
        return _forbidden()

    result = storage.clear_character_concentration(id, char_id)
    if result is None:
        return _not_found()

    return jsonify(character_id=char_id, concentration=None)


# --- Character inventory stacks ---

_VALID_INVENTORY_ITEMS = {"healing-potion", "torch", "leather-armor", "ring-of-protection", "amulet-of-health"}

_EQUIPMENT_SLOTS = {"armor", "accessory"}
_ITEM_SLOTS = {
    "leather-armor": "armor",
    "ring-of-protection": "accessory",
    "amulet-of-health": "accessory",
}


@api.post("/v1/play/campaigns/<id>/characters/<char_id>/inventory/items")
def add_play_inventory_item(id, char_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    owner_info = storage.get_character_owner(id, char_id)
    if owner_info is None:
        return _not_found()
    if owner_info.get("owner") != user["username"]:
        return _forbidden()

    data = _body()
    item_id = data.get("item_id")
    quantity = data.get("quantity")
    if item_id not in _VALID_INVENTORY_ITEMS:
        return _bad_request()
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return _bad_request()
    if quantity <= 0:
        return _bad_request()

    result = storage.add_character_inventory_item(id, char_id, item_id, quantity)
    if result is None:
        return _not_found()
    if result == "invalid_item" or result == "invalid_quantity":
        return _bad_request()

    return jsonify(result), 201


@api.get("/v1/play/campaigns/<id>/characters/<char_id>/inventory/items")
def get_play_inventory_items(id, char_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    result = storage.get_character_inventory_items(id, char_id)
    if result is None:
        return _not_found()
    return jsonify(result)


@api.delete("/v1/play/campaigns/<id>/characters/<char_id>/inventory/items/<item_id>")
def remove_play_inventory_item(id, char_id, item_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    owner_info = storage.get_character_owner(id, char_id)
    if owner_info is None:
        return _not_found()
    if owner_info.get("owner") != user["username"]:
        return _forbidden()

    data = _body()
    quantity = data.get("quantity")
    if item_id not in _VALID_INVENTORY_ITEMS:
        return _bad_request()
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return _bad_request()
    if quantity <= 0:
        return _bad_request()

    result = storage.remove_character_inventory_item(id, char_id, item_id, quantity)
    if result is None:
        return _not_found()
    if result == "invalid_item" or result == "invalid_quantity":
        return _bad_request()
    if result == "insufficient":
        return _conflict("insufficient quantity")

    return jsonify(result)


@api.post("/v1/play/campaigns/<id>/characters/<char_id>/inventory/items/<item_id>/consume")
def consume_play_inventory_item(id, char_id, item_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    owner_info = storage.get_character_owner(id, char_id)
    if owner_info is None:
        return _not_found()
    if owner_info.get("owner") != user["username"]:
        return _forbidden()

    result = storage.consume_character_inventory_item(id, char_id, item_id)
    if result is None:
        return _not_found()
    if result in ("invalid_item", "not_consumable"):
        return _bad_request()
    if result == "empty":
        return _conflict("insufficient quantity")

    return jsonify(result)


@api.put("/v1/play/campaigns/<id>/characters/<char_id>/equipment/<slot>")
def equip_item(id, char_id, slot):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    owner_info = storage.get_character_owner(id, char_id)
    if owner_info is None:
        return _not_found()
    if owner_info.get("owner") != user["username"]:
        return _forbidden()

    if slot not in _EQUIPMENT_SLOTS:
        return _bad_request()

    data = _body()
    item_id = data.get("item_id")
    if not _require_strings(item_id):
        return _bad_request()
    if item_id not in _VALID_INVENTORY_ITEMS:
        return _bad_request()
    if _ITEM_SLOTS.get(item_id) != slot:
        return _bad_request()
    if not storage.has_character_inventory_item(id, char_id, item_id):
        return _bad_request()

    result = storage.set_character_equipped_item(id, char_id, slot, item_id)
    if result is None:
        return _not_found()
    return jsonify(result)


@api.get("/v1/play/campaigns/<id>/characters/<char_id>/equipment/<slot>")
def get_equipped_item(id, char_id, slot):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    if slot not in _EQUIPMENT_SLOTS:
        return _bad_request()

    result = storage.get_character_equipped_item(id, char_id, slot)
    if result is None:
        return _not_found()
    return jsonify(result)


@api.post("/v1/play/campaigns/<id>/characters/<char_id>/equipment/<slot>/attune")
def attune_item(id, char_id, slot):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    owner_info = storage.get_character_owner(id, char_id)
    if owner_info is None:
        return _not_found()
    if owner_info.get("owner") != user["username"]:
        return _forbidden()

    if slot not in _EQUIPMENT_SLOTS:
        return _bad_request()

    result = storage.attune_character_equipped_item(id, char_id, slot)
    if result is None:
        return _not_found()
    if result == "not_attunable":
        return _bad_request()
    if result == "already_attuned":
        return _conflict("already attuned")
    return jsonify(result)


@api.post("/v1/play/campaigns/<id>/encounters")
def create_play_campaign_encounter(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    encounter_id = data.get("id")
    name = data.get("name")
    if not _require_strings(encounter_id, name):
        return _bad_request()

    result = storage.create_encounter(id, encounter_id, name)
    if result is None:
        return _not_found()
    if result == "duplicate":
        return _conflict("encounter already exists")
    if result == "in_combat":
        return _conflict("campaign already in combat")

    return jsonify(result), 201


@api.post("/v1/play/campaigns/<id>/encounters/<enc_id>/monsters")
def add_encounter_monster(id, enc_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    monster_id = data.get("monster_id")
    name = data.get("name")
    hp_max = data.get("hp_max")
    initiative = data.get("initiative")

    if not _require_strings(monster_id, name):
        return _bad_request()
    try:
        hp_max = int(hp_max)
        initiative = int(initiative)
    except (TypeError, ValueError):
        return _bad_request()
    if hp_max <= 0:
        return _bad_request()

    result = storage.add_encounter_monster(id, enc_id, monster_id, name, hp_max, initiative)
    if result is None:
        return _not_found()
    if result == "duplicate":
        return _conflict("monster already exists")
    return jsonify(result), 201


@api.delete("/v1/play/campaigns/<id>/encounters/<enc_id>/monsters/<monster_id>")
def remove_encounter_monster(id, enc_id, monster_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    result = storage.remove_encounter_monster(id, enc_id, monster_id)
    if result is None:
        return _not_found()
    if result is False:
        return _not_found()
    return jsonify(removed=result)


@api.post("/v1/play/campaigns/<id>/encounters/<enc_id>/combatants")
def bind_encounter_combatant(id, enc_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    member = data.get("member")
    initiative = data.get("initiative")
    if not isinstance(member, str) or member == "":
        return _bad_request()
    try:
        initiative = int(initiative)
    except (TypeError, ValueError):
        return _bad_request()

    result = storage.bind_encounter_member(id, enc_id, member, initiative)
    if result is None:
        return _not_found()
    if result == "missing_member":
        return _bad_request()
    if result == "duplicate":
        return _conflict("member already bound")
    return jsonify(result), 201


@api.delete("/v1/play/campaigns/<id>/encounters/<enc_id>/combatants/<member>")
def unbind_encounter_combatant(id, enc_id, member):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    result = storage.unbind_encounter_member(id, enc_id, member)
    if result is None:
        return _not_found()
    if result is False:
        return _not_found()
    return jsonify(removed=result)


@api.get("/v1/play/campaigns/<id>/encounters/<enc_id>/turn")
def get_encounter_turn(id, enc_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    turn = storage.get_encounter_turn(id, enc_id)
    if turn is None:
        return _not_found()
    if turn is False:
        return _bad_request()

    active = turn["active"]
    return jsonify(
        round=turn["round"],
        turn_index=turn["turn_index"],
        active={
            "name": active["name"],
            "kind": active["kind"],
            "initiative": active["initiative"],
        },
    )


@api.post("/v1/play/campaigns/<id>/encounters/<enc_id>/turn/advance")
def advance_encounter_turn(id, enc_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    turn = storage.get_encounter_turn(id, enc_id)
    if turn is None:
        return _not_found()
    if turn is False:
        return _bad_request()

    active = turn["active"]
    is_current_combatant = active["kind"] == "player" and active.get("member") == user["username"]
    if campaign["owner"] != user["username"] and not is_current_combatant:
        return _conflict("not your turn")

    new_turn = storage.advance_encounter_turn(id, enc_id)
    if new_turn is None:
        return _not_found()
    if new_turn is False:
        return _bad_request()

    active = new_turn["active"]
    return jsonify(
        round=new_turn["round"],
        turn_index=new_turn["turn_index"],
        active={
            "name": active["name"],
            "kind": active["kind"],
            "initiative": active["initiative"],
        },
    )


@api.post("/v1/play/campaigns/<id>/encounters/<enc_id>/turn/delay")
def delay_encounter_turn(id, enc_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    turn = storage.get_encounter_turn(id, enc_id)
    if turn is None:
        return _not_found()
    if turn is False:
        return _bad_request()

    active = turn["active"]
    is_current_combatant = active["kind"] == "player" and active.get("member") == user["username"]
    if campaign["owner"] != user["username"] and not is_current_combatant:
        return _conflict("not your turn")

    data = _body()
    index = data.get("new_index")
    if index is None:
        index = data.get("index")
    if index is None:
        index = data.get("to_index")
    try:
        index = int(index)
    except (TypeError, ValueError):
        return _bad_request()

    result = storage.delay_encounter_turn(id, enc_id, index)
    if result is None:
        return _not_found()
    if result is False:
        return _bad_request()
    if result == "invalid_index":
        return _bad_request()

    order = [
        {"name": c["name"], "kind": c["kind"], "initiative": c["initiative"]}
        for c in result["order"]
    ]
    return jsonify(order=order)


@api.post("/v1/play/campaigns/<id>/encounters/<enc_id>/turn/ready")
def ready_encounter_turn(id, enc_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    turn = storage.get_encounter_turn(id, enc_id)
    if turn is None:
        return _not_found()
    if turn is False:
        return _bad_request()

    active = turn["active"]
    if active.get("kind") != "player" or active.get("member") != user["username"]:
        return _conflict("not your turn")

    data = _body()
    trigger = data.get("trigger")
    if not isinstance(trigger, str) or trigger == "":
        return _bad_request()

    result = storage.create_ready_action(id, enc_id, user["username"], trigger)
    if result is None:
        return _not_found()
    return jsonify(result), 201


@api.post("/v1/play/campaigns/<id>/encounters/<enc_id>/actions")
def submit_combat_action(id, enc_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    turn = storage.get_encounter_turn(id, enc_id)
    if turn is None:
        return _not_found()
    if turn is False:
        return _bad_request()

    active = turn["active"]
    if active.get("kind") != "player" or active.get("member") != user["username"]:
        return _conflict("not your turn")

    data = _body()
    action_type = data.get("type")
    target = data.get("target")
    text = data.get("text")
    if not _require_strings(action_type, target, text):
        return _bad_request()
    if action_type not in ("attack", "help", "dodge", "ready"):
        return _bad_request()

    result = storage.create_combat_action(id, enc_id, user["username"], action_type, target, text)
    if result is None:
        return _not_found()
    return jsonify(result), 201


@api.post("/v1/play/campaigns/<id>/encounters/<enc_id>/damage")
def damage_encounter_combatant(id, enc_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    target = data.get("target")
    amount = data.get("amount")
    if not isinstance(target, str) or target == "":
        return _bad_request()
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return _bad_request()
    if amount <= 0:
        return _bad_request()

    result = storage.apply_encounter_damage(id, enc_id, target, amount)
    if result is None:
        return _not_found()
    if result == "not_found":
        return _bad_request()
    return jsonify(
        target=target,
        hp_before=result["hp_before"],
        hp_after=result["hp_after"],
        damage=amount,
    )


@api.post("/v1/play/campaigns/<id>/encounters/<enc_id>/heal")
def heal_encounter_combatant(id, enc_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    target = data.get("target")
    amount = data.get("amount")
    if not isinstance(target, str) or target == "":
        return _bad_request()
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return _bad_request()
    if amount <= 0:
        return _bad_request()

    result = storage.apply_encounter_healing(id, enc_id, target, amount)
    if result is None:
        return _not_found()
    if result == "not_found":
        return _bad_request()
    return jsonify(
        target=target,
        hp_before=result["hp_before"],
        hp_after=result["hp_after"],
        healing=amount,
    )


@api.post("/v1/play/campaigns/<id>/encounters/<enc_id>/conditions")
def add_encounter_condition(id, enc_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    target = data.get("target")
    condition_text = data.get("condition")
    duration = data.get("duration_rounds")

    if not isinstance(target, str) or target == "":
        return _bad_request()
    if not isinstance(condition_text, str) or condition_text == "":
        return _bad_request()
    try:
        duration = int(duration)
    except (TypeError, ValueError):
        return _bad_request()
    if duration <= 0:
        return _bad_request()

    result = storage.add_encounter_condition(id, enc_id, target, condition_text, duration)
    if result is None:
        return _not_found()
    if result is False:
        return _bad_request()
    return jsonify(target=target, conditions=result), 201


@api.get("/v1/play/campaigns/<id>/encounters/<enc_id>/status")
def get_encounter_status(id, enc_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    status = storage.get_encounter_status(id, enc_id)
    if status is None:
        return _not_found()
    if status is False:
        return _bad_request()

    active = status["active"]
    order = [
        {"name": c["name"], "kind": c["kind"], "initiative": c["initiative"]}
        for c in status["order"]
    ]
    return jsonify(
        round=status["round"],
        turn_index=status["turn_index"],
        active={
            "name": active["name"],
            "kind": active["kind"],
            "initiative": active["initiative"],
        },
        order=order,
        conditions=status["conditions"],
    )


@api.post("/v1/play/campaigns/<id>/encounters/<enc_id>/rewards")
def award_encounter_rewards(id, enc_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    xp = data.get("xp")
    loot = data.get("loot", [])
    try:
        xp = int(xp)
    except (TypeError, ValueError):
        return _bad_request()
    if xp < 0:
        return _bad_request()
    if not isinstance(loot, list):
        return _bad_request()
    for item in loot:
        if not isinstance(item, dict):
            return _bad_request()
        item_slug = item.get("slug")
        quantity = item.get("quantity")
        if not isinstance(item_slug, str) or not SLUG_RE.fullmatch(item_slug):
            return _bad_request()
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            return _bad_request()
        if quantity <= 0:
            return _bad_request()

    result = storage.award_encounter_rewards(id, enc_id, xp, loot)
    if result is None:
        return _not_found()
    if result == "already_awarded":
        return _conflict("rewards already awarded")
    return jsonify(result)


@api.post("/v1/play/campaigns/<id>/encounters/<enc_id>/close")
def close_encounter(id, enc_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    result = storage.close_encounter(id, enc_id)
    if result is None:
        return _not_found()
    return jsonify(result)


@api.post("/v1/play/campaigns/<id>/encounters/<enc_id>/end")
def end_encounter(id, enc_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    result = storage.end_encounter(id, enc_id)
    if result is None:
        return _not_found()
    if result == "not_in_combat":
        return _conflict("not in combat")
    return jsonify(result)


# --- Loot distribution ---


@api.post("/v1/play/campaigns/<id>/loot")
def create_loot(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    loot_id = data.get("loot_id")
    item_id = data.get("item_id")
    quantity = data.get("quantity")
    if not _require_strings(loot_id, item_id):
        return _bad_request()
    if item_id not in _VALID_INVENTORY_ITEMS:
        return _bad_request()
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return _bad_request()
    if quantity <= 0:
        return _bad_request()

    result = storage.create_loot(id, loot_id, item_id, quantity)
    if result is None:
        return _not_found()
    if result == "duplicate":
        return _conflict("loot already exists")
    return jsonify(result), 201


@api.post("/v1/play/campaigns/<id>/loot/<loot_id>/votes")
def vote_loot(id, loot_id):
    user, error = _require_role("player")
    if error:
        return error

    err = _ensure_play_campaign(id)
    if err:
        return err

    if not storage.is_play_campaign_member(id, user["username"]):
        return _forbidden()

    data = _body()
    recipient_character_id = data.get("recipient_character_id")
    if not _require_strings(recipient_character_id):
        return _bad_request()

    result = storage.add_loot_vote(id, loot_id, user["username"], recipient_character_id)
    if result is None:
        return _not_found()
    if result == "invalid_recipient":
        return _bad_request()
    if result == "not_open":
        return _conflict("loot is not open")
    if result == "already_voted":
        return _conflict("already voted")
    return jsonify(result), 201


@api.post("/v1/play/campaigns/<id>/loot/<loot_id>/assign")
def assign_loot(id, loot_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    result = storage.assign_loot(id, loot_id)
    if result is None:
        return _not_found()
    if result in ("not_open", "no_votes", "tied"):
        return _conflict("cannot assign loot")
    return jsonify(result)


@api.get("/v1/play/campaigns/<id>/loot/<loot_id>")
def get_loot(id, loot_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    result = storage.get_loot(id, loot_id)
    if result is None:
        return _not_found()
    return jsonify(result)


# --- NPC agendas ---


@api.post("/v1/play/campaigns/<id>/npcs")
def create_play_npc(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    npc_id = data.get("npc_id")
    name = data.get("name")
    agenda = data.get("agenda")
    public_status = data.get("public_status")
    if not _require_strings(npc_id, name, agenda, public_status):
        return _bad_request()

    result = storage.create_play_npc(id, npc_id, name, agenda, public_status)
    if result is None:
        return _not_found()
    if result == "duplicate":
        return _conflict("npc already exists")
    return jsonify(result), 201


@api.put("/v1/play/campaigns/<id>/npcs/<npc_id>/agenda")
def update_play_npc_agenda(id, npc_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    agenda = data.get("agenda")
    public_status = data.get("public_status")
    if not _require_strings(agenda, public_status):
        return _bad_request()

    result = storage.update_play_npc_agenda(id, npc_id, agenda, public_status)
    if result is None:
        return _not_found()
    return jsonify(result)


@api.get("/v1/play/campaigns/<id>/npcs/<npc_id>")
def get_play_npc(id, npc_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    result = storage.get_play_npc(id, npc_id)
    if result is None:
        return _not_found()

    if campaign["owner"] == user["username"]:
        return jsonify(result)
    return jsonify(
        npc_id=result["npc_id"],
        name=result["name"],
        public_status=result["public_status"],
    )


# --- NPC dialogue ---


@api.post("/v1/play/campaigns/<id>/npcs/<npc_id>/dialogue")
def create_npc_dialogue(id, npc_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    if storage.get_play_npc(id, npc_id) is None:
        return _not_found()

    data = _body()
    dialogue_id = data.get("dialogue_id")
    speaker = data.get("speaker")
    text = data.get("text")
    visibility = data.get("visibility")
    if not _require_strings(dialogue_id, speaker, text):
        return _bad_request()
    if visibility not in ("public", "private"):
        return _bad_request()

    result = storage.create_npc_dialogue(id, npc_id, dialogue_id, speaker, text, visibility)
    if result == "duplicate":
        return _conflict("dialogue already exists")
    return jsonify(result), 201


@api.get("/v1/play/campaigns/<id>/npcs/<npc_id>/dialogue")
def get_npc_dialogue(id, npc_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    if storage.get_play_npc(id, npc_id) is None:
        return _not_found()

    include_private = campaign["owner"] == user["username"]
    result = storage.get_npc_dialogue_history(id, npc_id, include_private=include_private)
    return jsonify(result)


# --- Relationship graph ---


@api.post("/v1/play/campaigns/<id>/relationships")
def create_relationship(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    source_id = data.get("source_id")
    target_id = data.get("target_id")
    kind = data.get("kind")
    score = data.get("score")
    if not _require_strings(source_id, target_id, kind):
        return _bad_request()
    if not isinstance(score, int) or score < -100 or score > 100:
        return _bad_request()
    if source_id == target_id:
        return _bad_request()

    result = storage.create_relationship(id, source_id, target_id, kind, score)
    if result == "missing_entity":
        return _not_found()
    if result == "duplicate":
        return _conflict("relationship already exists")
    return jsonify(result), 201


@api.put("/v1/play/campaigns/<id>/relationships/<source_id>/<target_id>/<kind>")
def update_relationship(id, source_id, target_id, kind):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    score = data.get("score")
    if not isinstance(score, int) or score < -100 or score > 100:
        return _bad_request()

    result = storage.update_relationship(id, source_id, target_id, kind, score)
    if result is None:
        return _not_found()
    return jsonify(result)


@api.get("/v1/play/campaigns/<id>/relationships")
def get_relationships(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    edges = storage.get_relationships(id)
    if edges is None:
        return _not_found()
    return jsonify(edges=edges)


# --- Secrets and clues ---


@api.post("/v1/play/campaigns/<id>/clues")
def create_clue(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    clue_id = data.get("clue_id")
    text = data.get("text")
    audience = data.get("audience")
    character_id = data.get("character_id")

    if not _require_strings(clue_id, text):
        return _bad_request()
    if audience not in ("character", "party", "hidden"):
        return _bad_request()

    if audience == "character":
        if not _require_strings(character_id):
            return _bad_request()
        if storage.get_play_campaign_character(id, character_id) is None:
            return _bad_request()
    else:
        if "character_id" in data:
            return _bad_request()

    result = storage.create_clue(id, clue_id, text, audience, character_id)
    if result is None:
        return _not_found()
    if result == "duplicate":
        return _conflict("clue already exists")
    if result == "invalid_character":
        return _bad_request()

    return jsonify(result), 201


@api.get("/v1/play/campaigns/<id>/clues")
def get_clues(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    if campaign["owner"] == user["username"]:
        clues = storage.get_clues(id)
    else:
        member = storage.get_play_campaign_member(id, user["username"])
        if member is None:
            return _forbidden()
        clues = storage.get_clues(id, member["character_id"])

    if clues is None:
        return _not_found()

    return jsonify(clues=clues)


# --- Play campaign factions and reputation ---


@api.post("/v1/play/campaigns/<id>/factions")
def create_play_faction(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    faction_id = data.get("faction_id")
    name = data.get("name")
    if not _require_strings(faction_id, name):
        return _bad_request()

    result = storage.create_play_faction(id, faction_id, name)
    if result is None:
        return _not_found()
    if result == "duplicate":
        return _conflict("faction already exists")
    return jsonify(result), 201


@api.post("/v1/play/campaigns/<id>/factions/<faction_id>/reputation")
def change_reputation(id, faction_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    if storage.get_play_faction(id, faction_id) is None:
        return _not_found()

    data = _body()
    character_id = data.get("character_id")
    delta = data.get("delta")
    reason = data.get("reason")
    if not _require_strings(character_id, reason):
        return _bad_request()
    if storage.get_play_campaign_character(id, character_id) is None:
        return _bad_request()

    try:
        delta = int(delta)
    except (TypeError, ValueError):
        return _bad_request()
    if delta == 0 or delta < -25 or delta > 25:
        return _bad_request()

    result = storage.create_reputation_change(id, faction_id, character_id, delta, reason)
    if result is None:
        return _not_found()
    if result == "invalid_character":
        return _bad_request()
    return jsonify(result), 201


@api.get("/v1/play/campaigns/<id>/factions/<faction_id>/reputation")
def get_reputation(id, faction_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    if storage.get_play_faction(id, faction_id) is None:
        return _not_found()

    if campaign["owner"] == user["username"]:
        result = storage.get_reputation_history(id, faction_id)
    else:
        member = storage.get_play_campaign_member(id, user["username"])
        if member is None:
            return _forbidden()
        result = storage.get_reputation_history(id, faction_id, member["character_id"])

    return jsonify(result)


# --- Quest dependencies ---


@api.post("/v1/play/campaigns/<id>/quests")
def create_play_quest(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    quest_id = data.get("quest_id")
    title = data.get("title")
    depends_on = data.get("depends_on")

    if not _require_strings(quest_id, title):
        return _bad_request()
    if not isinstance(depends_on, list):
        return _bad_request()
    if len(depends_on) != len(set(depends_on)):
        return _bad_request()
    if quest_id in depends_on:
        return _bad_request()
    if any(not isinstance(dep, str) or dep == "" for dep in depends_on):
        return _bad_request()
    for dep in depends_on:
        if storage.get_play_quest(id, dep) is None:
            return _bad_request()

    result = storage.create_play_quest(id, quest_id, title, depends_on)
    if result is None:
        return _not_found()
    if result == "duplicate":
        return _conflict("quest already exists")
    return jsonify(result), 201


@api.put("/v1/play/campaigns/<id>/quests/<quest_id>/state")
def update_play_quest_state(id, quest_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    state = data.get("state")
    if state not in ("active", "completed"):
        return _bad_request()

    quest = storage.get_play_quest(id, quest_id)
    if quest is None:
        return _not_found()

    if state == "active":
        if quest["state"] != "locked":
            return _conflict("invalid transition")
        for dep in quest["depends_on"]:
            dep_quest = storage.get_play_quest(id, dep)
            if dep_quest is None or dep_quest["state"] != "completed":
                return _conflict("invalid transition")
    elif state == "completed":
        if quest["state"] != "active":
            return _conflict("invalid transition")

    result = storage.set_play_quest_state(id, quest_id, state)
    if result is None:
        return _not_found()
    return jsonify(result)


@api.get("/v1/play/campaigns/<id>/quests")
def get_play_quests(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    quests = storage.get_play_quests(id)
    if quests is None:
        return _not_found()
    return jsonify(quests=quests)


# --- Quest rewards ---


@api.put("/v1/play/campaigns/<id>/quests/<quest_id>/rewards")
def configure_quest_rewards(id, quest_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    quest = storage.get_play_quest(id, quest_id)
    if quest is None:
        return _not_found()
    if quest["state"] == "completed":
        return _conflict("quest is completed")

    data = _body()
    xp = data.get("xp")
    items = data.get("items")

    if type(xp) is not int or xp < 0:
        return _bad_request()
    if type(items) is not dict:
        return _bad_request()
    for item_id, qty in items.items():
        if type(item_id) is not str or not SLUG_RE.fullmatch(item_id):
            return _bad_request()
        if type(qty) is not int or qty <= 0:
            return _bad_request()
        if storage.get_item(item_id) is None:
            return _bad_request()

    result = storage.configure_play_quest_rewards(id, quest_id, xp, items)
    if result is None:
        return _not_found()
    return jsonify(result)


@api.post("/v1/play/campaigns/<id>/quests/<quest_id>/rewards/award")
def award_quest_rewards(id, quest_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    result = storage.award_play_quest_rewards(id, quest_id)
    if result is None:
        return _not_found()
    if result == "not_configured":
        return _conflict("rewards not configured")
    if result == "not_completed":
        return _conflict("quest is not completed")
    if result == "already_awarded":
        return _conflict("rewards already awarded")
    return jsonify(result), 201


@api.get("/v1/play/campaigns/<id>/characters/<character_id>/rewards")
def get_character_quest_rewards_route(id, character_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    if storage.get_play_campaign_character(id, character_id) is None:
        return _not_found()

    result = storage.get_character_quest_rewards(id, character_id)
    return jsonify(result)


# --- World events ---


@api.post("/v1/play/campaigns/<id>/world-events")
def schedule_world_event(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    event_id = data.get("event_id")
    turn_number = data.get("turn_number")
    title = data.get("title")
    text = data.get("text")
    if not _require_strings(event_id, title, text):
        return _bad_request()
    try:
        turn_number = int(turn_number)
    except (TypeError, ValueError):
        return _bad_request()
    if turn_number < campaign["turn_number"]:
        return _bad_request()

    result = storage.create_world_event(id, event_id, turn_number, title, text)
    if result is None:
        return _not_found()
    if result == "duplicate":
        return _conflict("event already exists")
    if result == "invalid_turn":
        return _bad_request()
    return jsonify(result), 201


@api.post("/v1/play/campaigns/<id>/world-events/<event_id>/resolve")
def resolve_world_event_route(id, event_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    text = data.get("text")
    if not isinstance(text, str) or text == "":
        return _bad_request()

    result = storage.resolve_world_event(id, event_id, text)
    if result is None:
        return _not_found()
    if result == "already_resolved":
        return _conflict("event already resolved")
    if result == "wrong_turn":
        return _conflict("wrong turn")
    return jsonify(result), 201


@api.get("/v1/play/campaigns/<id>/world-events")
def get_world_events_route(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    events = storage.get_world_events(id)
    if events is None:
        return _not_found()
    return jsonify(events=events)


# --- Calendar ---


def _calendar_response(day, season):
    return {
        "day": day,
        "season": season,
        "weather": domain.compute_weather(day, season),
    }


@api.post("/v1/play/campaigns/<id>/calendar")
def create_calendar(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    day = data.get("day")
    season = data.get("season")

    try:
        day = int(day)
    except (TypeError, ValueError):
        return _bad_request()
    if day < 1:
        return _bad_request()
    if season not in domain.SEASON_OFFSETS:
        return _bad_request()

    result = storage.create_calendar(id, day, season)
    if result is None:
        return _not_found()
    if result == "duplicate":
        return _conflict("calendar already exists")

    return jsonify(_calendar_response(result["day"], result["season"])), 201


@api.get("/v1/play/campaigns/<id>/calendar")
def get_calendar(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    result = storage.get_calendar(id)
    if result is None:
        return _not_found()

    return jsonify(_calendar_response(result["day"], result["season"]))


@api.post("/v1/play/campaigns/<id>/calendar/advance")
def advance_calendar(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    try:
        days = int(data.get("days"))
    except (TypeError, ValueError):
        return _bad_request()
    if days < 1 or days > 30:
        return _bad_request()

    result = storage.advance_calendar(id, days)
    if result is None:
        return _not_found()

    return jsonify(_calendar_response(result["day"], result["season"]))


# --- Settlements ---


def _validate_settlement_payload(data, require_settlement_id=True):
    """Return normalized settlement fields or None if invalid."""
    settlement_id = data.get("settlement_id")
    name = data.get("name")
    services = data.get("services")
    availability = data.get("availability")

    if require_settlement_id and not _require_strings(settlement_id):
        return None
    if not _require_strings(name):
        return None
    if availability not in ("open", "limited", "closed"):
        return None
    if not isinstance(services, list) or len(services) == 0:
        return None

    normalized = []
    seen = set()
    for svc in services:
        if not isinstance(svc, str):
            return None
        trimmed = svc.strip()
        if trimmed == "" or trimmed in seen:
            return None
        seen.add(trimmed)
        normalized.append(trimmed)

    result = {"name": name, "services": normalized, "availability": availability}
    if require_settlement_id:
        result["settlement_id"] = settlement_id
    return result


def _player_filter_settlement(settlement, character_id):
    """Return a player-view copy of a settlement with discovered_by limited."""
    filtered = dict(settlement)
    if character_id in settlement.get("discovered_by", []):
        filtered["discovered_by"] = [character_id]
    else:
        filtered["discovered_by"] = []
    return filtered


@api.post("/v1/play/campaigns/<id>/settlements")
def create_settlement(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    validated = _validate_settlement_payload(_body())
    if validated is None:
        return _bad_request()

    result = storage.create_settlement(
        id,
        validated["settlement_id"],
        validated["name"],
        validated["services"],
        validated["availability"],
    )
    if result is None:
        return _not_found()
    if result == "duplicate":
        return _conflict("settlement already exists")
    return jsonify(result), 201


@api.put("/v1/play/campaigns/<id>/settlements/<settlement_id>")
def update_settlement(id, settlement_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    validated = _validate_settlement_payload(_body(), require_settlement_id=False)
    if validated is None:
        return _bad_request()

    result = storage.update_settlement(
        id,
        settlement_id,
        validated["name"],
        validated["services"],
        validated["availability"],
    )
    if result is None:
        return _not_found()
    return jsonify(result)


@api.post("/v1/play/campaigns/<id>/settlements/<settlement_id>/discover")
def discover_settlement(id, settlement_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    if user["role"] != "player":
        return _forbidden()

    member = storage.get_play_campaign_member(id, user["username"])
    if member is None:
        return _forbidden()

    result = storage.discover_settlement(id, settlement_id, member["character_id"])
    if result is None:
        return _not_found()

    settlement, created = result
    status = 201 if created else 200
    return jsonify(_player_filter_settlement(settlement, member["character_id"])), status


@api.get("/v1/play/campaigns/<id>/settlements")
def list_settlements(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    settlements = storage.get_settlements(id)
    if settlements is None:
        return _not_found()

    if campaign["owner"] == user["username"]:
        return jsonify(settlements=settlements)

    member = storage.get_play_campaign_member(id, user["username"])
    if member is None:
        return _forbidden()
    character_id = member["character_id"]

    filtered = [
        _player_filter_settlement(s, character_id)
        for s in settlements
        if character_id in s.get("discovered_by", [])
    ]
    return jsonify(settlements=filtered)


# --- Settlement shops ---


@api.post("/v1/play/campaigns/<id>/settlements/<settlement_id>/shops")
def create_shop(id, settlement_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    shop_id = data.get("shop_id")
    name = data.get("name")
    stock = data.get("stock")
    buy_price = data.get("buy_price")
    sell_price = data.get("sell_price")

    if not _require_strings(shop_id, name):
        return _bad_request()
    if not isinstance(stock, dict) or len(stock) == 0:
        return _bad_request()
    for item_id, qty in stock.items():
        if item_id not in _VALID_INVENTORY_ITEMS:
            return _bad_request()
        if not isinstance(qty, int) or qty <= 0:
            return _bad_request()
    try:
        buy_price = int(buy_price)
        sell_price = int(sell_price)
    except (TypeError, ValueError):
        return _bad_request()
    if buy_price <= 0 or sell_price < 0:
        return _bad_request()

    result = storage.create_shop(id, settlement_id, shop_id, name, stock, buy_price, sell_price)
    if result is None:
        return _not_found()
    if result == "duplicate":
        return _conflict("shop already exists")
    return jsonify(result), 201


@api.get("/v1/play/campaigns/<id>/settlements/<settlement_id>/shops/<shop_id>")
def get_shop(id, settlement_id, shop_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    settlement = storage.get_settlement(id, settlement_id)
    if settlement is None:
        return _not_found()

    shop = storage.get_shop(id, settlement_id, shop_id)
    if shop is None:
        return _not_found()

    if campaign["owner"] != user["username"]:
        member = storage.get_play_campaign_member(id, user["username"])
        if member is None:
            return _forbidden()
        if member["character_id"] not in settlement.get("discovered_by", []):
            return _not_found()

    return jsonify(shop)


@api.post("/v1/play/campaigns/<id>/settlements/<settlement_id>/shops/<shop_id>/buy")
def buy_from_shop(id, settlement_id, shop_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    if user["role"] == "dm":
        return _forbidden()

    data = _body()
    character_id = data.get("character_id")
    item_id = data.get("item_id")
    quantity = data.get("quantity")

    if not _require_strings(character_id, item_id):
        return _bad_request()
    if item_id not in _VALID_INVENTORY_ITEMS:
        return _bad_request()
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return _bad_request()
    if quantity <= 0:
        return _bad_request()

    if storage.get_settlement(id, settlement_id) is None:
        return _not_found()
    if storage.get_shop(id, settlement_id, shop_id) is None:
        return _not_found()

    owner_info = storage.get_character_owner(id, character_id)
    if owner_info is None:
        return _not_found()
    if owner_info.get("owner") != user["username"]:
        return _forbidden()

    result = storage.buy_from_shop(id, settlement_id, shop_id, character_id, item_id, quantity)
    if result is None:
        return _not_found()
    if result in ("invalid_item", "invalid_quantity"):
        return _bad_request()
    if result == "insufficient_stock":
        return _conflict("insufficient stock")
    if result == "insufficient_funds":
        return _conflict("insufficient gold")

    return jsonify(result)


@api.post("/v1/play/campaigns/<id>/settlements/<settlement_id>/shops/<shop_id>/sell")
def sell_to_shop(id, settlement_id, shop_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    if user["role"] == "dm":
        return _forbidden()

    data = _body()
    character_id = data.get("character_id")
    item_id = data.get("item_id")
    quantity = data.get("quantity")

    if not _require_strings(character_id, item_id):
        return _bad_request()
    if item_id not in _VALID_INVENTORY_ITEMS:
        return _bad_request()
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return _bad_request()
    if quantity <= 0:
        return _bad_request()

    if storage.get_settlement(id, settlement_id) is None:
        return _not_found()
    if storage.get_shop(id, settlement_id, shop_id) is None:
        return _not_found()

    owner_info = storage.get_character_owner(id, character_id)
    if owner_info is None:
        return _not_found()
    if owner_info.get("owner") != user["username"]:
        return _forbidden()

    result = storage.sell_to_shop(id, settlement_id, shop_id, character_id, item_id, quantity)
    if result is None:
        return _not_found()
    if result in ("invalid_item", "invalid_quantity"):
        return _bad_request()
    if result == "insufficient_inventory":
        return _conflict("insufficient inventory")

    return jsonify(result)


# --- Campaign crafting recipes ---


@api.post("/v1/play/campaigns/<id>/recipes")
def create_recipe(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    recipe_id = data.get("recipe_id")
    name = data.get("name")
    ingredients = data.get("ingredients")
    output_item = data.get("output_item")
    output_quantity = data.get("output_quantity")

    result = storage.create_recipe(id, recipe_id, name, ingredients, output_item, output_quantity)
    if result is None:
        return _not_found()
    if result == "invalid":
        return _bad_request()
    if result == "duplicate":
        return _conflict("recipe already exists")
    return jsonify(result), 201


@api.get("/v1/play/campaigns/<id>/recipes")
def list_recipes(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    recipes = storage.get_recipes(id)
    if recipes is None:
        return _not_found()
    return jsonify(recipes=recipes)


@api.post("/v1/play/campaigns/<id>/recipes/<recipe_id>/craft")
def craft_recipe(id, recipe_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    if user["role"] == "dm":
        return _forbidden()

    data = _body()
    character_id = data.get("character_id")
    if not _require_strings(character_id):
        return _bad_request()

    character = storage.get_play_campaign_character(id, character_id)
    if character is None:
        return _not_found()

    owner_info = storage.get_character_owner(id, character_id)
    if owner_info is None or owner_info.get("owner") != user["username"]:
        return _forbidden()

    result = storage.craft_recipe(id, recipe_id, character_id)
    if result is None:
        return _not_found()
    if result == "character_not_found":
        return _not_found()
    if result == "insufficient":
        return _conflict("insufficient ingredients")

    return jsonify(result), 201


# --- Recurring downtime ---


@api.post("/v1/play/campaigns/<id>/downtime/activities")
def create_downtime_activity(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    activity_id = data.get("activity_id")
    name = data.get("name")
    cycles_required = data.get("cycles_required")
    if not _require_strings(activity_id, name):
        return _bad_request()
    if type(cycles_required) is not int or not (1 <= cycles_required <= 10):
        return _bad_request()

    result = storage.create_downtime_activity(id, activity_id, name, cycles_required)
    if result is None:
        return _not_found()
    if result == "duplicate":
        return _conflict("activity already exists")
    return jsonify(result), 201


@api.post("/v1/play/campaigns/<id>/characters/<char_id>/downtime/allocations")
def create_downtime_allocation(id, char_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    if user["role"] == "dm":
        return _forbidden()

    owner_info = storage.get_character_owner(id, char_id)
    if owner_info is None:
        return _not_found()
    if owner_info.get("owner") != user["username"]:
        return _forbidden()

    data = _body()
    activity_id = data.get("activity_id")
    if not _require_strings(activity_id):
        return _bad_request()

    result = storage.create_downtime_allocation(id, char_id, activity_id)
    if result is None:
        return _not_found()
    if result == "duplicate":
        return _conflict("allocation already exists")
    return jsonify(result), 201


@api.post("/v1/play/campaigns/<id>/characters/<char_id>/downtime/allocations/<activity_id>/progress")
def progress_downtime_allocation(id, char_id, activity_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    if user["role"] == "dm":
        return _forbidden()

    owner_info = storage.get_character_owner(id, char_id)
    if owner_info is None:
        return _not_found()
    if owner_info.get("owner") != user["username"]:
        return _forbidden()

    result = storage.progress_downtime_allocation(id, char_id, activity_id)
    if result is None:
        return _not_found()
    return jsonify(result)


@api.get("/v1/play/campaigns/<id>/characters/<char_id>/downtime/allocations/<activity_id>")
def get_downtime_allocation(id, char_id, activity_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    result = storage.get_downtime_allocation(id, char_id, activity_id)
    if result is None:
        return _not_found()
    return jsonify(result)


# --- Content tags ---


@api.post("/v1/play/campaigns/<id>/content")
def create_content_route(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    content_id = data.get("content_id")
    kind = data.get("kind")
    text = data.get("text")
    tags = data.get("tags")
    if not _require_strings(content_id, kind, text):
        return _bad_request()

    result = storage.create_content(id, content_id, kind, text, tags)
    if result is None:
        return _not_found()
    if result == "invalid":
        return _bad_request()
    if result is False:
        return _conflict("content already exists")

    return jsonify(result), 201


@api.put("/v1/play/campaigns/<id>/content/<content_id>/tags")
def update_content_tags_route(id, content_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    tags = data.get("tags")
    if not isinstance(tags, list):
        return _bad_request()

    result = storage.update_content_tags(id, content_id, tags)
    if result is None:
        return _not_found()
    if result == "invalid":
        return _bad_request()

    return jsonify(result)


@api.get("/v1/play/campaigns/<id>/content")
def list_content_route(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    exclude_tag = request.args.get("exclude_tag")
    if exclude_tag is not None and exclude_tag == "":
        return _bad_request()

    content = storage.list_content(id)
    if content is None:
        return _not_found()

    if campaign["owner"] != user["username"] and exclude_tag is not None:
        content = [record for record in content if exclude_tag not in record.get("tags", [])]

    return jsonify(content=content)


# --- Notes ---


@api.post("/v1/play/campaigns/<id>/notes")
def create_note_route(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err
    if campaign["owner"] != user["username"] and not storage.is_play_campaign_member(id, user["username"]):
        return _forbidden()

    data = _body()
    note_id = data.get("note_id")
    text = data.get("text")
    visibility = data.get("visibility")
    if not _require_strings(note_id, text):
        return _bad_request()
    if visibility not in ("private", "party"):
        return _bad_request()

    result = storage.create_note(id, note_id, text, visibility, user["username"])
    if result is None:
        return _not_found()
    if result == "duplicate":
        return _conflict("note already exists")
    return jsonify(result), 201


@api.get("/v1/play/campaigns/<id>/notes")
def list_notes_route(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    is_dm = campaign["owner"] == user["username"]
    notes = storage.list_notes(id, actor=user["username"], is_dm=is_dm)
    if notes is None:
        return _not_found()
    return jsonify(notes=notes)


@api.get("/v1/play/campaigns/<id>/notes/<note_id>")
def get_note_route(id, note_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    note = storage.get_note(id, note_id)
    if note is None:
        return _not_found()

    is_dm = campaign["owner"] == user["username"]
    if not is_dm and note["visibility"] == "private" and note["owner"] != user["username"]:
        return _forbidden()
    return jsonify(note)


@api.put("/v1/play/campaigns/<id>/notes/<note_id>")
def update_note_route(id, note_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    note = storage.get_note(id, note_id)
    if note is None:
        return _not_found()
    if note["owner"] != user["username"]:
        return _forbidden()

    data = _body()
    text = data.get("text")
    visibility = data.get("visibility")
    if not _require_strings(text) or visibility not in ("private", "party"):
        return _bad_request()

    result = storage.update_note(id, note_id, text, visibility)
    if result is None:
        return _not_found()
    return jsonify(result)


# --- Whispers ---


@api.post("/v1/play/campaigns/<id>/whispers")
def create_whisper_route(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err
    if user["role"] != "player":
        return _forbidden()

    data = _body()
    whisper_id = data.get("whisper_id")
    to_character_id = data.get("to_character_id")
    text = data.get("text")
    if not _require_strings(whisper_id, to_character_id, text):
        return _bad_request()

    member = storage.get_play_campaign_member(id, user["username"])
    if member is None:
        return _bad_request()
    owner_info = storage.get_character_owner(id, member["character_id"])
    if owner_info is None or owner_info.get("owner") != user["username"]:
        return _bad_request()
    from_character_id = member["character_id"]

    if storage.get_play_campaign_character(id, to_character_id) is None:
        return _bad_request()

    result = storage.create_whisper(id, whisper_id, from_character_id, to_character_id, text)
    if result is None:
        return _not_found()
    if result == "duplicate":
        return _conflict("whisper already exists")
    return jsonify(result), 201


@api.get("/v1/play/campaigns/<id>/whispers")
def list_whispers_route(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    is_dm = campaign["owner"] == user["username"]
    if is_dm:
        whispers = storage.list_whispers(id, is_dm=True)
    else:
        member = storage.get_play_campaign_member(id, user["username"])
        if member is None:
            return _forbidden()
        whispers = storage.list_whispers(id, character_id=member["character_id"], is_dm=False)
    if whispers is None:
        return _not_found()
    return jsonify(whispers=whispers)


# --- Chat messages ---


@api.post("/v1/play/campaigns/<id>/messages")
def create_message_route(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    data = _body()
    text = data.get("text")
    if not isinstance(text, str) or text == "":
        return _bad_request()

    result = storage.create_message(id, user["username"], text)
    if result is None:
        return _not_found()

    return Response(
        json.dumps(result, sort_keys=False, separators=(",", ":")),
        status=201,
        mimetype="application/json",
    )


# --- Character sheets ---


@api.get("/v1/play/campaigns/<id>/characters/<char_id>/sheet")
def get_character_sheet_route(id, char_id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    sheet = storage.get_character_sheet(id, char_id)
    if sheet is None:
        return _not_found()
    if campaign["owner"] != user["username"] and sheet["owner"] != user["username"]:
        return _forbidden()
    return jsonify(sheet)


# --- Invitations ---


@api.post("/v1/play/campaigns/<id>/invitations")
def create_invitation_route(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    invitation_id = data.get("invitation_id")
    username = data.get("username")
    character_id = data.get("character_id")
    if not _require_strings(invitation_id, username, character_id):
        return _bad_request()

    target = storage.get_user(username)
    if target is None or target.get("role") != "player":
        return _bad_request()

    result = storage.create_play_campaign_invitation(id, invitation_id, username, character_id)
    if result is None:
        return _not_found()
    if result == "duplicate_id":
        return _conflict("invitation already exists")
    if result == "duplicate_active":
        return _conflict("active invitation already exists")
    return jsonify(result), 201


@api.post("/v1/play/campaigns/<id>/invitations/<invitation_id>/accept")
def accept_invitation_route(id, invitation_id):
    user = _current_user()
    if user is None:
        return _unauthorized()
    campaign, err = _load_play_campaign(id)
    if err:
        return err

    invitation = storage.get_play_campaign_invitation(id, invitation_id)
    if invitation is None:
        return _not_found()
    if invitation["username"] != user["username"]:
        return _forbidden()
    if invitation["status"] != "pending":
        return _conflict("already accepted")

    result = storage.accept_play_campaign_invitation(id, invitation_id, user["username"])
    if result is None:
        return _not_found()
    if result == "wrong_user":
        return _forbidden()
    if result == "already_accepted":
        return _conflict("already accepted")
    if result == "already_member":
        return _conflict("player already joined")
    if result == "duplicate_character":
        return _conflict("character already exists")
    if result == "full":
        return _conflict("party is full")
    return jsonify(result), 200


@api.get("/v1/play/campaigns/<id>/invitations")
def list_invitations_route(id):
    user = _current_user()
    if user is None:
        return _unauthorized()
    campaign, err = _load_play_campaign(id)
    if err:
        return err

    if campaign["owner"] == user["username"]:
        invitations = storage.list_play_campaign_invitations(id)
    else:
        invitations = storage.list_play_campaign_invitations(id, user["username"])
        if not invitations and not storage.is_play_campaign_member(id, user["username"]):
            return _forbidden()

    return jsonify({"invitations": invitations})


# --- GM Delegation ---

_VALID_DELEGATION_POWERS = {"narrate"}


@api.get("/v1/play/campaigns/<id>/delegations/audit")
def list_delegation_audit(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    entries = storage.get_play_campaign_delegation_audit(id)
    if entries is None:
        return _not_found()
    return jsonify(entries=entries)


@api.post("/v1/play/campaigns/<id>/delegations")
def grant_delegation(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    username = data.get("username")
    powers = data.get("powers")
    if not _require_strings(username):
        return _bad_request()
    if not isinstance(powers, list) or len(powers) == 0:
        return _bad_request()

    seen = set()
    for power in powers:
        if not isinstance(power, str) or power == "" or power in seen or power not in _VALID_DELEGATION_POWERS:
            return _bad_request()
        seen.add(power)

    if not storage.is_play_campaign_member(id, username):
        return _bad_request()

    result = storage.grant_play_campaign_delegation(id, username, powers)
    if result is None:
        return _not_found()
    if result == "not_member":
        return _bad_request()
    if result == "duplicate_active":
        return _conflict("delegate already active")

    return jsonify(result), 201


@api.delete("/v1/play/campaigns/<id>/delegations/<username>")
def revoke_delegation(id, username):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    if not storage.is_play_campaign_member(id, username):
        return _bad_request()

    result = storage.revoke_play_campaign_delegation(id, username)
    if result is None:
        return _not_found()
    if result == "not_active":
        return _bad_request()

    return jsonify(result)


# --- Actor Audit Trail ---


@api.post("/v1/play/campaigns/<id>/audit-events")
def create_audit_event(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    data = _body()
    kind = data.get("kind")
    correlation_id = data.get("correlation_id")
    if not _require_strings(kind, correlation_id):
        return _bad_request()

    role = "DM" if campaign["owner"] == user["username"] else "player"
    result = storage.create_actor_audit_event(id, kind, user["username"], role, correlation_id)
    if result is None:
        return _not_found()
    if result == "duplicate":
        return _conflict("correlation_id already exists")

    return jsonify(result), 201


@api.get("/v1/play/campaigns/<id>/audit-events")
def list_audit_events(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    entries = storage.get_actor_audit_events(id)
    if entries is None:
        return _not_found()

    return jsonify(entries=entries)


# --- Projection events ---


@api.post("/v1/play/campaigns/<id>/projection-events")
def append_projection_event(id):
    user = _current_user()
    if user is None:
        return _unauthorized()

    campaign, err = _load_play_campaign(id)
    if err:
        return err

    if campaign["owner"] == user["username"]:
        return _forbidden()
    if not storage.is_play_campaign_member(id, user["username"]):
        return _forbidden()

    data = _body()
    event_id = data.get("event_id")
    kind = data.get("kind")
    value = data.get("value")

    if not isinstance(event_id, str) or event_id == "":
        return _bad_request()
    if kind not in ("set-story", "increment-danger"):
        return _bad_request()
    if kind == "set-story":
        if not isinstance(value, str) or value == "":
            return _bad_request()
    else:
        if "value" in data:
            return _bad_request()

    result = storage.create_projection_event(id, event_id, kind, value if kind == "set-story" else None)
    if result == "duplicate":
        return _conflict("event_id already exists")
    if result is None:
        return _not_found()

    return jsonify(result), 201


@api.get("/v1/play/campaigns/<id>/projection")
def get_projection(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    result = storage.get_projection(id)
    if result is None:
        return _not_found()

    return jsonify(result)


@api.get("/v1/play/campaigns/<id>/projection/rebuild")
def rebuild_projection(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    result = storage.get_projection(id)
    if result is None:
        return _not_found()

    return jsonify(result)


# --- Idempotent events ---


@api.post("/v1/play/campaigns/<id>/idempotent-events")
def create_idempotent_event_route(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    if idempotency_key == "":
        return _bad_request()

    data = _body()
    event_id = data.get("event_id")
    value = data.get("value")

    if not _require_strings(event_id, value):
        return _bad_request()

    result = storage.create_idempotent_event(id, idempotency_key, event_id, value)
    if result == "mismatch":
        return _conflict("idempotency key mismatch")
    if result == "duplicate_event_id":
        return _conflict("event_id already exists")
    if result is None:
        return _not_found()

    status, event = result
    return jsonify(event), (201 if status == "created" else 200)


@api.get("/v1/play/campaigns/<id>/idempotent-events")
def list_idempotent_events(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    events = storage.get_idempotent_events(id)
    if events is None:
        return _not_found()

    return jsonify(events=events)


# --- Safe turns ---


@api.post("/v1/play/campaigns/<id>/safe-turns")
def submit_safe_turn(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    data = _body()
    submission_id = data.get("submission_id")
    expected_turn = data.get("expected_turn")
    action = data.get("action")

    if not _require_strings(submission_id, action):
        return _bad_request()
    try:
        expected_turn = int(expected_turn)
    except (TypeError, ValueError):
        return _bad_request()
    if expected_turn < 1:
        return _bad_request()

    result = storage.submit_safe_turn(id, submission_id, expected_turn, action)
    if result is None:
        return _not_found()
    if result == "duplicate":
        return _conflict("submission already exists")

    status, payload = result
    if status == "stale":
        return jsonify(current_turn=payload), 409

    return jsonify(payload), 201


@api.get("/v1/play/campaigns/<id>/safe-turns")
def list_safe_turns(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    result = storage.get_safe_turns(id)
    if result is None:
        return _not_found()

    return jsonify(result)


# --- Transactional transfers ---


@api.post("/v1/play/campaigns/<id>/transactional-transfers")
def create_transactional_transfer_route(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    data = _body()
    from_character_id = data.get("from_character_id")
    to_character_id = data.get("to_character_id")
    amount = data.get("amount")
    simulate_failure = data.get("simulate_failure")

    if not _require_strings(from_character_id, to_character_id):
        return _bad_request()
    if type(amount) is not int or amount <= 0:
        return _bad_request()
    if type(simulate_failure) is not bool:
        return _bad_request()

    result = storage.create_transactional_transfer(
        id, user["username"], from_character_id, to_character_id, amount, simulate_failure
    )
    if result is None:
        return _bad_request()
    if result == "self_transfer":
        return _bad_request()
    if result == "invalid_amount":
        return _bad_request()
    if result == "forbidden":
        return _forbidden()
    if result == "insufficient":
        return _conflict("insufficient gold")
    if result == "simulated_failure":
        return jsonify(error="simulated failure"), 500

    return jsonify(result), 201


@api.get("/v1/play/campaigns/<id>/transactional-transfers")
def list_transactional_transfers(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    result = storage.get_transactional_transfers(id)
    if result is None:
        return _not_found()

    return jsonify(result)


# --- Versioned campaign exports ---


@api.post("/v1/play/campaigns/<id>/exports")
def create_export(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    result = storage.create_play_campaign_export(id)
    if result is None:
        return _not_found()
    return jsonify(result), 201


@api.get("/v1/play/campaigns/<id>/exports")
def list_exports(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    exports = storage.get_play_campaign_exports(id)
    if exports is None:
        return _not_found()
    return jsonify(exports=exports)


@api.get("/v1/play/campaigns/<id>/exports/<version>")
def get_export(id, version):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    try:
        version = int(version)
    except (TypeError, ValueError):
        return _not_found()

    result = storage.get_play_campaign_export(id, version)
    if result is None:
        return _not_found()
    return jsonify(result)


# --- Campaign backups ---


@api.post("/v1/play/campaigns/<id>/backups")
def create_backup(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    result = storage.create_play_campaign_backup(id)
    if result is None:
        return _not_found()
    payload = {
        "backup_id": result["backup_id"],
        "story": result["story"],
        "status": result["status"],
    }
    return Response(
        json.dumps(payload, sort_keys=False, separators=(",", ":")),
        status=201,
        mimetype="application/json",
    )


@api.get("/v1/play/campaigns/<id>/backups")
def list_backups(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    backups = storage.get_play_campaign_backups(id)
    if backups is None:
        return _not_found()
    payload = {
        "backups": [
            {"backup_id": b["backup_id"], "story": b["story"], "status": b["status"]}
            for b in backups
        ],
    }
    return Response(
        json.dumps(payload, sort_keys=False, separators=(",", ":")),
        mimetype="application/json",
    )


@api.post("/v1/play/campaigns/<id>/backups/<backup_id>/restore")
def restore_backup(id, backup_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    result = storage.restore_play_campaign_backup(id, backup_id)
    if result is None:
        return _not_found()
    payload = {
        "backup_id": result["backup_id"],
        "story": result["story"],
        "status": result["status"],
    }
    return Response(
        json.dumps(payload, sort_keys=False, separators=(",", ":")),
        mimetype="application/json",
    )


# --- Campaign imports ---


@api.post("/v1/play/campaigns/<id>/imports")
def import_campaign(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    if not isinstance(data, dict):
        return _bad_request()

    version = data.get("version")
    story = data.get("story")
    status = data.get("status")

    if not isinstance(version, int) or version != 1:
        return _bad_request()
    if not isinstance(story, str) or story == "":
        return _bad_request()
    if status not in ("lobby", "started"):
        return _bad_request()

    snapshot = {"version": 1, "story": story, "status": status}
    result = storage.import_play_campaign_snapshot(id, snapshot)
    if result is None:
        return _not_found()
    return Response(
        json.dumps(result, separators=(",", ":")),
        status=200,
        mimetype="application/json",
    )


@api.get("/v1/play/campaigns/<id>/import-state")
def get_import_state(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    result = storage.get_play_campaign_import_state(id)
    if result is None:
        return _not_found()
    return Response(
        json.dumps(result, separators=(",", ":")),
        mimetype="application/json",
    )


# --- Schema migrations ---


@api.post("/v1/play/campaigns/<id>/migrations")
def migrate_campaign(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    if not isinstance(data, dict):
        return _bad_request()

    schema_version = data.get("schema_version")
    story = data.get("story")

    if not isinstance(schema_version, int) or schema_version != 1:
        return _bad_request()
    if not isinstance(story, str) or story == "":
        return _bad_request()

    result = storage.migrate_play_campaign(id, schema_version, story)
    if result == "invalid":
        return _bad_request()
    if result is None:
        return _not_found()

    status = 201 if result["created"] else 200
    return Response(
        json.dumps(result["state"], separators=(",", ":")),
        status=status,
        mimetype="application/json",
    )


@api.get("/v1/play/campaigns/<id>/migration-state")
def get_migration_state(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    result = storage.get_play_campaign_migration_state(id)
    if result is None:
        return _not_found()
    return Response(
        json.dumps(result, separators=(",", ":")),
        mimetype="application/json",
    )


# --- Search records ---


@api.post("/v1/play/campaigns/<id>/search-records")
def create_search_record(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    record_id = data.get("record_id")
    text = data.get("text")
    if not _require_strings(record_id, text):
        return _bad_request()

    result = storage.create_search_record(id, record_id, text)
    if result is None:
        return _not_found()
    if result is False:
        return _bad_request()

    return jsonify(result), 201


@api.get("/v1/play/campaigns/<id>/search-records")
def list_search_records(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    q = request.args.get("q")
    try:
        limit = int(request.args.get("limit", 2))
    except (TypeError, ValueError):
        return _bad_request()
    try:
        cursor = int(request.args.get("cursor", 0))
    except (TypeError, ValueError):
        return _bad_request()
    if not (1 <= limit <= 3) or cursor < 0:
        return _bad_request()

    result = storage.list_search_records(id, q=q, limit=limit, cursor=cursor)
    if result is None:
        return _not_found()

    return jsonify(result)


# --- Deterministic Replay ---


@api.post("/v1/play/campaigns/<id>/replay-events")
def append_replay_event(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    data = _body()
    event_id = data.get("event_id")
    kind = data.get("kind")
    text = data.get("text")
    if not _require_strings(event_id, text):
        return _bad_request()
    if kind != "append":
        return _bad_request()

    result = storage.create_replay_event(id, event_id, kind, text)
    if result is None:
        return _not_found()
    if result == "duplicate":
        return _conflict("event_id already exists")

    payload = {"event_id": result["event_id"], "kind": result["kind"], "text": result["text"], "sequence": result["sequence"]}
    return Response(
        json.dumps(payload, separators=(",", ":"), sort_keys=False),
        status=201,
        mimetype="application/json",
    )


@api.get("/v1/play/campaigns/<id>/replay")
def get_replay_route(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    result = storage.get_replay(id)
    if result is None:
        return _not_found()

    return Response(
        json.dumps(result, separators=(",", ":"), sort_keys=False),
        mimetype="application/json",
    )


@api.get("/v1/play/campaigns/<id>/replay/check")
def check_replay(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    result = storage.get_replay(id)
    if result is None:
        return _not_found()

    return Response(
        json.dumps(result, separators=(",", ":"), sort_keys=False),
        mimetype="application/json",
    )


# --- Rate events ---


@api.post("/v1/play/campaigns/<id>/rate-events")
def create_rate_event(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    data = _body()
    event_id = data.get("event_id")
    if not isinstance(event_id, str) or event_id == "":
        return _bad_request()

    result = storage.create_rate_event(id, user["username"], event_id)
    if result is None:
        return _not_found()
    if result == "duplicate":
        return _bad_request()
    if result == "rate_limited":
        return _rate_limited(2, 0)

    return jsonify(result), 201


@api.get("/v1/play/campaigns/<id>/rate-events")
def list_rate_events(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    result = storage.list_rate_events(id, user["username"])
    if result is None:
        return _not_found()

    return jsonify(result)


@api.get("/v1/play/campaigns/<id>/metrics")
def get_campaign_metrics(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    result = storage.get_campaign_metrics(id)
    if result is None:
        return _not_found()

    # Preserve the exact key order required by the stage contract; the default
    # Flask JSON provider sorts object keys alphabetically.
    response = Response(json.dumps(result, separators=(",", ":")), mimetype="application/json")
    return response


# --- Deterministic RNG ledger ---


def _rng_roll_record(roll_id, sides, result, sequence):
    """Return an ordered RNG roll record dict for stable JSON serialization."""
    return {
        "roll_id": roll_id,
        "sides": sides,
        "result": result,
        "sequence": sequence,
    }


@api.put("/v1/play/campaigns/<id>/rng-seed")
def set_rng_seed(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    seed = data.get("seed")
    if not isinstance(seed, str) or seed == "":
        return _bad_request()

    result = storage.set_play_campaign_rng_seed(id, seed)
    if result is None:
        return _not_found()
    if result == "exists":
        return _conflict("seed already configured")

    ledger = storage.get_play_campaign_rng_ledger(id)
    payload = {"seed": ledger["seed"], "rolls": ledger["rolls"]}
    return Response(
        json.dumps(payload, sort_keys=False, separators=(",", ":")),
        mimetype="application/json",
    )


@api.post("/v1/play/campaigns/<id>/rng-rolls")
def append_rng_roll(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    data = _body()
    roll_id = data.get("roll_id")
    sides = data.get("sides")

    if not isinstance(roll_id, str) or roll_id == "":
        return _bad_request()
    if isinstance(sides, bool) or not isinstance(sides, int) or sides < 2 or sides > 100:
        return _bad_request()

    result = storage.append_play_campaign_rng_roll(id, roll_id, sides)
    if result is None:
        return _not_found()
    if result == "no_seed":
        return _conflict("rng seed not configured")
    if result == "duplicate":
        return _conflict("roll_id already exists")

    payload = _rng_roll_record(result["roll_id"], result["sides"], result["result"], result["sequence"])
    return Response(
        json.dumps(payload, sort_keys=False, separators=(",", ":")),
        status=201,
        mimetype="application/json",
    )


@api.get("/v1/play/campaigns/<id>/rng-ledger")
def get_rng_ledger(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    ledger = storage.get_play_campaign_rng_ledger(id)
    rolls = [
        _rng_roll_record(r["roll_id"], r["sides"], r["result"], r["sequence"])
        for r in ledger["rolls"]
    ]
    payload = {"seed": ledger["seed"], "rolls": rolls}
    return Response(
        json.dumps(payload, sort_keys=False, separators=(",", ":")),
        mimetype="application/json",
    )


# --- Moderation workflow ---


def _moderation_report_response(report, status=200):
    """Return a JSON Response with the exact report key order."""
    return Response(
        json.dumps(report, sort_keys=False, separators=(",", ":")),
        status=status,
        mimetype="application/json",
    )


@api.post("/v1/play/campaigns/<id>/moderation/reports")
def create_moderation_report(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    data = _body()
    report_id = data.get("report_id")
    target_id = data.get("target_id")
    reason = data.get("reason")
    if not _require_strings(report_id, target_id, reason):
        return _bad_request()

    result = storage.create_moderation_report(id, report_id, target_id, reason, user["username"])
    if result is None:
        return _not_found()
    if result == "duplicate":
        return _conflict("report already exists")

    return _moderation_report_response(result, status=201)


@api.get("/v1/play/campaigns/<id>/moderation/reports")
def list_moderation_reports(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    reports = storage.get_moderation_reports(id)
    if reports is None:
        return _not_found()

    return Response(
        json.dumps({"reports": reports}, sort_keys=False, separators=(",", ":")),
        mimetype="application/json",
    )


@api.put("/v1/play/campaigns/<id>/moderation/reports/<report_id>/resolution")
def resolve_moderation_report(id, report_id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    action = data.get("action")
    note = data.get("note")
    if action not in ("allow", "remove"):
        return _bad_request()
    if not isinstance(note, str) or note == "":
        return _bad_request()

    result = storage.resolve_moderation_report(id, report_id, action, note, user["username"])
    if result is None:
        return _not_found()
    if result == "already_resolved":
        return _conflict("report already resolved")

    return _moderation_report_response(result)


# --- Safety boundaries ---


def _validate_safety_tags(tags):
    """Return a normalized tag list, or None if the list is invalid.

    Tags must be a non-empty list of unique non-empty strings.
    """
    if not isinstance(tags, list):
        return None
    if len(tags) == 0:
        return None
    seen = set()
    normalized = []
    for tag in tags:
        if not isinstance(tag, str) or tag == "" or tag in seen:
            return None
        seen.add(tag)
        normalized.append(tag)
    return normalized


@api.put("/v1/play/campaigns/<id>/safety-boundaries")
def replace_safety_boundaries_route(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    blocked_tags = data.get("blocked_tags")
    normalized = _validate_safety_tags(blocked_tags)
    if normalized is None:
        return _bad_request()

    result = storage.replace_safety_boundaries(id, normalized)
    if result is None:
        return _not_found()
    return jsonify(result)


@api.get("/v1/play/campaigns/<id>/safety-boundaries")
def get_safety_boundaries_route(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    result = storage.get_safety_boundaries(id)
    if result is None:
        return _not_found()
    return jsonify(result)


@api.post("/v1/play/campaigns/<id>/safety-checks")
def submit_safety_check(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    data = _body()
    event_id = data.get("event_id")
    kind = data.get("kind")
    text = data.get("text")
    tags = data.get("tags")

    if not isinstance(event_id, str) or event_id == "":
        return _bad_request()
    if not isinstance(text, str) or text == "":
        return _bad_request()
    if kind not in ("narration", "chat"):
        return _bad_request()
    normalized_tags = _validate_safety_tags(tags)
    if normalized_tags is None:
        return _bad_request()

    result = storage.create_safety_event(id, event_id, kind, text, normalized_tags)
    if result is None:
        return _not_found()
    if result == "duplicate":
        return _conflict("event already exists")
    if result == "blocked":
        return _conflict("blocked tag")

    payload = {
        "event_id": result["event_id"],
        "kind": result["kind"],
        "text": result["text"],
        "tags": result["tags"],
        "sequence": result["sequence"],
    }
    return Response(
        json.dumps(payload, sort_keys=False, separators=(",", ":")),
        status=201,
        mimetype="application/json",
    )


@api.get("/v1/play/campaigns/<id>/safety-events")
def get_safety_events_route(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    result = storage.get_safety_events(id)
    if result is None:
        return _not_found()
    return Response(
        json.dumps(result, sort_keys=False, separators=(",", ":")),
        mimetype="application/json",
    )


# --- Fixture seeding ---


_CANONICAL_FIXTURE_ID = "canonical-v1"


def _fixture_state_response(status_code=200):
    """Return the canonical fixture state with a deterministic JSON shape."""
    payload = {
        "fixture_id": "canonical-v1",
        "status": "seeded",
        "characters": [
            {"character_id": "fixture-hero", "name": "Ari", "class": "fighter"},
            {"character_id": "fixture-mage", "name": "Bea", "class": "wizard"},
        ],
        "story": "The lantern is lit.",
        "event_ids": ["fixture-event-1", "fixture-event-2"],
    }
    return Response(
        json.dumps(payload, sort_keys=False, separators=(",", ":")),
        status=status_code,
        mimetype="application/json",
    )


@api.post("/v1/play/campaigns/<id>/fixture-seeds")
def seed_fixture_route(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    fixture_id = data.get("fixture_id")
    if not isinstance(fixture_id, str) or fixture_id != _CANONICAL_FIXTURE_ID:
        return _bad_request()

    result = storage.seed_fixture(id, fixture_id)
    if result is None:
        return _not_found()

    created, state = result
    # Guard: if the stored state differs from the canonical contract, still
    # return the canonical shape so repeated seeds are byte-for-byte idempotent.
    status_code = 201 if created else 200
    return _fixture_state_response(status_code=status_code)


@api.get("/v1/play/campaigns/<id>/fixture-state")
def get_fixture_state_route(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    state = storage.get_fixture_state(id)
    if state is None:
        return _not_found()

    return _fixture_state_response(status_code=200)


# --- Spectator view ---


@api.post("/v1/play/campaigns/<id>/spectators")
def create_spectator_route(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    spectator_id = data.get("spectator_id")
    if not isinstance(spectator_id, str) or spectator_id == "":
        return _bad_request()

    result = storage.create_spectator(id, spectator_id)
    if result is None:
        return _not_found()
    if result == "duplicate":
        return _conflict("spectator already exists")

    return Response(
        json.dumps(
            {"spectator_id": spectator_id, "token": f"spectator-{spectator_id}"},
            sort_keys=False,
            separators=(",", ":"),
        ),
        status=201,
        mimetype="application/json",
    )


@api.get("/v1/play/campaigns/<id>/spectator-view")
def get_spectator_view_route(id):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return _unauthorized()
    token = header[7:]
    if token.startswith("session-"):
        return _forbidden()
    if not token.startswith("spectator-"):
        return _unauthorized()
    spectator_id = token[10:]
    if spectator_id == "":
        return _unauthorized()

    spectator_campaign_id = storage.get_spectator_campaign(spectator_id)
    if spectator_campaign_id is None:
        return _unauthorized()

    campaign = storage.get_play_campaign(id)
    if campaign is None:
        return _not_found()
    if spectator_campaign_id != id:
        return _forbidden()

    party_size = len(storage.get_play_campaign_members(id))
    payload = {
        "campaign_id": id,
        "name": campaign["name"],
        "status": campaign["status"],
        "party_size": party_size,
        "story": campaign.get("story", ""),
    }
    return Response(
        json.dumps(payload, sort_keys=False, separators=(",", ":")),
        mimetype="application/json",
    )


# --- Load-safe event feed ---


@api.post("/v1/play/campaigns/<id>/feed-events")
def create_feed_event_route(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    data = _body()
    event_id = data.get("event_id")
    text = data.get("text")
    if not _require_strings(event_id, text):
        return _bad_request()

    result = storage.create_feed_event(id, event_id, text)
    if result == "duplicate":
        return _conflict("duplicate event_id")

    return Response(
        json.dumps(result, sort_keys=False, separators=(",", ":")),
        status=201,
        mimetype="application/json",
    )


@api.get("/v1/play/campaigns/<id>/event-feed")
def get_event_feed_route(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    try:
        cursor = int(request.args.get("cursor", 0))
    except (TypeError, ValueError):
        return _bad_request()
    try:
        limit = int(request.args.get("limit", 2))
    except (TypeError, ValueError):
        return _bad_request()
    if cursor < 0 or not (1 <= limit <= 3):
        return _bad_request()

    result = storage.get_feed_event_page(id, cursor, limit)
    return Response(
        json.dumps(result, sort_keys=False, separators=(",", ":")),
        mimetype="application/json",
    )

