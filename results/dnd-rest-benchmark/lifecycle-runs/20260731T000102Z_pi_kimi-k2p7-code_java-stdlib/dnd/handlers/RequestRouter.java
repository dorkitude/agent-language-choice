package dnd.handlers;

import com.sun.net.httpserver.HttpServer;

import dnd.storage.Storage;

/**
 * Registers all HTTP contexts and routes requests to domain handlers.
 * This class is intentionally thin: each domain owns its handler class,
 * and shared concerns (authentication, error bodies, method checks) live in
 * {@link BaseHandler}.
 */
public final class RequestRouter {
    private final CoreHandler core;
    private final CombatHandler combat;
    private final AuthHandler auth;
    private final StorageHandler storageHandler;
    private final CompendiumHandler compendium;
    private final CampaignHandler campaign;
    private final PhbHandler phb;
    private final DmToolHandler dm;
    private final PlayCampaignHandler play;

    public RequestRouter(Storage storage) {
        this.core = new CoreHandler(storage);
        this.combat = new CombatHandler(storage);
        this.auth = new AuthHandler(storage);
        this.storageHandler = new StorageHandler(storage);
        this.compendium = new CompendiumHandler(storage);
        this.campaign = new CampaignHandler(storage);
        this.phb = new PhbHandler(storage);
        this.dm = new DmToolHandler(storage);
        this.play = new PlayCampaignHandler(storage);
    }

    public void register(HttpServer server) {
        // Core / health.
        server.createContext("/health", core::handleHealth);
        server.createContext("/healthz", core::handleHealthz);
        server.createContext("/readyz", core::handleReadyz);

        // Public API schema.
        server.createContext("/v1/schema", core::handleSchema);

        // Dice, checks, encounter math, initiative, character rules.
        server.createContext("/v1/dice/stats", core::handleDiceStats);
        server.createContext("/v1/checks/ability", core::handleAbilityCheck);
        server.createContext("/v1/encounters/adjusted-xp", core::handleAdjustedXp);
        server.createContext("/v1/initiative/order", core::handleInitiative);
        server.createContext("/v1/characters/ability-modifier", core::handleAbilityModifier);
        server.createContext("/v1/characters/proficiency", core::handleProficiency);
        server.createContext("/v1/characters/derived-stats", core::handleDerivedStats);

        // Combat sessions.
        server.createContext("/v1/combat/sessions", combat::handleCombatSessionCreate);
        server.createContext("/v1/combat/sessions/", combat::handleCombatSessionAction);

        // Auth.
        server.createContext("/v1/auth/register", auth::handleRegister);
        server.createContext("/v1/auth/login", auth::handleLogin);

        // Storage admin.
        server.createContext("/v1/storage/status", storageHandler::handleStorageStatus);
        server.createContext("/v1/storage/reset", storageHandler::handleStorageReset);

        // Compendium.
        server.createContext("/v1/compendium/monsters", compendium::handleMonsterCreate);
        server.createContext("/v1/compendium/monsters/", compendium::handleMonsterRead);
        server.createContext("/v1/compendium/items", compendium::handleItemCreate);
        server.createContext("/v1/compendium/items/", compendium::handleItemRead);

        // Campaign management.
        server.createContext("/v1/campaigns", campaign::handleCampaignCreate);
        server.createContext("/v1/campaigns/", campaign::handleCampaignAction);

        // PHB rules.
        server.createContext("/v1/phb/spell-slots", phb::handleSpellSlots);
        server.createContext("/v1/phb/rests/long", phb::handleLongRest);
        server.createContext("/v1/phb/equipment-load", phb::handleEquipmentLoad);

        // DM tools.
        server.createContext("/v1/dm/encounter-builder", dm::handleDmEncounterBuilder);
        server.createContext("/v1/dm/loot-parcel", dm::handleDmLootParcel);
        server.createContext("/v1/dm/session-recap", dm::handleDmSessionRecap);

        // Play-surface campaigns.
        server.createContext("/v1/play/campaigns", play::handlePlayCampaignCreate);
        server.createContext("/v1/play/campaigns/", play::handlePlayCampaignAction);
    }
}
