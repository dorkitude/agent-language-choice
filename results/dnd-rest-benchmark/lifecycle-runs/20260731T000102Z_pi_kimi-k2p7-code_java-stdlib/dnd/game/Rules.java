package dnd.game;

import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import dnd.json.JsonUtils;

/**
 * D&D 5e style game rules used by the HTTP handlers.
 * All calculations are deterministic and operate only on the supplied inputs.
 */
public final class Rules {
    public static final Map<String, Integer> CR_XP = new HashMap<>();
    static {
        CR_XP.put("0", 10);
        CR_XP.put("1/8", 25);
        CR_XP.put("1/4", 50);
        CR_XP.put("1/2", 100);
        CR_XP.put("1", 200);
        CR_XP.put("2", 450);
        CR_XP.put("3", 700);
        CR_XP.put("4", 1100);
        CR_XP.put("5", 1800);
    }

    public static final Map<Integer, int[]> LEVEL_THRESHOLDS = new HashMap<>();
    static {
        LEVEL_THRESHOLDS.put(1, new int[]{25, 50, 75, 100});
        LEVEL_THRESHOLDS.put(2, new int[]{50, 100, 150, 200});
        LEVEL_THRESHOLDS.put(3, new int[]{75, 150, 225, 400});
        LEVEL_THRESHOLDS.put(4, new int[]{125, 250, 375, 500});
        LEVEL_THRESHOLDS.put(5, new int[]{250, 500, 750, 1100});
        LEVEL_THRESHOLDS.put(6, new int[]{300, 600, 900, 1400});
        LEVEL_THRESHOLDS.put(7, new int[]{350, 750, 1100, 1700});
        LEVEL_THRESHOLDS.put(8, new int[]{450, 900, 1400, 2100});
        LEVEL_THRESHOLDS.put(9, new int[]{550, 1100, 1700, 2500});
        LEVEL_THRESHOLDS.put(10, new int[]{600, 1200, 1900, 2800});
        LEVEL_THRESHOLDS.put(11, new int[]{800, 1600, 2400, 3600});
        LEVEL_THRESHOLDS.put(12, new int[]{1000, 2000, 3000, 4500});
        LEVEL_THRESHOLDS.put(13, new int[]{1100, 2200, 3400, 5100});
        LEVEL_THRESHOLDS.put(14, new int[]{1250, 2500, 3800, 5700});
        LEVEL_THRESHOLDS.put(15, new int[]{1400, 2800, 4300, 6400});
        LEVEL_THRESHOLDS.put(16, new int[]{1600, 3200, 4800, 7200});
        LEVEL_THRESHOLDS.put(17, new int[]{2000, 3900, 5900, 8800});
        LEVEL_THRESHOLDS.put(18, new int[]{2100, 4200, 6300, 9500});
        LEVEL_THRESHOLDS.put(19, new int[]{2400, 4900, 7300, 10900});
        LEVEL_THRESHOLDS.put(20, new int[]{2800, 5700, 8500, 12700});
    }

    public static final Map<String, Integer> HIT_DICE = new HashMap<>();
    static {
        HIT_DICE.put("barbarian", 12);
        HIT_DICE.put("bard", 8);
        HIT_DICE.put("cleric", 8);
        HIT_DICE.put("druid", 8);
        HIT_DICE.put("fighter", 10);
        HIT_DICE.put("monk", 8);
        HIT_DICE.put("paladin", 10);
        HIT_DICE.put("ranger", 10);
        HIT_DICE.put("rogue", 8);
        HIT_DICE.put("sorcerer", 6);
        HIT_DICE.put("warlock", 8);
        HIT_DICE.put("wizard", 6);
    }

    public static final Set<String> VALID_RACES = new HashSet<>();
    static {
        VALID_RACES.add("aarakocra");
        VALID_RACES.add("aasimar");
        VALID_RACES.add("bugbear");
        VALID_RACES.add("dragonborn");
        VALID_RACES.add("dwarf");
        VALID_RACES.add("elf");
        VALID_RACES.add("firbolg");
        VALID_RACES.add("gnome");
        VALID_RACES.add("goblin");
        VALID_RACES.add("half-elf");
        VALID_RACES.add("half-orc");
        VALID_RACES.add("halfling");
        VALID_RACES.add("hobgoblin");
        VALID_RACES.add("human");
        VALID_RACES.add("kenku");
        VALID_RACES.add("kobold");
        VALID_RACES.add("lizardfolk");
        VALID_RACES.add("orc");
        VALID_RACES.add("tabaxi");
        VALID_RACES.add("tiefling");
        VALID_RACES.add("triton");
        VALID_RACES.add("yuan-ti");
    }

