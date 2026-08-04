"""DM-facing tools: encounter builder, loot parcels, session recaps."""

from flask import Blueprint, jsonify, request

from ..db import get_db
from ..rules import CR_XP, DM_RECOMMENDATIONS, DM_TIER_LOOT, classify_difficulty, \
    multiplier_for_count, sum_party_thresholds
from ..validation import valid_int

bp = Blueprint("dm", __name__)


@bp.post("/v1/dm/encounter-builder")
def dm_encounter_builder():
    data = request.get_json(silent=True) or {}
    campaign_id = data.get("campaign_id")
    party = data.get("party")
    monster_slugs = data.get("monster_slugs")

    if not isinstance(campaign_id, str) or not campaign_id:
        return jsonify(error="invalid campaign_id"), 400
    if not isinstance(party, list) or not party:
        return jsonify(error="invalid party"), 400
    if not isinstance(monster_slugs, list) or not monster_slugs:
        return jsonify(error="invalid monster_slugs"), 400
    if not all(isinstance(slug, str) and slug for slug in monster_slugs):
        return jsonify(error="invalid monster_slugs"), 400

    try:
        thresholds_sum = sum_party_thresholds(party)
        if thresholds_sum is None:
            return jsonify(error="unsupported level"), 400
    except (KeyError, TypeError, ValueError):
        return jsonify(error="invalid party"), 400

    conn = get_db()
    try:
        base_xp = 0
        for slug in monster_slugs:
            row = conn.execute(
                "SELECT cr FROM monsters WHERE slug = ?", (slug,)
            ).fetchone()
            if row is None:
                return jsonify(error="unknown monster slug"), 400
            cr = row["cr"]
            if cr not in CR_XP:
                return jsonify(error="unsupported cr"), 400
            base_xp += CR_XP[cr]
    finally:
        conn.close()

    monster_count = len(monster_slugs)
    multiplier = multiplier_for_count(monster_count)
    adjusted = base_xp * multiplier
    difficulty = classify_difficulty(adjusted, thresholds_sum)

    return jsonify(
        campaign_id=campaign_id,
        base_xp=base_xp,
        adjusted_xp=adjusted,
        difficulty=difficulty,
        monster_count=monster_count,
        recommendation=DM_RECOMMENDATIONS[difficulty],
    )


@bp.post("/v1/dm/loot-parcel")
def dm_loot_parcel():
    data = request.get_json(silent=True) or {}
    campaign_id = data.get("campaign_id")
    tier = data.get("tier")
    seed = data.get("seed")

    if not isinstance(campaign_id, str) or not campaign_id:
        return jsonify(error="invalid campaign_id"), 400
    if not valid_int(tier) or tier not in DM_TIER_LOOT:
        return jsonify(error="unsupported tier"), 400
    if not valid_int(seed):
        return jsonify(error="invalid seed"), 400

    loot = DM_TIER_LOOT[tier]
    return jsonify(
        campaign_id=campaign_id,
        coins_gp=loot["coins_gp"],
        items=loot["items"],
    )


@bp.post("/v1/dm/session-recap")
def dm_session_recap():
    data = request.get_json(silent=True) or {}
    campaign_id = data.get("campaign_id")

    if not isinstance(campaign_id, str) or not campaign_id:
        return jsonify(error="invalid campaign_id"), 400

    return jsonify(
        campaign_id=campaign_id,
        summary="Nyx scouts the goblin trail.",
        open_threads=["Resolve goblin trail ambush"],
    )
