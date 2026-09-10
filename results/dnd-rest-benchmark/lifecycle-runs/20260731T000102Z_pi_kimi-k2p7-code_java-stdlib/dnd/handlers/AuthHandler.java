package dnd.handlers;

import com.sun.net.httpserver.HttpExchange;
import java.io.IOException;
import java.security.SecureRandom;
import java.security.spec.KeySpec;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Pattern;

import javax.crypto.SecretKey;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;

import dnd.json.JsonUtils;
import dnd.model.User;
import dnd.server.HttpSupport;
import dnd.storage.Storage;

/**
 * User registration and login handlers.
 * Passwords are hashed with PBKDF2 and a random per-user salt.
 */
public final class AuthHandler extends BaseHandler {
    private static final Pattern USERNAME_PATTERN = Pattern.compile("^[a-z0-9_-]{2,32}$");
    private static final SecureRandom RANDOM = new SecureRandom();

    public AuthHandler(Storage storage) {
        super(storage);
    }

    public void handleRegister(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String username = (String) req.get("username");
            String password = (String) req.get("password");
            String role = (String) req.get("role");

            if (username == null || password == null || role == null) throw new RuntimeException("Missing fields");
            if (!USERNAME_PATTERN.matcher(username).matches()) throw new RuntimeException("Invalid username");
            if (password.length() < 8) throw new RuntimeException("Password too short");
            if (!"dm".equals(role) && !"player".equals(role)) throw new RuntimeException("Invalid role");

            if (storage.getUser(username) != null) {
                HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Username already exists\"}");
                return;
            }

            String salt = generateSalt();
            String hash = hashPassword(password, salt);
            User user = new User(username, role, salt, hash);
            if (!storage.insertUser(user)) {
                HttpSupport.sendResponse(exchange, 409, "{\"error\":\"Username already exists\"}");
                return;
            }

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("username", username);
            res.put("role", role);
            HttpSupport.sendResponse(exchange, 201, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    public void handleLogin(HttpExchange exchange) throws IOException {
        if (!requireMethod(exchange, "POST")) return;
        try {
            String body = HttpSupport.readBody(exchange);
            Map<String, Object> req = JsonUtils.parseJsonObject(body);
            String username = (String) req.get("username");
            String password = (String) req.get("password");

            if (username == null || password == null) throw new RuntimeException("Missing fields");

            User user = storage.getUser(username);
            if (user == null || !hashPassword(password, user.salt).equals(user.hash)) {
                HttpSupport.sendResponse(exchange, 401, "{\"error\":\"Invalid credentials\"}");
                return;
            }

            Map<String, Object> res = new LinkedHashMap<>();
            res.put("username", username);
            res.put("token", "session-" + username);
            HttpSupport.sendResponse(exchange, 200, JsonUtils.toJson(res));
        } catch (RuntimeException e) {
            badRequest(exchange);
        }
    }

    private String hashPassword(String password, String salt) {
        try {
            SecretKeyFactory factory = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256");
            byte[] saltBytes = Base64.getDecoder().decode(salt);
            KeySpec spec = new PBEKeySpec(password.toCharArray(), saltBytes, 65536, 256);
            SecretKey key = factory.generateSecret(spec);
            return Base64.getEncoder().encodeToString(key.getEncoded());
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    private String generateSalt() {
        byte[] salt = new byte[16];
        RANDOM.nextBytes(salt);
        return Base64.getEncoder().encodeToString(salt);
    }
}
