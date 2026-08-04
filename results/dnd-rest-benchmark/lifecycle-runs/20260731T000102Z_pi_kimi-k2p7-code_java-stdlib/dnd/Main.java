package dnd;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;

import dnd.handlers.RequestRouter;
import dnd.storage.Storage;

/**
 * Entry point for the D&D helper HTTP server.
 * The server uses only the Java standard library and a local sqlite3 binary.
 */
public class Main {
    public static void main(String[] args) throws Exception {
        Storage storage = new Storage("game.db");
        storage.init();

        String portStr = System.getenv("PORT");
        int port = portStr == null ? 8080 : Integer.parseInt(portStr);
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);

        RequestRouter router = new RequestRouter(storage);
        router.register(server);

        server.setExecutor(null);
        server.start();
    }
}
