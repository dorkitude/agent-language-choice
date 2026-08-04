"""Character ability-score and derived-stat calculations."""

from flask import Blueprint, jsonify, request

from ..rules import ability_modifier, proficiency_bonus
from ..validation import valid_int_in_range

bp = Blueprint("characters", __name__)


@bp.post("/v1/characters/ability-modifier")
def ability_modifier_route():
    data = request.get_json(silent=True) or {}
    score = data.get("score")
    if not valid_int_in_range(score, 1, 30):
        return jsonify(error="invalid score"), 400

    return jsonify(score=score, modifier=ability_modifier(score))


@bp.post("/v1/characters/proficiency")
def proficiency_route():
    data = request.get_json(silent=True) or {}
    level = data.get("level")
    if not valid_int_in_range(level, 1, 20):
        return jsonify(error="invalid level"), 400

    return jsonify(level=level, proficiency_bonus=proficiency_bonus(level))


@bp.post("/v1/characters/derived-stats")
def derived_stats():
    data = request.get_json(silent=True) or {}
    level = data.get("level")
    abilities = data.get("abilities")
    armor = data.get("armor")

    if not valid_int_in_range(level, 1, 20):
        return jsonify(error="invalid level"), 400
    if not isinstance(abilities, dict):
        return jsonify(error="invalid abilities"), 400
    if not isinstance(armor, dict):
        return jsonify(error="invalid armor"), 400

    ability_names = ("str", "dex", "con", "int", "wis", "cha")
    scores = {}
    for name in ability_names:
        value = abilities.get(name)
        if not valid_int_in_range(value, 1, 30):
            return jsonify(error="invalid abilities"), 400
        scores[name] = value

    base = armor.get("base")
    shield = armor.get("shield")
    dex_cap = armor.get("dex_cap")

    if not isinstance(base, int) or isinstance(base, bool):
        return jsonify(error="invalid armor"), 400
    if not isinstance(shield, bool):
        return jsonify(error="invalid armor"), 400
    if not isinstance(dex_cap, int) or isinstance(dex_cap, bool):
        return jsonify(error="invalid armor"), 400

    modifiers = {name: ability_modifier(scores[name]) for name in ability_names}
    prof = proficiency_bonus(level)
    hp_max = level * (6 + modifiers["con"])
    shield_bonus = 2 if shield else 0
    armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus

    return jsonify(
        level=level,
        proficiency_bonus=prof,
        hp_max=hp_max,
        armor_class=armor_class,
        modifiers=modifiers,
    )
