"""Play-campaign surface and encounter routes.

Everything in this module requires an `Authorization: Bearer session-{username}`
header. It covers lobby creation, membership, turn queue, narration, scene and
location graph management, travel/rest turns, encounter building, and combat.
"""

from flask import jsonify

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
    _require_dm_campaign,
    _require_owner,
    _require_owner_or_member,
    _require_play_campaign_access,
    _require_role,
    _require_strings,
    _unauthorized,
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


@api.post("/v1/play/campaigns/<id>/narrations")
def add_narration(id):
    (campaign, user), err = _require_dm_campaign(id)
    if err:
        return err

    data = _body()
    text = data.get("text")
    if not isinstance(text, str) or text == "":
        return _bad_request()

    result = storage.create_narration(id, text)
    if result is None:
        return _not_found()
    return jsonify(result), 201


@api.get("/v1/play/campaigns/<id>/turn")
def get_play_campaign_turn(id):
    (campaign, user), err = _require_play_campaign_access(id)
    if err:
        return err

    current_actor = campaign["current_actor"]
    if current_actor == campaign["owner"]:
        phase = "dm"
    elif current_actor is None:
        phase = campaign["status"]
    else:
        phase = "player"

    queue = storage.get_play_campaign_queue(id)
    return jsonify(
        campaign_id=id,
        current_actor=current_actor,
        phase=phase,
        turn_number=campaign["turn_number"],
        queue=queue,
        overdue=False,
        logical_deadline=campaign["turn_number"] + 1,
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

