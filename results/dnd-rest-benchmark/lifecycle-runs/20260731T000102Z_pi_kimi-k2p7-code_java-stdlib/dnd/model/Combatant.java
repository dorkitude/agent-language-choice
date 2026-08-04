package dnd.model;

/**
 * A combatant in an initiative order.
 * The score is the initiative roll plus the dexterity modifier.
 */
public class Combatant {
    public final String name;
    public final int score;
    public final int dex;
    public final int roll;

    public Combatant(String name, int score, int dex, int roll) {
        this.name = name;
        this.score = score;
        this.dex = dex;
        this.roll = roll;
    }
}
