package dnd.model;

/**
 * A status condition applied to a combatant.
 * remainingRounds is decremented when the affected combatant starts a turn.
 */
public class Condition {
    public final String condition;
    public int remainingRounds;

    public Condition(String condition, int remainingRounds) {
        this.condition = condition;
        this.remainingRounds = remainingRounds;
    }
}
