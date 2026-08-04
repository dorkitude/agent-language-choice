"""Higher-level business workflows that combine domain math and storage."""

import domain
import storage


def build_encounter(campaign_id, party, monster_slugs):
    """Validate inputs and build an encounter summary from stored monsters.

    Returns a dict on success or None if any input is invalid or a slug
    does not resolve to a stored monster.
    """
    if not isinstance(campaign_id, str) or campaign_id == "":
        return None
    if not isinstance(party, list) or not isinstance(monster_slugs, list):
        return None
    if len(monster_slugs) == 0:
        return None

    for member in party:
        if not isinstance(member, dict):
            return None
        try:
            if int(member["level"]) != 3:
                return None
        except (KeyError, TypeError, ValueError):
            return None

    cr_counts = {}
    for slug in monster_slugs:
        if not isinstance(slug, str):
            return None
        monster = storage.get_monster(slug)
        if monster is None:
            return None
        cr_counts[monster["cr"]] = cr_counts.get(monster["cr"], 0) + 1

    # Reuse the domain-level encounter math; no need to duplicate it here.
    monsters = [{"cr": cr, "count": count} for cr, count in cr_counts.items()]
    result = domain.compute_adjusted_xp(party, monsters)
    if result is None:
        return None

    result["campaign_id"] = campaign_id
    result["recommendation"] = domain.DIFFICULTY_RECOMMENDATION[result["difficulty"]]
    return result


# --- Campaign analytics ---


def _campaign_readiness_signals(camp_id):
    """Return the four boolean readiness signals for a campaign."""
    campaign = storage.get_campaign(camp_id)
    if campaign is None:
        return None
    quest_summary = storage.get_quest_summary(camp_id)
    return {
        "has_dm": bool(campaign.get("dm")),
        "has_characters": storage.get_character_count(camp_id) > 0,
        "has_next_session": storage.get_session_count(camp_id) > 0,
        "has_active_quest": quest_summary.get("active", 0) > 0,
    }


def build_analytics_summary(camp_id):
    """Return a deterministic campaign analytics summary.

    Returns None if the campaign does not exist.
    """
    signals = _campaign_readiness_signals(camp_id)
    if signals is None:
        return None

    readiness_score = 25 + 15 * sum(1 for value in signals.values() if value)
    quest_summary = storage.get_quest_summary(camp_id)
    relationships = storage.get_relationship_summary(camp_id)

    return {
        "campaign_id": camp_id,
        "readiness_score": readiness_score,
        "open_quests": quest_summary.get("active", 0),
        "friendly_npcs": relationships.get("friendly_npcs", 0),
        "scheduled_sessions": storage.get_session_count(camp_id),
        "inventory_items": storage.get_inventory_item_count(camp_id),
    }


def build_risk_report(camp_id, include_zeroes=True):
    """Return a deterministic maintenance risk report for a campaign.

    The include_zeroes flag is accepted for API compatibility but does not
    change the report shape. Returns None if the campaign does not exist.
    """
    signals = _campaign_readiness_signals(camp_id)
    if signals is None:
        return None

    missing = [name for name, value in signals.items() if not value]
    if not missing:
        risk_level = "low"
    elif len(missing) <= 2:
        risk_level = "medium"
    else:
        risk_level = "high"

    return {
        "campaign_id": camp_id,
        "risk_level": risk_level,
        "missing": missing,
        "signals": signals,
    }
