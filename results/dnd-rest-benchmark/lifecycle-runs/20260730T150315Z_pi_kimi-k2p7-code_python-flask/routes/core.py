"""Core, stateless, and compendium routes.

Includes health, storage administration, dice/checks/encounters, combat
sessions, character helpers, auth, compendium entries, and Player's
Handbook utilities.
"""

from flask import jsonify

import domain
import storage
from ._common import (
    SLUG_RE,
    USERNAME_RE,
    _bad_request,
    _body,
    _conflict,
    _not_found,
    _parse_initiative_combatants,
    _require_strings,
)
from . import api


# --- Health ---


@api.get("/health")
def health():
    return jsonify(ok=True)


# --- Storage ---


@api.get("/v1/storage/status")
def storage_status():
    return jsonify(
        driver="sqlite",
        schema_version=storage.SCHEMA_VERSION,
        initialized=storage.is_initialized(),
    )


@api.post("/v1/storage/reset")
def storage_reset():
    try:
        storage.reset_db()
    except Exception:
        return jsonify(error="reset failed"), 500
    return jsonify(ok=True, schema_version=storage.SCHEMA_VERSION)


# --- Core dice / checks / encounters ---


@api.post("/v1/dice/stats")
def dice_stats():
    stats = domain.compute_dice_stats(_body().get("expression", ""))
    if stats is None:
        return _bad_request()
    return jsonify(stats)


@api.post("/v1/checks/ability")
def ability_check():
    data = _body()
    try:
        roll = int(data["roll"])
        modifier = int(data["modifier"])
        dc = int(data["dc"])
    except (KeyError, TypeError, ValueError):
        return _bad_request()
    return jsonify(domain.compute_ability_check(roll, modifier, dc))


@api.post("/v1/encounters/adjusted-xp")
def adjusted_xp():
    data = _body()
    party = data.get("party", [])
    monsters = data.get("monsters", [])
    if not isinstance(party, list) or not isinstance(monsters, list):
        return _bad_request()

    # Preserve the specific error message used by the original contract:
    # only level-3 parties are supported; missing or malformed levels are a
    # generic invalid-input error.
    for member in party:
        try:
            if int(member["level"]) != 3:
                return jsonify(error="unsupported level"), 400
        except (KeyError, TypeError, ValueError):
            return _bad_request()

    result = domain.compute_adjusted_xp(party, monsters)
    if result is None:
        return _bad_request()
    return jsonify(result)


@api.post("/v1/initiative/order")
def initiative_order():
    data = _body()
    combatants, error = _parse_initiative_combatants(data.get("combatants", []))
    if error:
        return error
    order = domain.initiative_order(combatants)
    return jsonify(order=[{"name": c["name"], "score": c["score"]} for c in order])


# --- Combat sessions ---


@api.post("/v1/combat/sessions")
def create_combat_session():
    data = _body()
    session_id = data.get("id")
    if not isinstance(session_id, str) or session_id == "":
        return _bad_request()

    combatants, error = _parse_initiative_combatants(
        data.get("combatants", []), require_unique_names=True
    )
    if error:
        return error
    if len(combatants) == 0:
        return _bad_request()

    order = domain.initiative_order(combatants)
    result = storage.create_combat_session(session_id, order)
    if result is None:
        return _conflict("session already exists")

    return jsonify(
        id=result["id"],
        round=result["round"],
        turn_index=result["turn_index"],
        active=result["active"],
        order=result["order"],
    )


@api.post("/v1/combat/sessions/<id>/conditions")
def add_condition(id):
    session = storage.get_combat_session(id)
    if session is None:
        return _not_found()

    data = _body()
    target = data.get("target")
    condition_text = data.get("condition")
    duration = data.get("duration_rounds")

    combatant_names = {c["name"] for c in session["order"]}
    if not isinstance(target, str) or target not in combatant_names:
        return _bad_request()
    if not isinstance(condition_text, str):
        return _bad_request()
    try:
        duration = int(duration)
    except (TypeError, ValueError):
        return _bad_request()
    if duration <= 0:
        return _bad_request()

    result = storage.add_condition(id, target, condition_text, duration)
    if result is None:
        return _not_found()
    if result is False:
        return _bad_request()
    return jsonify(target=target, conditions=result)


@api.post("/v1/combat/sessions/<id>/advance")
def advance_turn(id):
    session = storage.get_combat_session(id)
    if session is None:
        return _not_found()
    if len(session["order"]) == 0:
        return jsonify(error="invalid state"), 400

    result = storage.advance_turn(id)
    if result is None:
        return _not_found()
    if result is False:
        return jsonify(error="invalid state"), 400
    return jsonify(result)


# --- Characters ---


@api.post("/v1/characters/ability-modifier")
def character_ability_modifier():
    data = _body()
    try:
        score = int(data["score"])
    except (KeyError, TypeError, ValueError):
        return _bad_request()
    if score < 1 or score > 30:
        return _bad_request()
    return jsonify(score=score, modifier=domain.ability_modifier(score))


