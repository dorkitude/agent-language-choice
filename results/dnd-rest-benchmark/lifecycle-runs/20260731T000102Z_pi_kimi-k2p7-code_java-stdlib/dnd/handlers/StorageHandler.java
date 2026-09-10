package dnd.handlers;

import com.sun.net.httpserver.HttpExchange;
import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Map;

import dnd.json.JsonUtils;
import dnd.server.HttpSupport;
import dnd.storage.Storage;

/**
 * Administrative handlers for the SQLite storage layer.
 */
public final class StorageHandler extends BaseHandler {
    public StorageHandler(Storage storage) {
        super(storage);
    }

    public void handleStorageStatus(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "GET")) return;
        HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(storage.status()));
    }

    public void handleStorageReset(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        try {
            storage.reset();
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("ok", true);
            res.put("schema_version", 1);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (Exception e) {
            HttpSupport.sendResponse(exchange, 500, "{\"error\":\"Storage reset failed\"}");
        }
    }
}
