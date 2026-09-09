"""Django views for the D&D REST API.

Each view is a thin layer over the ``domain`` and ``db`` modules. Common
request parsing and response helpers live in ``dndsite.http``. Validation
failures return 400, missing resources 404, and conflicts 409. Error message
strings are preserved from the original implementation to maintain exact
response bodies.
"""

import json
import sqlite3

from django.contrib.auth.hashers import check_password, make_password
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import (
    require_actor,
    require_play_campaign_member_or_owner,
)

from ..http import bad_request, conflict, forbidden, not_found, parse_json, require_method, unauthorized

from ..constants import (
    DICE_RE,
    HIT_DICE,
    SCHEMA_VERSION,
    SKILL_ABILITIES,
    USERNAME_RE,
    VALID_BACKGROUNDS,
    VALID_CLASSES,
    VALID_RACES,
    WIZARD_SPELLS,
)
from ..db import (
    _add_inventory_item,
    _assign_equipment,
    _get_inventory_summary,
    db_conn,
    is_initialized,
    reset_storage,
)
from ..domain import (
    ability_modifier as compute_ability_modifier,
    avg_hit_die,
    build_initiative_order,
    compute_encounter_xp,
    encounter_recommendation,
    max_spell_slots,
    parse_combatant,
    proficiency_bonus,
    skill_check_modifier,
)

# ---------------------------------------------------------------------------
# Character death saves
# ---------------------------------------------------------------------------


@csrf_exempt
def character_damage(request, id, char_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request, "dm")
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        amount = body["amount"]
        if not isinstance(amount, int) or amount <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if actor["username"] != campaign["owner"]:
            return forbidden()

        member = conn.execute(
            "SELECT username, hp_current, hp_max FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, char_id),
        ).fetchone()
        if member is None:
            return not_found("character not found")

        hp_before = member["hp_current"]
        hp_after = max(0, hp_before - amount)
        actual_damage = hp_before - hp_after
        new_status = "conscious" if hp_after > 0 else "unconscious"
        conn.execute(
            "UPDATE play_campaign_members SET hp_current = ?, status = ?, death_save_successes = 0, death_save_failures = 0 WHERE campaign_id = ? AND character_id = ?",
            (hp_after, new_status, id, char_id),
        )

    return JsonResponse(
        {
            "target": char_id,
            "hp_before": hp_before,
            "hp_after": hp_after,
            "damage": actual_damage,
        }
    )


