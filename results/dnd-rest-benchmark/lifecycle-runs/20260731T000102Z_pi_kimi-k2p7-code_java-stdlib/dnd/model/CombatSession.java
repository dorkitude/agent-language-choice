package dnd.model;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * A persisted combat encounter.
 * Rounds and turns advance according to the stored order list.
 */
public class CombatSession {
    public final String id;
    public int round;
    public int turnIndex;
    public final List<Combatant> order;
    public final Map<String, List<Condition>> conditions;

    public CombatSession(String id, List<Combatant> order) {
        this.id = id;
        this.round = 1;
        this.turnIndex = 0;
        this.order = order;
        this.conditions = new LinkedHashMap<>();
    }
}