@api.post("/v1/characters/proficiency")
def character_proficiency():
    data = _body()
    try:
        level = int(data["level"])
    except (KeyError, TypeError, ValueError):
        return _bad_request()
    if level < 1 or level > 20:
        return _bad_request()
    return jsonify(level=level, proficiency_bonus=domain.proficiency_bonus(level))


@api.post("/v1/characters/derived-stats")
def character_derived_stats():
    data = _body()
    try:
        level = int(data["level"])
        abilities = data["abilities"]
        armor = data["armor"]
    except (KeyError, TypeError, ValueError):
        return _bad_request()

    result = domain.compute_derived_stats(level, abilities, armor)
    if result is None:
        return _bad_request()
    return jsonify(result)


# --- Auth ---


@api.post("/v1/auth/register")
def register_user():
    data = _body()
    username = data.get("username")
    password = data.get("password")
    role = data.get("role")

    if not isinstance(username, str) or not isinstance(password, str) or role not in ("dm", "player"):
        return _bad_request()
    if not USERNAME_RE.fullmatch(username):
        return _bad_request()
    if len(password) < 8:
        return _bad_request()

    if storage.create_user(username, password, role) is None:
        return _conflict("username already exists")

    return jsonify(username=username, role=role), 201


@api.post("/v1/auth/login")
def login_user():
    data = _body()
    username = data.get("username")
    password = data.get("password")

    if not isinstance(username, str) or not isinstance(password, str):
        return _bad_request()

    user = storage.get_user(username)
    if user is None or not storage.verify_password(password, user["salt"], user["password_hash"]):
        return jsonify(error="invalid credentials"), 401

    return jsonify(username=username, token=f"session-{username}")


# --- Compendium ---


@api.post("/v1/compendium/monsters")
def create_monster():
    data = _body()
    slug = data.get("slug")
    name = data.get("name")
    cr = data.get("cr")
    armor_class = data.get("armor_class")
    hit_points = data.get("hit_points")
    tags = data.get("tags", [])

    if not isinstance(slug, str) or not isinstance(name, str) or not isinstance(cr, str):
        return _bad_request()
    if not SLUG_RE.fullmatch(slug):
        return _bad_request()
    try:
        armor_class = int(armor_class)
        hit_points = int(hit_points)
    except (TypeError, ValueError):
        return _bad_request()
    if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
        return _bad_request()

    result = storage.create_monster(slug, name, cr, armor_class, hit_points, tags)
    if result is None:
        return _conflict("slug already exists")
    return jsonify(result), 201


@api.get("/v1/compendium/monsters/<slug>")
def get_monster(slug):
    result = storage.get_monster(slug)
    if result is None:
        return _not_found()
    return jsonify(result)


@api.post("/v1/compendium/items")
def create_item():
    data = _body()
    slug = data.get("slug")
    name = data.get("name")
    item_type = data.get("type")
    rarity = data.get("rarity")
    cost_gp = data.get("cost_gp")

    if not isinstance(slug, str) or not isinstance(name, str) or not isinstance(item_type, str) or not isinstance(rarity, str):
        return _bad_request()
    if not SLUG_RE.fullmatch(slug):
        return _bad_request()
    try:
        cost_gp = int(cost_gp)
    except (TypeError, ValueError):
        return _bad_request()

    result = storage.create_item(slug, name, item_type, rarity, cost_gp)
    if result is None:
        return _conflict("slug already exists")
    return jsonify(result), 201


@api.get("/v1/compendium/items/<slug>")
def get_item(slug):
    result = storage.get_item(slug)
    if result is None:
        return _not_found()
    return jsonify(result)


# --- PHB ---


@api.post("/v1/phb/spell-slots")
def phb_spell_slots():
    data = _body()
    class_name = data.get("class")
    level = data.get("level")
    result = domain.compute_spell_slots(class_name, level)
    if result is None:
        return _bad_request()
    return jsonify(result)


@api.post("/v1/phb/rests/long")
def phb_long_rest():
    data = _body()
    try:
        level = int(data["level"])
        hp_current = int(data["hp_current"])
        hp_max = int(data["hp_max"])
        hit_dice_spent = int(data["hit_dice_spent"])
        exhaustion_level = int(data["exhaustion_level"])
    except (KeyError, TypeError, ValueError):
        return _bad_request()

    result = domain.compute_long_rest(level, hp_current, hp_max, hit_dice_spent, exhaustion_level)
    if result is None:
        return _bad_request()
    return jsonify(result)


@api.post("/v1/phb/equipment-load")
def phb_equipment_load():
    data = _body()
    try:
        strength = int(data["strength"])
        weight = int(data["weight"])
    except (KeyError, TypeError, ValueError):
        return _bad_request()

    result = domain.compute_equipment_load(strength, weight)
    if result is None:
        return _bad_request()
    return jsonify(result)
