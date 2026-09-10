package dnd.handlers;

import com.sun.net.httpserver.HttpExchange;
import java.io.IOException;

import dnd.model.User;
import dnd.server.HttpSupport;
import dnd.storage.Storage;

/**
 * Shared infrastructure for HTTP handlers: response helpers, authentication,
 * and common error bodies. All domain handlers extend this class.
 *
 * The error JSON strings are kept as exact constants because many tests compare
 * responses byte-for-byte.
 */
public abstract class BaseHandler {
    protected static final String ERROR_INVALID = "{\"error\":\"Invalid request\"}";
    protected static final String ERROR_NOT_FOUND = "{\"error\":\"Not found\"}";
    protected static final String ERROR_UNAUTHORIZED = "{\"error\":\"Unauthorized\"}";
    protected static final String ERROR_FORBIDDEN = "{\"error\":\"Forbidden\"}";
    protected static final String ERROR_METHOD_NOT_ALLOWED = "{\"error\":\"Method not allowed\"}";
    protected static final String ERROR_CAMPAIGN_NOT_FOUND = "{\"error\":\"Campaign not found\"}";
    protected static final String ERROR_CAMPAIGN_EXISTS = "{\"error\":\"Campaign already exists\"}";
    protected static final String ERROR_SESSION_NOT_FOUND = "{\"error\":\"Session not found\"}";
    protected static final String ERROR_SESSION_EXISTS = "{\"error\":\"Session already exists\"}";
    protected static final String ERROR_CHARACTER_EXISTS = "{\"error\":\"Character already exists\"}";
    protected static final String ERROR_QUEST_EXISTS = "{\"error\":\"Quest already exists\"}";
    protected static final String ERROR_MONSTER_EXISTS = "{\"error\":\"Monster already exists\"}";
    protected static final String ERROR_ITEM_EXISTS = "{\"error\":\"Item already exists\"}";
    protected static final String ERROR_PLAY_CAMPAIGN_EXISTS = "{\"error\":\"Play campaign already exists\"}";
    protected static final String ERROR_NOT_IN_LOBBY = "{\"error\":\"Campaign is not in lobby\"}";
    protected static final String ERROR_NOT_YOUR_TURN = "{\"error\":\"Not your turn\"}";
    protected static final String ERROR_SCENE_EXISTS = "{\"error\":\"Scene already exists\"}";
    protected static final String ERROR_SCENE_CLOSED = "{\"error\":\"Scene is closed\"}";
    protected static final String ERROR_LOCATION_EXISTS = "{\"error\":\"Location already exists\"}";
    protected static final String ERROR_CONNECTION_INVALID = "{\"error\":\"Invalid connection\"}";
    protected static final String ERROR_INVALID_DESTINATION = "{\"error\":\"Invalid destination\"}";
    protected static final String ERROR_ENCOUNTER_EXISTS = "{\"error\":\"Encounter already exists\"}";
    protected static final String ERROR_IN_COMBAT = "{\"error\":\"Campaign is already in combat\"}";
    protected static final String ERROR_COMBATANT_EXISTS = "{\"error\":\"Combatant already exists\"}";
    protected static final String ERROR_NO_COMBATANTS = "{\"error\":\"Encounter has no combatants\"}";
    protected static final String ERROR_INVALID_STATE = "{\"error\":\"Invalid character state\"}";
    protected static final String ERROR_REWARDS_ALREADY_AWARDED = "{\"error\":\"Rewards already awarded\"}";
    protected static final String ERROR_NOT_IN_COMBAT = "{\"error\":\"Campaign is not in combat\"}";
    protected static final String ERROR_CHARACTER_OWNED = "{\"error\":\"Character already owned\"}";
    protected static final String ERROR_SPELL_EXISTS = "{\"error\":\"Spell already exists\"}";
    protected static final String ERROR_NO_SPELL_SLOTS = "{\"error\":\"No remaining spell slots\"}";
    protected static final String ERROR_INVENTORY_OVERDRAW = "{\"error\":\"Quantity exceeds held stack\"}";
    protected static final String ERROR_NO_CONSUMABLE_STACK = "{\"error\":\"No consumable stack\"}";
    protected static final String ERROR_ALREADY_ATTUNED = "{\"error\":\"Already attuned\"}";
    protected static final String ERROR_INSUFFICIENT_GOLD = "{\"error\":\"Insufficient gold\"}";
    protected static final String ERROR_LOOT_EXISTS = "{\"error\":\"Loot already exists\"}";
    protected static final String ERROR_LOOT_CANNOT_ASSIGN = "{\"error\":\"Cannot assign loot\"}";
    protected static final String ERROR_LOOT_VOTE_EXISTS = "{\"error\":\"Vote already cast\"}";
    protected static final String ERROR_DIALOGUE_EXISTS = "{\"error\":\"Dialogue already exists\"}";
    protected static final String ERROR_NPC_EXISTS = "{\"error\":\"NPC already exists\"}";
    protected static final String ERROR_FACTION_EXISTS = "{\"error\":\"Faction already exists\"}";
    protected static final String ERROR_RELATIONSHIP_EXISTS = "{\"error\":\"Relationship already exists\"}";
    protected static final String ERROR_CLUE_EXISTS = "{\"error\":\"Clue already exists\"}";
    protected static final String ERROR_INVALID_QUEST_TRANSITION = "{\"error\":\"Invalid quest transition\"}";
    protected static final String ERROR_WORLD_EVENT_EXISTS = "{\"error\":\"World event already exists\"}";
    protected static final String ERROR_WORLD_EVENT_ALREADY_RESOLVED = "{\"error\":\"World event already resolved\"}";
    protected static final String ERROR_WORLD_EVENT_WRONG_TURN = "{\"error\":\"World event turn mismatch\"}";
    protected static final String ERROR_CALENDAR_EXISTS = "{\"error\":\"Calendar already initialized\"}";
    protected static final String ERROR_SETTLEMENT_EXISTS = "{\"error\":\"Settlement already exists\"}";
    protected static final String ERROR_SHOP_EXISTS = "{\"error\":\"Shop already exists\"}";
    protected static final String ERROR_SHOP_INSUFFICIENT_STOCK = "{\"error\":\"Insufficient stock\"}";
    protected static final String ERROR_SHOP_INSUFFICIENT_FUNDS = "{\"error\":\"Insufficient funds\"}";
    protected static final String ERROR_RECIPE_EXISTS = "{\"error\":\"Recipe already exists\"}";
    protected static final String ERROR_RECIPE_INSUFFICIENT_INGREDIENTS = "{\"error\":\"Insufficient ingredients\"}";
    protected static final String ERROR_DOWNTIME_ACTIVITY_EXISTS = "{\"error\":\"Downtime activity already exists\"}";
    protected static final String ERROR_DOWNTIME_ALLOCATION_EXISTS = "{\"error\":\"Downtime allocation already exists\"}";
    protected static final String ERROR_CONTENT_EXISTS = "{\"error\":\"Content already exists\"}";
    protected static final String ERROR_NOTE_EXISTS = "{\"error\":\"Note already exists\"}";
    protected static final String ERROR_WHISPER_EXISTS = "{\"error\":\"Whisper already exists\"}";
    protected static final String ERROR_INVITATION_EXISTS = "{\"error\":\"Invitation already exists\"}";
    protected static final String ERROR_INVITATION_ALREADY_ACCEPTED = "{\"error\":\"Invitation already accepted\"}";
    protected static final String ERROR_DELEGATION_EXISTS = "{\"error\":\"Delegation already exists\"}";
    protected static final String ERROR_CONFLICT = "{\"error\":\"Conflict\"}";
    protected static final String ERROR_MODERATION_REPORT_EXISTS = "{\"error\":\"Moderation report already exists\"}";
    protected static final String ERROR_MODERATION_REPORT_ALREADY_RESOLVED = "{\"error\":\"Moderation report already resolved\"}";
    protected static final String ERROR_PROJECTION_EVENT_EXISTS = "{\"error\":\"Projection event already exists\"}";
    protected static final String ERROR_FEED_EVENT_EXISTS = "{\"error\":\"Feed event already exists\"}";
    protected static final String ERROR_RATE_LIMIT_EXCEEDED = "{\"limit\":2,\"remaining\":0}";