@csrf_exempt
def death_saves(request, id, char_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        outcome = body["outcome"]
        if outcome not in ("success", "failure"):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        member = conn.execute(
            "SELECT username, hp_current, status, death_save_successes, death_save_failures "
            "FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
            (id, char_id),
        ).fetchone()
        if member is None:
            return not_found("character not found")

        if actor["username"] != member["username"]:
            return forbidden()

        if member["hp_current"] > 0 or member["status"] != "unconscious":
            return conflict("character is conscious")

        if outcome == "success":
            successes = member["death_save_successes"] + 1
            failures = member["death_save_failures"]
        else:
            successes = member["death_save_successes"]
            failures = member["death_save_failures"] + 1

        if successes >= 3:
            status = "stable"
        elif failures >= 3:
            status = "dead"
        else:
            status = "unconscious"

        conn.execute(
            "UPDATE play_campaign_members SET status = ?, death_save_successes = ?, death_save_failures = ? WHERE campaign_id = ? AND character_id = ?",
            (status, successes, failures, id, char_id),
        )

    return JsonResponse(
        {
            "character_id": char_id,
            "successes": successes,
            "failures": failures,
            "status": status,
        },
        status=201,
    )


@csrf_exempt
def character_status(request, id, char_id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        member = conn.execute(
            "SELECT character_id, hp_current, hp_max, status FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, char_id),
        ).fetchone()
        if member is None:
            return not_found("character not found")

    return JsonResponse(
        {
            "character_id": member["character_id"],
            "hp_current": member["hp_current"],
            "hp_max": member["hp_max"],
            "status": member["status"],
        }
    )



# ---------------------------------------------------------------------------
# Character ownership
# ---------------------------------------------------------------------------


@csrf_exempt
def get_character_owner(request, id, char_id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        member = conn.execute(
            "SELECT character_id, owner FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, char_id),
        ).fetchone()
        if member is None:
            return not_found("character not found")

    return JsonResponse(
        {"character_id": member["character_id"], "owner": member["owner"]}
    )


@csrf_exempt
def claim_character(request, id, char_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request, "player", "only players may claim")
    if err is not None:
        return err

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        is_member = (
            conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (id, actor["username"]),
            ).fetchone()
            is not None
        )
        if not is_member:
            return forbidden()

        member = conn.execute(
            "SELECT character_id, owner FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, char_id),
        ).fetchone()
        if member is None:
            return not_found("character not found")

        current_owner = member["owner"]
        if current_owner is not None and current_owner != actor["username"]:
            return conflict("character already owned")

        if current_owner is None:
            conn.execute(
                "UPDATE play_campaign_members SET owner = ? WHERE campaign_id = ? AND character_id = ?",
                (actor["username"], id, char_id),
            )

    return JsonResponse(
        {"character_id": char_id, "owner": actor["username"]}, status=201
    )


@csrf_exempt
def transfer_character(request, id, char_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        new_owner = body["new_owner"]
        if not isinstance(new_owner, str):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        member = conn.execute(
            "SELECT character_id, owner FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, char_id),
        ).fetchone()
        if member is None:
            return not_found("character not found")

        if member["owner"] != actor["username"]:
            return forbidden()

        new_owner_member = conn.execute(
            "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
            (id, new_owner),
        ).fetchone()
        if new_owner_member is None:
            return bad_request("invalid request")

        conn.execute(
            "UPDATE play_campaign_members SET owner = ? WHERE campaign_id = ? AND character_id = ?",
            (new_owner, id, char_id),
        )

    return JsonResponse({"character_id": char_id, "owner": new_owner})



# ---------------------------------------------------------------------------
# Character creation choices
# ---------------------------------------------------------------------------


@csrf_exempt
def build_character(request, id, char_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        race = body["race"]
        character_class = body["class"]
        background = body["background"]
        abilities = body["abilities"]
        if not all(isinstance(v, str) for v in (race, character_class, background)):
            raise ValueError
        if not isinstance(abilities, dict):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    if race not in VALID_RACES:
        return bad_request("invalid request")
    if character_class not in VALID_CLASSES:
        return bad_request("invalid request")
    if background not in VALID_BACKGROUNDS:
        return bad_request("invalid request")

    ability_names = ["str", "dex", "con", "int", "wis", "cha"]
    modifiers = {}
    for name in ability_names:
        score = abilities.get(name)
        if not isinstance(score, int) or isinstance(score, bool) or score < 1 or score > 30:
            return bad_request("invalid request")
        modifiers[name] = compute_ability_modifier(score)

    level = 1
    hp_max = HIT_DICE[character_class] + modifiers["con"]
    proficiency = proficiency_bonus(level)

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        member = conn.execute(
            "SELECT owner FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, char_id),
        ).fetchone()
        if member is None:
            return not_found("character not found")

        if actor["username"] != member["owner"]:
            return forbidden()

        conn.execute(
            "UPDATE play_campaign_members SET class_name = ?, hp_max = ?, hp_current = ?, level = ?, abilities_json = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (character_class, hp_max, hp_max, level, json.dumps(abilities), id, char_id),
        )

    return JsonResponse(
        {
            "character_id": char_id,
            "race": race,
            "class": character_class,
            "background": background,
            "level": level,
            "hp_max": hp_max,
            "proficiency_bonus": proficiency,
        }
    )



# ---------------------------------------------------------------------------
# Level progression
# ---------------------------------------------------------------------------


@csrf_exempt
def level_up(request, id, char_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        target_level = body["level"]
        if not isinstance(target_level, int) or isinstance(target_level, bool):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        member = conn.execute(
            "SELECT owner, class_name, level, hp_max, abilities_json FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, char_id),
        ).fetchone()
        if member is None:
            return not_found("character not found")

        if actor["username"] != member["owner"]:
            return forbidden()

        current_level = member["level"]
        if target_level != current_level + 1:
            return bad_request("invalid request")
        if target_level < 1 or target_level > 20:
            return bad_request("invalid request")

        try:
            abilities = json.loads(member["abilities_json"])
            con_modifier = compute_ability_modifier(abilities["con"])
        except (KeyError, TypeError, ValueError):
            return bad_request("invalid request")

        hp_gain = avg_hit_die(member["class_name"]) + con_modifier
        hp_gain = max(1, hp_gain)
        new_hp_max = member["hp_max"] + hp_gain

        conn.execute(
            "UPDATE play_campaign_members SET level = ?, hp_max = ? WHERE campaign_id = ? AND character_id = ?",
            (target_level, new_hp_max, id, char_id),
        )

    return JsonResponse(
        {
            "character_id": char_id,
            "level": target_level,
            "hp_max": new_hp_max,
            "hit_dice": f"1d{HIT_DICE[member['class_name']]}",
            "proficiency_bonus": proficiency_bonus(target_level),
        }
    )



# ---------------------------------------------------------------------------
# Skills and proficiencies
# ---------------------------------------------------------------------------


@csrf_exempt
def skill_check(request, id, char_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        skill = body["skill"]
        ability = body["ability"]
        proficient = body["proficient"]
        roll = body["roll"]
        if not isinstance(skill, str) or not isinstance(ability, str):
            raise ValueError
        if not isinstance(proficient, bool):
            raise ValueError
        if not isinstance(roll, int) or isinstance(roll, bool):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    if skill not in SKILL_ABILITIES or SKILL_ABILITIES[skill] != ability:
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        member = conn.execute(
            "SELECT owner, level, abilities_json FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, char_id),
        ).fetchone()
        if member is None:
            return not_found("character not found")

        if actor["username"] != member["owner"]:
            return forbidden()

        try:
            abilities = json.loads(member["abilities_json"])
            score = abilities[ability]
            if not isinstance(score, int) or isinstance(score, bool) or score < 1 or score > 30:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            return bad_request("invalid request")

        modifier = skill_check_modifier(score, member["level"], proficient)
        total = roll + modifier

    return JsonResponse(
        {
            "character_id": char_id,
            "skill": skill,
            "ability": ability,
            "modifier": modifier,
            "total": total,
        }
    )


# ---------------------------------------------------------------------------
# Spellbook
# ---------------------------------------------------------------------------


def _add_spell(request, id, char_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        spell_id = body["spell_id"]
        name = body["name"]
        level = body["level"]
        if not isinstance(spell_id, str) or not isinstance(name, str):
            raise ValueError
        if not isinstance(level, int) or isinstance(level, bool) or level < 0 or level > 9:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        member = conn.execute(
            "SELECT owner, class_name FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, char_id),
        ).fetchone()
        if member is None:
            return not_found("character not found")

        if actor["username"] != member["owner"]:
            return forbidden()

        if member["class_name"] != "wizard":
            return bad_request("invalid request")

        spell_info = WIZARD_SPELLS.get(spell_id)
        if spell_info is None or spell_info["name"] != name or spell_info["level"] != level:
            return bad_request("invalid request")

        existing = conn.execute(
            "SELECT 1 FROM spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
            (id, char_id, spell_id),
        ).fetchone()
        if existing is not None:
            return conflict("spell already known")

        conn.execute(
            "INSERT INTO spells (campaign_id, character_id, spell_id, name, level) "
            "VALUES (?, ?, ?, ?, ?)",
            (id, char_id, spell_id, name, level),
        )

    return JsonResponse(
        {"spell_id": spell_id, "name": name, "level": level},
        status=201,
    )


def _get_spells(request, id, char_id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        member = conn.execute(
            "SELECT 1 FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, char_id),
        ).fetchone()
        if member is None:
            return not_found("character not found")

        rows = conn.execute(
            "SELECT spell_id, name, level FROM spells "
            "WHERE campaign_id = ? AND character_id = ? "
            "ORDER BY level, spell_id",
            (id, char_id),
        ).fetchall()

    spells = [
        {"spell_id": row["spell_id"], "name": row["name"], "level": row["level"]}
        for row in rows
    ]
    return JsonResponse({"spells": spells})


@csrf_exempt
def character_spells(request, id, char_id):
    if request.method == "POST":
        return _add_spell(request, id, char_id)
    if request.method == "GET":
        return _get_spells(request, id, char_id)
    return require_method(request, "GET", "POST")


# ---------------------------------------------------------------------------
# Spell preparation
# ---------------------------------------------------------------------------

PREPARED_SPELLCASTERS = {"wizard"}


def _max_prepared_spells(class_name, level):
    """Return the maximum number of prepared spells for a character.

    Only wizards are supported by the existing spellbook. A wizard may
    prepare a number of spells equal to their class level (minimum 1).
    """
    if class_name not in PREPARED_SPELLCASTERS:
        return 0
    return max(1, level)


def _fetch_prepared_spells(conn, campaign_id, character_id):
    """Return the character's prepared spell IDs in order."""
    rows = conn.execute(
        "SELECT spell_id FROM prepared_spells "
        "WHERE campaign_id = ? AND character_id = ? "
        "ORDER BY sequence",
        (campaign_id, character_id),
    ).fetchall()
    return [row["spell_id"] for row in rows]


def _prepared_spells_payload(character_id, prepared_spells, class_name, level):
    """Build the standardized prepared-spells response body."""
    return {
        "character_id": character_id,
        "prepared_spells": prepared_spells,
        "max_prepared": _max_prepared_spells(class_name, level),
    }


@csrf_exempt
def character_prepared_spells(request, id, character_id):
    if request.method == "GET":
        return _get_prepared_spells(request, id, character_id)
    if request.method == "PUT":
        return _set_prepared_spells(request, id, character_id)
    return require_method(request, "GET", "PUT")


def _get_prepared_spells(request, id, character_id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        member = conn.execute(
            "SELECT character_id, class_name, level FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, character_id),
        ).fetchone()
        if member is None:
            return not_found("character not found")

        prepared_spells = _fetch_prepared_spells(conn, id, character_id)

    return JsonResponse(
        _prepared_spells_payload(
            member["character_id"], prepared_spells, member["class_name"], member["level"]
        )
    )


def _set_prepared_spells(request, id, character_id):
    bad = require_method(request, "PUT")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        spell_ids = body["spell_ids"]
        if not isinstance(spell_ids, list):
            raise ValueError
        if not all(isinstance(spell_id, str) for spell_id in spell_ids):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        member = conn.execute(
            "SELECT character_id, owner, class_name, level FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, character_id),
        ).fetchone()
        if member is None:
            return not_found("character not found")

        if actor["username"] != member["owner"]:
            return forbidden()

        max_prepared = _max_prepared_spells(member["class_name"], member["level"])
        if max_prepared == 0:
            return bad_request("invalid request")

        # Deduplicate while preserving the order the player submitted.
        seen = set()
        unique_spell_ids = []
        for spell_id in spell_ids:
            if spell_id not in seen:
                seen.add(spell_id)
                unique_spell_ids.append(spell_id)

        if len(unique_spell_ids) > max_prepared:
            return bad_request("invalid request")

        known_spells = {
            row["spell_id"]
            for row in conn.execute(
                "SELECT spell_id FROM spells WHERE campaign_id = ? AND character_id = ?",
                (id, character_id),
            )
        }
        if any(spell_id not in known_spells for spell_id in unique_spell_ids):
            return bad_request("invalid request")

        conn.execute(
            "DELETE FROM prepared_spells WHERE campaign_id = ? AND character_id = ?",
            (id, character_id),
        )
        for sequence, spell_id in enumerate(unique_spell_ids):
            conn.execute(
                "INSERT INTO prepared_spells (campaign_id, character_id, spell_id, sequence) "
                "VALUES (?, ?, ?, ?)",
                (id, character_id, spell_id, sequence),
            )

    return JsonResponse(
        _prepared_spells_payload(
            character_id, unique_spell_ids, member["class_name"], member["level"]
        )
    )


# ---------------------------------------------------------------------------
# Spell casting
# ---------------------------------------------------------------------------

SPELLCASTING_CLASSES = {
    "bard",
    "cleric",
    "druid",
    "paladin",
    "ranger",
    "sorcerer",
    "warlock",
    "wizard",
}


def _count_casts_at_level(conn, campaign_id, character_id, slot_level):
    """Return the number of recorded spell casts at the given slot level."""
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM spell_casts "
        "WHERE campaign_id = ? AND character_id = ? AND slot_level = ?",
        (campaign_id, character_id, slot_level),
    ).fetchone()
    return row["count"]


@csrf_exempt
def character_casts(request, id, char_id):
    if request.method == "POST":
        return _cast_spell(request, id, char_id)
    if request.method == "GET":
        return _get_casts(request, id, char_id)
    return require_method(request, "GET", "POST")


def _cast_spell(request, id, char_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        spell_id = body["spell_id"]
        target = body["target"]
        if not isinstance(spell_id, str) or not isinstance(target, str):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        member = conn.execute(
            "SELECT character_id, owner, class_name, level FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, char_id),
        ).fetchone()
        if member is None:
            return not_found("character not found")

        if actor["username"] != member["owner"]:
            return forbidden()

        if member["class_name"] not in SPELLCASTING_CLASSES:
            return bad_request("invalid request")

        spell_row = conn.execute(
            "SELECT spell_id, level FROM spells "
            "WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
            (id, char_id, spell_id),
        ).fetchone()
        if spell_row is None:
            return bad_request("invalid request")

        prepared_row = conn.execute(
            "SELECT 1 FROM prepared_spells "
            "WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
            (id, char_id, spell_id),
        ).fetchone()
        if prepared_row is None:
            return bad_request("invalid request")

        slot_level = spell_row["level"]
        max_slots = max_spell_slots(member["level"], slot_level)
        if max_slots <= 0:
            return conflict("no remaining spell slots")

        casts_at_level = _count_casts_at_level(conn, id, char_id, slot_level)
        slots_remaining = max_slots - casts_at_level - 1
        if slots_remaining < 0:
            return conflict("no remaining spell slots")

        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM spell_casts "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, char_id),
        ).fetchone()["next_sequence"]

        conn.execute(
            "INSERT INTO spell_casts (campaign_id, character_id, sequence, spell_id, target, slot_level, slots_remaining) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (id, char_id, next_sequence, spell_id, target, slot_level, slots_remaining),
        )

    return JsonResponse(
        {
            "character_id": char_id,
            "spell_id": spell_id,
            "target": target,
            "slot_level": slot_level,
            "slots_remaining": slots_remaining,
            "sequence": next_sequence,
        },
        status=201,
    )


def _get_casts(request, id, char_id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        member = conn.execute(
            "SELECT 1 FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, char_id),
        ).fetchone()
        if member is None:
            return not_found("character not found")

        rows = conn.execute(
            "SELECT sequence, spell_id, target, slot_level, slots_remaining FROM spell_casts "
            "WHERE campaign_id = ? AND character_id = ? "
            "ORDER BY sequence",
            (id, char_id),
        ).fetchall()

    casts = [
        {
            "character_id": char_id,
            "spell_id": row["spell_id"],
            "target": row["target"],
            "slot_level": row["slot_level"],
            "slots_remaining": row["slots_remaining"],
            "sequence": row["sequence"],
        }
        for row in rows
    ]
    return JsonResponse({"casts": casts})


# ---------------------------------------------------------------------------
# Concentration
# ---------------------------------------------------------------------------


def _fetch_member_for_concentration(conn, campaign_id, character_id):
    """Return member row including the stored concentration JSON, if any."""
    return conn.execute(
        "SELECT character_id, owner, class_name, concentration_json "
        "FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?",
        (campaign_id, character_id),
    ).fetchone()


def _concentration_response(character_id, concentration):
    """Build the standard concentration response body."""
    return {"character_id": character_id, "concentration": concentration}


def _active_concentration(member):
    """Parse the member's concentration JSON into a dict or ``None``."""
    raw = member["concentration_json"]
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


@csrf_exempt
def character_concentration(request, id, char_id):
    if request.method == "PUT":
        return _set_concentration(request, id, char_id)
    if request.method == "GET":
        return _get_concentration(request, id, char_id)
    if request.method == "DELETE":
        return _clear_concentration(request, id, char_id)
    return require_method(request, "GET", "PUT", "DELETE")


@csrf_exempt
def character_concentration_advance_turn(request, id, char_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        member = _fetch_member_for_concentration(conn, id, char_id)
        if member is None:
            return not_found("character not found")

        concentration = _active_concentration(member)
        if concentration is not None:
            remaining = concentration["remaining_turns"] - 1
            if remaining > 0:
                concentration["remaining_turns"] = remaining
                conn.execute(
                    "UPDATE play_campaign_members SET concentration_json = ? "
                    "WHERE campaign_id = ? AND character_id = ?",
                    (json.dumps(concentration), id, char_id),
                )
            else:
                concentration = None
                conn.execute(
                    "UPDATE play_campaign_members SET concentration_json = NULL "
                    "WHERE campaign_id = ? AND character_id = ?",
                    (id, char_id),
                )

    return JsonResponse(_concentration_response(char_id, concentration))


def _set_concentration(request, id, char_id):
    bad = require_method(request, "PUT")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        spell_id = body["spell_id"]
        target = body["target"]
        duration_turns = body["duration_turns"]
        if not isinstance(spell_id, str) or not isinstance(target, str):
            raise ValueError
        if not isinstance(duration_turns, int) or isinstance(duration_turns, bool) or duration_turns < 1:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        member = _fetch_member_for_concentration(conn, id, char_id)
        if member is None:
            return not_found("character not found")

        if actor["username"] != member["owner"]:
            return forbidden()

        if member["class_name"] not in SPELLCASTING_CLASSES:
            return bad_request("invalid request")

        known = conn.execute(
            "SELECT 1 FROM spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
            (id, char_id, spell_id),
        ).fetchone()
        if known is None:
            return bad_request("invalid request")

        prepared = conn.execute(
            "SELECT 1 FROM prepared_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
            (id, char_id, spell_id),
        ).fetchone()
        if prepared is None:
            return bad_request("invalid request")

        concentration = {
            "spell_id": spell_id,
            "target": target,
            "remaining_turns": duration_turns,
        }
        conn.execute(
            "UPDATE play_campaign_members SET concentration_json = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (json.dumps(concentration), id, char_id),
        )

    return JsonResponse(_concentration_response(char_id, concentration))


def _get_concentration(request, id, char_id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        member = _fetch_member_for_concentration(conn, id, char_id)
        if member is None:
            return not_found("character not found")

        concentration = _active_concentration(member)

    return JsonResponse(_concentration_response(char_id, concentration))


def _clear_concentration(request, id, char_id):
    bad = require_method(request, "DELETE")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    body = parse_json(request)
    if request.body and body is None:
        return bad_request("invalid request")

    validate_body = body is not None
    if validate_body:
        try:
            spell_id = body["spell_id"]
            target = body["target"]
            duration_turns = body["duration_turns"]
            if not isinstance(spell_id, str) or not isinstance(target, str):
                raise ValueError
            if (
                not isinstance(duration_turns, int)
                or isinstance(duration_turns, bool)
                or duration_turns < 1
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        member = _fetch_member_for_concentration(conn, id, char_id)
        if member is None:
            return not_found("character not found")

        if actor["username"] != member["owner"]:
            return forbidden()

        if validate_body:
            if member["class_name"] not in SPELLCASTING_CLASSES:
                return bad_request("invalid request")

            known = conn.execute(
                "SELECT 1 FROM spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
                (id, char_id, spell_id),
            ).fetchone()
            if known is None:
                return bad_request("invalid request")

            prepared = conn.execute(
                "SELECT 1 FROM prepared_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
                (id, char_id, spell_id),
            ).fetchone()
            if prepared is None:
                return bad_request("invalid request")

        conn.execute(
            "UPDATE play_campaign_members SET concentration_json = NULL "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, char_id),
        )

    return JsonResponse(_concentration_response(char_id, None))