    public static final Set<String> VALID_CLASSES = new HashSet<>();
    static {
        VALID_CLASSES.add("barbarian");
        VALID_CLASSES.add("bard");
        VALID_CLASSES.add("cleric");
        VALID_CLASSES.add("druid");
        VALID_CLASSES.add("fighter");
        VALID_CLASSES.add("monk");
        VALID_CLASSES.add("paladin");
        VALID_CLASSES.add("ranger");
        VALID_CLASSES.add("rogue");
        VALID_CLASSES.add("sorcerer");
        VALID_CLASSES.add("warlock");
        VALID_CLASSES.add("wizard");
    }

    public static final Set<String> VALID_BACKGROUNDS = new HashSet<>();
    static {
        VALID_BACKGROUNDS.add("acolyte");
        VALID_BACKGROUNDS.add("charlatan");
        VALID_BACKGROUNDS.add("criminal");
        VALID_BACKGROUNDS.add("entertainer");
        VALID_BACKGROUNDS.add("folk_hero");
        VALID_BACKGROUNDS.add("guild_artisan");
        VALID_BACKGROUNDS.add("hermit");
        VALID_BACKGROUNDS.add("noble");
        VALID_BACKGROUNDS.add("outlander");
        VALID_BACKGROUNDS.add("sage");
        VALID_BACKGROUNDS.add("sailor");
        VALID_BACKGROUNDS.add("soldier");
        VALID_BACKGROUNDS.add("urchin");
    }

    public static final Set<String> VALID_ABILITIES = new HashSet<>();
    static {
        VALID_ABILITIES.add("str");
        VALID_ABILITIES.add("dex");
        VALID_ABILITIES.add("con");
        VALID_ABILITIES.add("int");
        VALID_ABILITIES.add("wis");
        VALID_ABILITIES.add("cha");
    }

    public static final Set<String> VALID_SKILLS = new HashSet<>();
    static {
        VALID_SKILLS.add("acrobatics");
        VALID_SKILLS.add("animal-handling");
        VALID_SKILLS.add("animal handling");
        VALID_SKILLS.add("arcana");
        VALID_SKILLS.add("athletics");
        VALID_SKILLS.add("deception");
        VALID_SKILLS.add("history");
        VALID_SKILLS.add("insight");
        VALID_SKILLS.add("intimidation");
        VALID_SKILLS.add("investigation");
        VALID_SKILLS.add("medicine");
        VALID_SKILLS.add("nature");
        VALID_SKILLS.add("perception");
        VALID_SKILLS.add("performance");
        VALID_SKILLS.add("persuasion");
        VALID_SKILLS.add("religion");
        VALID_SKILLS.add("sleight-of-hand");
        VALID_SKILLS.add("sleight of hand");
        VALID_SKILLS.add("stealth");
        VALID_SKILLS.add("survival");
    }

    /**
     * Determines whether a spell is valid for a character class.
     * In this simplified system wizards may learn any spell, rogues may not
     * learn spells, and all other classes are treated as non-spellcasters.
     */
    public static boolean isValidSpellForClass(String spellId, String className) {
        if (spellId == null || className == null) return false;
        String cls = className.toLowerCase();
        if ("rogue".equals(cls)) return false;
        if ("wizard".equals(cls)) return true;
        return false;
    }

    /**
     * Returns true for classes that can cast spells in this simplified system.
     */
    public static boolean isSpellcastingClass(String className) {
        return "wizard".equals(className);
    }

    /**
     * Returns the number of spell slots a character of the given class and level
     * has for {@code slotLevel}. In this simplified system a wizard has one
     * first-level slot per character level and no higher-level slots.
     */
    public static int spellSlots(String className, int level, int slotLevel) {
        String cls = className == null ? null : className.toLowerCase();
        if (level < 1 || slotLevel < 1 || slotLevel > 9) return 0;
        if ("wizard".equals(cls)) {
            return slotLevel == 1 ? level : 0;
        }
        return 0;
    }

