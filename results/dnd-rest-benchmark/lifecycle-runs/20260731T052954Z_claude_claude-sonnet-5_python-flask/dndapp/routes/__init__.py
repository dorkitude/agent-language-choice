"""Blueprint registration for the D&D REST API."""

from . import (
    analytics,
    audit,
    auth,
    campaigns,
    characters,
    combat,
    compendium,
    core,
    dm,
    downtime,
    inventory,
    npcs_factions,
    phb,
    play,
    quests,
    sessions,
    storage,
)

_BLUEPRINTS = (
    analytics.bp,
    audit.bp,
    core.bp,
    characters.bp,
    combat.bp,
    auth.bp,
    compendium.bp,
    campaigns.bp,
    phb.bp,
    dm.bp,
    downtime.bp,
    quests.bp,
    npcs_factions.bp,
    storage.bp,
    inventory.bp,
    sessions.bp,
    play.bp,
)


def register_blueprints(app):
    for bp in _BLUEPRINTS:
        app.register_blueprint(bp)
