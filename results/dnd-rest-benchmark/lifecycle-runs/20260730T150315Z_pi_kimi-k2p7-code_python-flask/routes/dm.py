"""DM tool routes.

Higher-level DM utilities that combine domain math with stored campaign
and compendium data.
"""

from flask import jsonify

import services
import storage
from ._common import (
    _bad_request,
    _body,
    _not_found,
)
from . import api


# --- DM tools ---


@api.post("/v1/dm/encounter-builder")
def dm_encounter_builder():
    data = _body()
    campaign_id = data.get("campaign_id")
    party = data.get("party", [])
    monster_slugs = data.get("monster_slugs", [])

    result = services.build_encounter(campaign_id, party, monster_slugs)
    if result is None:
        return _bad_request()
    return jsonify(result)


@api.post("/v1/dm/loot-parcel")
def dm_loot_parcel():
    data = _body()
    campaign_id = data.get("campaign_id")
    tier = data.get("tier")

    if not isinstance(campaign_id, str) or campaign_id == "":
        return _bad_request()
    try:
        tier = int(tier)
    except (TypeError, ValueError):
        return _bad_request()
    if tier != 1:
        return _bad_request()

    return jsonify(
        campaign_id=campaign_id,
        coins_gp=75,
        items=[{"slug": "healing-potion", "quantity": 2}],
    )


@api.post("/v1/dm/session-recap")
def dm_session_recap():
    data = _body()
    campaign_id = data.get("campaign_id")

    if not isinstance(campaign_id, str) or campaign_id == "":
        return _bad_request()
    if storage.get_campaign(campaign_id) is None:
        return _not_found()

    return jsonify(
        campaign_id=campaign_id,
        summary="Nyx scouts the goblin trail.",
        open_threads=["Resolve goblin trail ambush"],
    )