    private Rules() {}

    public static boolean isValidAbility(String ability) {
        return ability != null && VALID_ABILITIES.contains(ability.toLowerCase());
    }

    public static boolean isValidSkill(String skill) {
        return skill != null && VALID_SKILLS.contains(skill.toLowerCase());
    }

    public static int hitDieAtLevel1(String className) {
        Integer die = HIT_DICE.get(className.toLowerCase());
        if (die == null) throw new RuntimeException("Unknown class hit die");
        return die;
    }

    public static int abilityModifier(int score) {
        return (int) Math.floor((score - 10) / 2.0);
    }

    public static int proficiencyBonus(int level) {
        if (level <= 4) return 2;
        if (level <= 8) return 3;
        if (level <= 12) return 4;
        if (level <= 16) return 5;
        return 6;
    }

    public static Map<String, Object> calculateEncounter(List<?> partyList, List<Map<String, Object>> monsters) {
        int baseXp = 0;
        int monsterCount = 0;
        for (Map<String, Object> monster : monsters) {
            String cr = (String) monster.get("cr");
            int count = JsonUtils.toInt(monster.get("count"));
            Integer xp = CR_XP.get(cr);
            if (xp == null) throw new RuntimeException("Unsupported CR: " + cr);
            baseXp += xp * count;
            monsterCount += count;
        }

        double multiplier;
        if (monsterCount == 1) multiplier = 1;
        else if (monsterCount == 2) multiplier = 1.5;
        else if (monsterCount <= 6) multiplier = 2;
        else if (monsterCount <= 10) multiplier = 2.5;
        else if (monsterCount <= 14) multiplier = 3;
        else multiplier = 4;

        long adjustedXp = Math.round(baseXp * multiplier);

        int easy = 0, medium = 0, hard = 0, deadly = 0;
        for (Object memberObj : partyList) {
            Map<String, Object> member = (Map<String, Object>) memberObj;
            int level = JsonUtils.toInt(member.get("level"));
            int[] thresholds = LEVEL_THRESHOLDS.get(level);
            if (thresholds == null) throw new RuntimeException("Unsupported level: " + level);
            easy += thresholds[0];
            medium += thresholds[1];
            hard += thresholds[2];
            deadly += thresholds[3];
        }

        String difficulty;
        if (adjustedXp >= deadly) difficulty = "deadly";
        else if (adjustedXp >= hard) difficulty = "hard";
        else if (adjustedXp >= medium) difficulty = "medium";
        else if (adjustedXp >= easy) difficulty = "easy";
        else difficulty = "trivial";

        Map<String, Object> thresholds = new LinkedHashMap<>();
        thresholds.put("easy", easy);
        thresholds.put("medium", medium);
        thresholds.put("hard", hard);
        thresholds.put("deadly", deadly);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("base_xp", baseXp);
        result.put("monster_count", monsterCount);
        result.put("multiplier", multiplier);
        result.put("adjusted_xp", adjustedXp);
        result.put("difficulty", difficulty);
        result.put("thresholds", thresholds);
        return result;
    }

    public static String recommendationForDifficulty(String difficulty) {
        switch (difficulty) {
            case "trivial": return "no threat";
            case "easy": return "safe warm-up";
            case "medium": return "standard challenge";
            case "hard": return "risky fight";
            case "deadly": return "likely lethal";
            default: return "proceed with caution";
        }
    }

    public static String deriveOpenThread(String summary) {
        String s = summary.trim();
        if (s.isEmpty()) return "Resolve unfinished business";
        String[] words = s.split("\\s+");
        if (words.length >= 3) {
            int start = 2;
            if (words[start].equalsIgnoreCase("the")) start++;
            StringBuilder sb = new StringBuilder();
            for (int i = start; i < words.length; i++) {
                if (i > start) sb.append(' ');
                sb.append(words[i]);
            }
            String rest = sb.toString().trim();
            if (rest.isEmpty()) rest = s;
            rest = rest.replaceAll("[.!?\\p{Punct}]+$", "");
            return "Resolve " + rest + " ambush";
        }
        String rest = s.replaceAll("[.!?\\p{Punct}]+$", "");
        return "Resolve " + rest;
    }
}