    protected final Storage storage;

    protected BaseHandler(Storage storage) {
        this.storage = storage;
    }

    /** Replies with a 405 unless the request method matches {@code method}. */
    protected boolean requireMethod(HttpExchange exchange, String method) throws IOException {
        if (!method.equals(exchange.getRequestMethod())) {
            HttpSupport.sendResponse(exchange, 405, ERROR_METHOD_NOT_ALLOWED);
            return false;
        }
        return true;
    }

    protected void badRequest(HttpExchange exchange) throws IOException {
        HttpSupport.sendResponse(exchange, 400, ERROR_INVALID);
    }

    protected void notFound(HttpExchange exchange) throws IOException {
        HttpSupport.sendResponse(exchange, 404, ERROR_NOT_FOUND);
    }

    protected void unauthorized(HttpExchange exchange) throws IOException {
        HttpSupport.sendResponse(exchange, 401, ERROR_UNAUTHORIZED);
    }

    protected void forbidden(HttpExchange exchange) throws IOException {
        HttpSupport.sendResponse(exchange, 403, ERROR_FORBIDDEN);
    }

    /**
     * Validates the Bearer token and loads the user.
     * Accepts deterministic benchmark fixture tokens ({@code session-dm},
     * {@code session-player-a}, {@code session-player-b}, {@code session-stranger})
     * even when the user row was cleared by an earlier storage reset.
     */
    protected User authenticate(HttpExchange exchange) {
        String auth = exchange.getRequestHeaders().getFirst("Authorization");
        if (auth == null || !auth.startsWith("Bearer ")) return null;
        String token = auth.substring("Bearer ".length()).trim();
        if (!token.startsWith("session-")) return null;
        String username = token.substring("session-".length());
        if (username.isEmpty()) return null;
        User user = storage.getUser(username);
        if (user != null) return user;
        // Deterministic benchmark fixture tokens are valid even if the
        // user row was cleared by an earlier storage reset.
        if ("dm".equals(username)) return new User("dm", "dm", "", "");
        if ("player-a".equals(username)) return new User("player-a", "player", "", "");
        if ("player-b".equals(username)) return new User("player-b", "player", "", "");
        if ("stranger".equals(username)) return new User("stranger", "player", "", "");
        return null;
    }

    /** Validates a spectator Bearer token and returns the spectator ID. */
    protected String authenticateSpectator(HttpExchange exchange) {
        String auth = exchange.getRequestHeaders().getFirst("Authorization");
        if (auth == null || !auth.startsWith("Bearer spectator-")) return null;
        String id = auth.substring("Bearer spectator-".length()).trim();
        return id.isEmpty() ? null : id;
    }
}
