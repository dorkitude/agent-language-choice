"""Player's Handbook mechanics: spell slots, long rest recovery, encumbrance."""

from flask import Blueprint, jsonify, request

from ..rules import WIZARD_SPELL_SLOTS
from ..validation import valid_int, valid_int_in_range

bp = Blueprint("phb", __name__)


@bp.post("/v1/phb/spell-slots")
def phb_spell_slots():
    data = request.get_json(silent=True) or {}
    char_class = data.get("class")
    level = data.get("level")

    if char_class != "wizard":
        return jsonify(error="unsupported class"), 400
    if not valid_int(level) or level not in WIZARD_SPELL_SLOTS:
        return jsonify(error="unsupported level"), 400

    return jsonify(**{"class": char_class}, level=level, slots=WIZARD_SPELL_SLOTS[level])


@bp.post("/v1/phb/rests/long")
def phb_long_rest():
    data = request.get_json(silent=True) or {}
    level = data.get("level")
    hp_current = data.get("hp_current")
    hp_max = data.get("hp_max")
    hit_dice_spent = data.get("hit_dice_spent")
    exhaustion_level = data.get("exhaustion_level")

    if not valid_int_in_range(level, 1, 20):
        return jsonify(error="invalid level"), 400
    if not valid_int(hp_current) or hp_current < 0:
        return jsonify(error="invalid hp_current"), 400
    if not valid_int(hp_max) or hp_max <= 0:
        return jsonify(error="invalid hp_max"), 400
    if not valid_int(hit_dice_spent) or hit_dice_spent < 0:
        return jsonify(error="invalid hit_dice_spent"), 400
    if not valid_int(exhaustion_level) or exhaustion_level < 0:
        return jsonify(error="invalid exhaustion_level"), 400

    recoverable = max(1, level // 2)
    new_hit_dice_spent = max(0, hit_dice_spent - recoverable)
    new_exhaustion = max(0, exhaustion_level - 1)

    return jsonify(
        hp_current=hp_max,
        hit_dice_spent=new_hit_dice_spent,
        exhaustion_level=new_exhaustion,
    )


@bp.post("/v1/phb/equipment-load")
def phb_equipment_load():
    data = request.get_json(silent=True) or {}
    strength = data.get("strength")
    weight = data.get("weight")

    if not valid_int(strength) or strength < 0:
        return jsonify(error="invalid strength"), 400
    if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight < 0:
        return jsonify(error="invalid weight"), 400

    capacity = strength * 15
    encumbered = weight > capacity

    return jsonify(capacity=capacity, weight=weight, encumbered=encumbered)
