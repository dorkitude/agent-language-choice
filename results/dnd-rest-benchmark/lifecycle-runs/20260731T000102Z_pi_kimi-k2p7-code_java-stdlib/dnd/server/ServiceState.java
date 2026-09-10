package dnd.server;

import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Process-global service state for readiness/maintenance mode.
 * This state is intentionally separate from campaign-local storage
 * because the maintenance switch applies to the entire server process.
 */
public final class ServiceState {
    private static final AtomicBoolean maintenance = new AtomicBoolean(false);

    private ServiceState() {}

    public static boolean isMaintenance() {
        return maintenance.get();
    }

    public static void setMaintenance(boolean value) {
        maintenance.set(value);
    }
}
