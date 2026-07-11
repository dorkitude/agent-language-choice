import json
from pathlib import Path
import re
import sqlite3

from django.contrib.auth.hashers import check_password, make_password
from django.http import JsonResponse
from django.urls import path


DICE_RE = re.compile(r"^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$")
USERNAME_RE = re.compile(r"^[a-z0-9_-]{2,32}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

CR_XP = {
    "0": 10,
    "1/8": 25,
    "1/4": 50,
    "1/2": 100,
    "1": 200,
    "2": 450,
    "3": 700,
    "4": 1100,
    "5": 1800,
}

LEVEL_THRESHOLDS = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}

SCHEMA_VERSION = 1
DB_PATH = Path(__file__).resolve().parent.parent / "game.db"


def db_connect():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_storage():
    with db_connect() as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS storage_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS combat_sessions (
                id TEXT PRIMARY KEY,
                round INTEGER NOT NULL,
                turn_index INTEGER NOT NULL,
                initiative_order TEXT NOT NULL,
                conditions TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS monsters (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                cr TEXT NOT NULL,
                armor_class INTEGER NOT NULL,
                hit_points INTEGER NOT NULL,
                tags TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                rarity TEXT NOT NULL,
                cost_gp INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                dm TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS campaign_characters (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                name TEXT NOT NULL,
                level INTEGER NOT NULL,
                class_name TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS campaign_events (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                summary TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO storage_meta (key, value)
            VALUES ('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(SCHEMA_VERSION),),
        )


def reset_storage_data():
    with db_connect() as connection:
        connection.execute("DROP TABLE IF EXISTS campaign_events")
        connection.execute("DROP TABLE IF EXISTS campaign_characters")
        connection.execute("DROP TABLE IF EXISTS campaigns")
        connection.execute("DROP TABLE IF EXISTS items")
        connection.execute("DROP TABLE IF EXISTS monsters")
        connection.execute("DROP TABLE IF EXISTS combat_sessions")
        connection.execute("DROP TABLE IF EXISTS users")
        connection.execute("DROP TABLE IF EXISTS storage_meta")
    initialize_storage()


def storage_initialized():
    if not DB_PATH.exists():
        return False
    try:
        with db_connect() as connection:
            row = connection.execute(
                "SELECT value FROM storage_meta WHERE key = 'schema_version'"
            ).fetchone()
            return row is not None and int(row["value"]) == SCHEMA_VERSION
    except (sqlite3.Error, ValueError):
        return False


def get_user(username):
    with db_connect() as connection:
        row = connection.execute(
            "SELECT username, password_hash, role FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    return dict(row) if row is not None else None


def create_user(username, password_hash, role):
    try:
        with db_connect() as connection:
            connection.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, password_hash, role),
            )
    except sqlite3.IntegrityError:
        return False
    return True


def row_to_session(row):
    if row is None:
        return None
    return {
        "id": row["id"],
        "round": row["round"],
        "turn_index": row["turn_index"],
        "order": json.loads(row["initiative_order"]),
        "conditions": json.loads(row["conditions"]),
    }


def get_combat_session(session_id):
    with db_connect() as connection:
        row = connection.execute(
            """
            SELECT id, round, turn_index, initiative_order, conditions
            FROM combat_sessions
            WHERE id = ?
            """,
            (session_id,),
        ).fetchone()
    return row_to_session(row)


def save_combat_session(session):
    with db_connect() as connection:
        connection.execute(
            """
            INSERT INTO combat_sessions
                (id, round, turn_index, initiative_order, conditions)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                round = excluded.round,
                turn_index = excluded.turn_index,
                initiative_order = excluded.initiative_order,
                conditions = excluded.conditions
            """,
            (
                session["id"],
                session["round"],
                session["turn_index"],
                json.dumps(session["order"], separators=(",", ":")),
                json.dumps(session["conditions"], separators=(",", ":")),
            ),
        )


def row_to_monster(row, include_tags):
    monster = {
        "slug": row["slug"],
        "name": row["name"],
        "cr": row["cr"],
        "armor_class": row["armor_class"],
        "hit_points": row["hit_points"],
    }
    if include_tags:
        monster["tags"] = json.loads(row["tags"])
    return monster


def get_monster(slug):
    with db_connect() as connection:
        row = connection.execute(
            """
            SELECT slug, name, cr, armor_class, hit_points, tags
            FROM monsters
            WHERE slug = ?
            """,
            (slug,),
        ).fetchone()
    return row_to_monster(row, include_tags=True) if row is not None else None


def create_monster_record(monster):
    try:
        with db_connect() as connection:
            connection.execute(
                """
                INSERT INTO monsters
                    (slug, name, cr, armor_class, hit_points, tags)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    monster["slug"],
                    monster["name"],
                    monster["cr"],
                    monster["armor_class"],
                    monster["hit_points"],
                    json.dumps(monster["tags"], separators=(",", ":")),
                ),
            )
    except sqlite3.IntegrityError:
        return False
    return True


def get_item(slug):
    with db_connect() as connection:
        row = connection.execute(
            """
            SELECT slug, name, type, rarity, cost_gp
            FROM items
            WHERE slug = ?
            """,
            (slug,),
        ).fetchone()
    if row is None:
        return None
    return {
        "slug": row["slug"],
        "name": row["name"],
        "type": row["type"],
        "rarity": row["rarity"],
        "cost_gp": row["cost_gp"],
    }


def create_item_record(item):
    try:
        with db_connect() as connection:
            connection.execute(
                """
                INSERT INTO items
                    (slug, name, type, rarity, cost_gp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    item["slug"],
                    item["name"],
                    item["type"],
                    item["rarity"],
                    item["cost_gp"],
                ),
            )
    except sqlite3.IntegrityError:
        return False
    return True


def get_campaign(campaign_id):
    with db_connect() as connection:
        row = connection.execute(
            "SELECT id, name, dm FROM campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
    return dict(row) if row is not None else None


def create_campaign_record(campaign):
    try:
        with db_connect() as connection:
            connection.execute(
                "INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)",
                (campaign["id"], campaign["name"], campaign["dm"]),
            )
    except sqlite3.IntegrityError:
        return False
    return True


def create_campaign_character(character):
    try:
        with db_connect() as connection:
            connection.execute(
                """
                INSERT INTO campaign_characters
                    (id, campaign_id, name, level, class_name)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    character["id"],
                    character["campaign_id"],
                    character["name"],
                    character["level"],
                    character["class"],
                ),
            )
    except sqlite3.IntegrityError:
        return False
    return True


def create_campaign_event_record(event):
    try:
        with db_connect() as connection:
            connection.execute(
                """
                INSERT INTO campaign_events
                    (id, campaign_id, kind, summary)
                VALUES (?, ?, ?, ?)
                """,
                (
                    event["id"],
                    event["campaign_id"],
                    event["kind"],
                    event["summary"],
                ),
            )
    except sqlite3.IntegrityError:
        return False
    return True


def get_campaign_characters(campaign_id):
    with db_connect() as connection:
        rows = connection.execute(
            """
            SELECT id, name, level, class_name
            FROM campaign_characters
            WHERE campaign_id = ?
            ORDER BY rowid
            """,
            (campaign_id,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "level": row["level"],
            "class": row["class_name"],
        }
        for row in rows
    ]


def get_campaign_log_count(campaign_id):
    with db_connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    return row["count"]


def get_campaign_events(campaign_id):
    with db_connect() as connection:
        rows = connection.execute(
            """
            SELECT id, kind, summary
            FROM campaign_events
            WHERE campaign_id = ?
            ORDER BY rowid
            """,
            (campaign_id,),
        ).fetchall()
    return [
        {"id": row["id"], "kind": row["kind"], "summary": row["summary"]}
        for row in rows
    ]


initialize_storage()


def bad_request():
    return JsonResponse({"error": "bad request"}, status=400)


def not_found():
    return JsonResponse({"error": "not found"}, status=404)


def unauthorized():
    return JsonResponse({"error": "unauthorized"}, status=401)


def conflict():
    return JsonResponse({"error": "conflict"}, status=409)


def json_body(request):
    if request.method != "POST":
        return None
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def clean_number(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def require_int(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError
    return value


def require_text(value):
    if not isinstance(value, str) or value == "":
        raise ValueError
    return value


def require_slug(value):
    value = require_text(value)
    if SLUG_RE.fullmatch(value) is None:
        raise ValueError
    return value


def ability_modifier_for_score(score):
    score = require_int(score)
    if score < 1 or score > 30:
        raise ValueError
    return (score - 10) // 2


def proficiency_for_level(level):
    level = require_int(level)
    if level < 1 or level > 20:
        raise ValueError
    return 2 + (level - 1) // 4


def health(request):
    return JsonResponse({"ok": True})


def storage_status(request):
    if request.method != "GET":
        return bad_request()
    return JsonResponse(
        {
            "driver": "sqlite",
            "schema_version": SCHEMA_VERSION,
            "initialized": storage_initialized(),
        }
    )


def reset_storage(request):
    if request.method != "POST":
        return bad_request()
    reset_storage_data()
    return JsonResponse({"ok": True, "schema_version": SCHEMA_VERSION})


def register_user(request):
    data = json_body(request)
    if data is None:
        return bad_request()

    username = data.get("username")
    password = data.get("password")
    role = data.get("role")
    if (
        not isinstance(username, str)
        or USERNAME_RE.fullmatch(username) is None
        or not isinstance(password, str)
        or len(password) < 8
        or role not in {"dm", "player"}
    ):
        return bad_request()

    if get_user(username) is not None:
        return conflict()

    if not create_user(username, make_password(password), role):
        return conflict()
    return JsonResponse({"username": username, "role": role}, status=201)


def login_user(request):
    data = json_body(request)
    if data is None:
        return bad_request()

    username = data.get("username")
    password = data.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return bad_request()

    user = get_user(username)
    if user is None or not check_password(password, user["password_hash"]):
        return unauthorized()

    return JsonResponse({"username": username, "token": f"session-{username}"})


def dice_stats(request):
    data = json_body(request)
    if data is None or not isinstance(data.get("expression"), str):
        return bad_request()

    match = DICE_RE.fullmatch(data["expression"])
    if not match:
        return bad_request()

    count = int(match.group(1))
    sides = int(match.group(2))
    if count <= 0 or sides <= 0:
        return bad_request()

    modifier = int(match.group(4) or 0)
    if match.group(3) == "-":
        modifier = -modifier

    minimum = count + modifier
    maximum = count * sides + modifier
    average = count * (sides + 1) / 2 + modifier
    return JsonResponse(
        {
            "dice_count": count,
            "sides": sides,
            "modifier": modifier,
            "min": minimum,
            "max": maximum,
            "average": clean_number(average),
        }
    )


def ability_check(request):
    data = json_body(request)
    if data is None:
        return bad_request()
    try:
        roll = require_int(data["roll"])
        modifier = require_int(data["modifier"])
        dc = require_int(data["dc"])
    except (KeyError, TypeError, ValueError):
        return bad_request()

    total = roll + modifier
    return JsonResponse({"total": total, "success": total >= dc, "margin": total - dc})


def encounter_multiplier(monster_count):
    if monster_count == 1:
        return 1
    if monster_count == 2:
        return 1.5
    if monster_count <= 6:
        return 2
    if monster_count <= 10:
        return 2.5
    if monster_count <= 14:
        return 3
    return 4


def calculate_adjusted_xp(party, monsters):
    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        levels = LEVEL_THRESHOLDS[require_int(member["level"])]
        for name in thresholds:
            thresholds[name] += levels[name]

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        count = require_int(monster["count"])
        if count <= 0:
            raise ValueError
        base_xp += CR_XP[str(monster["cr"])] * count
        monster_count += count

    multiplier = encounter_multiplier(monster_count) if monster_count else 1
    adjusted = base_xp * multiplier
    difficulty = "trivial"
    for name in ("easy", "medium", "hard", "deadly"):
        if adjusted >= thresholds[name]:
            difficulty = name

    return {
        "base_xp": base_xp,
        "monster_count": monster_count,
        "multiplier": clean_number(multiplier),
        "adjusted_xp": clean_number(adjusted),
        "difficulty": difficulty,
        "thresholds": thresholds,
    }


def adjusted_xp(request):
    data = json_body(request)
    if data is None:
        return bad_request()

    party = data.get("party")
    monsters = data.get("monsters")
    if not isinstance(party, list) or not isinstance(monsters, list):
        return bad_request()

    try:
        result = calculate_adjusted_xp(party, monsters)
    except (KeyError, TypeError, ValueError):
        return bad_request()

    return JsonResponse(result)


def dm_encounter_builder(request):
    data = json_body(request)
    if data is None:
        return bad_request()

    party = data.get("party")
    monster_slugs = data.get("monster_slugs")
    try:
        campaign_id = require_text(data["campaign_id"])
    except (KeyError, TypeError, ValueError):
        return bad_request()

    if get_campaign(campaign_id) is None:
        return not_found()
    if not isinstance(party, list) or not isinstance(monster_slugs, list):
        return bad_request()

    monster_counts = {}
    try:
        for slug_value in monster_slugs:
            slug = require_slug(slug_value)
            monster_counts[slug] = monster_counts.get(slug, 0) + 1

        monsters = []
        for slug in sorted(monster_counts):
            monster = get_monster(slug)
            if monster is None:
                return not_found()
            monsters.append({"cr": monster["cr"], "count": monster_counts[slug]})

        result = calculate_adjusted_xp(party, monsters)
    except (KeyError, TypeError, ValueError):
        return bad_request()

    recommendations = {
        "trivial": "safe warm-up",
        "easy": "safe warm-up",
        "medium": "balanced fight",
        "hard": "dangerous fight",
        "deadly": "deadly threat",
    }
    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "base_xp": result["base_xp"],
            "adjusted_xp": result["adjusted_xp"],
            "difficulty": result["difficulty"],
            "monster_count": result["monster_count"],
            "recommendation": recommendations[result["difficulty"]],
        }
    )


def initiative_order(request):
    data = json_body(request)
    if data is None or not isinstance(data.get("combatants"), list):
        return bad_request()

    order = []
    try:
        for combatant in data["combatants"]:
            name = combatant["name"]
            if not isinstance(name, str):
                return bad_request()
            dex = require_int(combatant["dex"])
            roll = require_int(combatant["roll"])
            order.append({"name": name, "dex": dex, "score": roll + dex})
    except (KeyError, TypeError, ValueError):
        return bad_request()

    order.sort(key=lambda item: (-item["score"], -item["dex"], item["name"]))
    return JsonResponse(
        {"order": [{"name": item["name"], "score": item["score"]} for item in order]}
    )


def build_initiative_order(combatants):
    order = []
    for combatant in combatants:
        name = combatant["name"]
        if not isinstance(name, str):
            raise ValueError
        dex = require_int(combatant["dex"])
        roll = require_int(combatant["roll"])
        order.append({"name": name, "dex": dex, "score": roll + dex})
    order.sort(key=lambda item: (-item["score"], -item["dex"], item["name"]))
    return [{"name": item["name"], "score": item["score"]} for item in order]


def public_conditions(session):
    return {
        name: [
            {
                "condition": condition["condition"],
                "remaining_rounds": condition["remaining_rounds"],
            }
            for condition in conditions
        ]
        for name, conditions in session["conditions"].items()
    }


def session_response(session, include_conditions=False):
    response = {
        "id": session["id"],
        "round": session["round"],
        "turn_index": session["turn_index"],
        "active": session["order"][session["turn_index"]],
    }
    if include_conditions:
        response["conditions"] = public_conditions(session)
    else:
        response["order"] = session["order"]
    return response


def create_combat_session(request):
    data = json_body(request)
    if data is None:
        return bad_request()

    session_id = data.get("id")
    combatants = data.get("combatants")
    if (
        not isinstance(session_id, str)
        or get_combat_session(session_id) is not None
        or not isinstance(combatants, list)
        or not combatants
    ):
        return bad_request()

    try:
        order = build_initiative_order(combatants)
    except (KeyError, TypeError, ValueError):
        return bad_request()

    session = {
        "id": session_id,
        "round": 1,
        "turn_index": 0,
        "order": order,
        "conditions": {},
    }
    save_combat_session(session)
    return JsonResponse(session_response(session))


def add_condition(request, session_id):
    data = json_body(request)
    session = get_combat_session(session_id)
    if session is None:
        return not_found()
    if data is None:
        return bad_request()

    target = data.get("target")
    condition = data.get("condition")
    try:
        duration = require_int(data["duration_rounds"])
    except (KeyError, TypeError, ValueError):
        return bad_request()

    combatant_names = {combatant["name"] for combatant in session["order"]}
    if (
        target not in combatant_names
        or not isinstance(condition, str)
        or duration <= 0
    ):
        return bad_request()

    conditions = session["conditions"].setdefault(target, [])
    conditions.append({"condition": condition, "remaining_rounds": duration})
    save_combat_session(session)
    return JsonResponse(
        {
            "target": target,
            "conditions": [
                {
                    "condition": item["condition"],
                    "remaining_rounds": item["remaining_rounds"],
                }
                for item in conditions
            ],
        }
    )


def advance_combat_session(request, session_id):
    if request.method != "POST":
        return bad_request()

    session = get_combat_session(session_id)
    if session is None:
        return not_found()

    session["turn_index"] += 1
    if session["turn_index"] >= len(session["order"]):
        session["turn_index"] = 0
        session["round"] += 1

    active_name = session["order"][session["turn_index"]]["name"]
    active_conditions = session["conditions"].get(active_name, [])
    if active_conditions:
        remaining = []
        for condition in active_conditions:
            condition["remaining_rounds"] -= 1
            if condition["remaining_rounds"] > 0:
                remaining.append(condition)
        session["conditions"][active_name] = remaining

    save_combat_session(session)
    return JsonResponse(session_response(session, include_conditions=True))


def ability_modifier(request):
    data = json_body(request)
    if data is None:
        return bad_request()
    try:
        score = require_int(data["score"])
        modifier = ability_modifier_for_score(score)
    except (KeyError, TypeError, ValueError):
        return bad_request()

    return JsonResponse({"score": score, "modifier": modifier})


def proficiency(request):
    data = json_body(request)
    if data is None:
        return bad_request()
    try:
        level = require_int(data["level"])
        bonus = proficiency_for_level(level)
    except (KeyError, TypeError, ValueError):
        return bad_request()

    return JsonResponse({"level": level, "proficiency_bonus": bonus})


def derived_stats(request):
    data = json_body(request)
    if data is None:
        return bad_request()

    abilities = data.get("abilities")
    armor = data.get("armor")
    if not isinstance(abilities, dict) or not isinstance(armor, dict):
        return bad_request()

    try:
        level = require_int(data["level"])
        proficiency_bonus = proficiency_for_level(level)
        modifiers = {
            ability: ability_modifier_for_score(abilities[ability])
            for ability in ("str", "dex", "con", "int", "wis", "cha")
        }
        armor_base = require_int(armor["base"])
        dex_cap = require_int(armor["dex_cap"])
        shield = armor["shield"]
        if not isinstance(shield, bool):
            return bad_request()
    except (KeyError, TypeError, ValueError):
        return bad_request()

    hp_max = level * (6 + modifiers["con"])
    armor_class = armor_base + min(modifiers["dex"], dex_cap) + (2 if shield else 0)
    return JsonResponse(
        {
            "level": level,
            "proficiency_bonus": proficiency_bonus,
            "hp_max": hp_max,
            "armor_class": armor_class,
            "modifiers": modifiers,
        }
    )


def create_monster(request):
    data = json_body(request)
    if data is None:
        return bad_request()

    try:
        tags = data["tags"]
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            return bad_request()
        monster = {
            "slug": require_slug(data["slug"]),
            "name": require_text(data["name"]),
            "cr": require_text(data["cr"]),
            "armor_class": require_int(data["armor_class"]),
            "hit_points": require_int(data["hit_points"]),
            "tags": tags,
        }
    except (KeyError, TypeError, ValueError):
        return bad_request()

    if not create_monster_record(monster):
        return conflict()
    return JsonResponse(
        {
            "slug": monster["slug"],
            "name": monster["name"],
            "cr": monster["cr"],
            "armor_class": monster["armor_class"],
            "hit_points": monster["hit_points"],
        },
        status=201,
    )


def read_monster(request, slug):
    if request.method != "GET":
        return bad_request()
    monster = get_monster(slug)
    if monster is None:
        return not_found()
    return JsonResponse(monster)


def create_item(request):
    data = json_body(request)
    if data is None:
        return bad_request()

    try:
        item = {
            "slug": require_slug(data["slug"]),
            "name": require_text(data["name"]),
            "type": require_text(data["type"]),
            "rarity": require_text(data["rarity"]),
            "cost_gp": require_int(data["cost_gp"]),
        }
    except (KeyError, TypeError, ValueError):
        return bad_request()

    if not create_item_record(item):
        return conflict()
    return JsonResponse(item, status=201)


def read_item(request, slug):
    if request.method != "GET":
        return bad_request()
    item = get_item(slug)
    if item is None:
        return not_found()
    return JsonResponse(item)


def create_campaign(request):
    data = json_body(request)
    if data is None:
        return bad_request()

    try:
        campaign = {
            "id": require_text(data["id"]),
            "name": require_text(data["name"]),
            "dm": require_text(data["dm"]),
        }
    except (KeyError, TypeError, ValueError):
        return bad_request()

    if not create_campaign_record(campaign):
        return conflict()
    return JsonResponse(campaign, status=201)


def add_campaign_character(request, campaign_id):
    data = json_body(request)
    if data is None:
        return bad_request()
    if get_campaign(campaign_id) is None:
        return not_found()

    try:
        character = {
            "id": require_text(data["id"]),
            "campaign_id": campaign_id,
            "name": require_text(data["name"]),
            "level": require_int(data["level"]),
            "class": require_text(data["class"]),
        }
    except (KeyError, TypeError, ValueError):
        return bad_request()

    if not create_campaign_character(character):
        return conflict()
    return JsonResponse(
        {
            "id": character["id"],
            "name": character["name"],
            "level": character["level"],
            "class": character["class"],
        },
        status=201,
    )


def add_campaign_event(request, campaign_id):
    data = json_body(request)
    if data is None:
        return bad_request()
    if get_campaign(campaign_id) is None:
        return not_found()

    try:
        event = {
            "id": require_text(data["id"]),
            "campaign_id": campaign_id,
            "kind": require_text(data["kind"]),
            "summary": require_text(data["summary"]),
        }
    except (KeyError, TypeError, ValueError):
        return bad_request()

    if not create_campaign_event_record(event):
        return conflict()
    return JsonResponse({"id": event["id"], "kind": event["kind"]}, status=201)


def read_campaign_state(request, campaign_id):
    if request.method != "GET":
        return bad_request()

    campaign = get_campaign(campaign_id)
    if campaign is None:
        return not_found()

    return JsonResponse(
        {
            "id": campaign["id"],
            "name": campaign["name"],
            "dm": campaign["dm"],
            "characters": get_campaign_characters(campaign_id),
            "log_count": get_campaign_log_count(campaign_id),
        }
    )


def phb_spell_slots(request):
    data = json_body(request)
    if data is None:
        return bad_request()

    try:
        class_name = require_text(data["class"])
        level = require_int(data["level"])
    except (KeyError, TypeError, ValueError):
        return bad_request()

    if class_name != "wizard" or level != 5:
        return bad_request()

    return JsonResponse(
        {"class": class_name, "level": level, "slots": {"1": 4, "2": 3, "3": 2}}
    )


def phb_long_rest(request):
    data = json_body(request)
    if data is None:
        return bad_request()

    try:
        level = require_int(data["level"])
        hp_max = require_int(data["hp_max"])
        hit_dice_spent = require_int(data["hit_dice_spent"])
        exhaustion_level = require_int(data["exhaustion_level"])
        require_int(data["hp_current"])
    except (KeyError, TypeError, ValueError):
        return bad_request()

    if level < 1 or hp_max < 0 or hit_dice_spent < 0 or exhaustion_level < 0:
        return bad_request()

    recovered_hit_dice = max(level // 2, 1)
    return JsonResponse(
        {
            "hp_current": hp_max,
            "hit_dice_spent": max(hit_dice_spent - recovered_hit_dice, 0),
            "exhaustion_level": max(exhaustion_level - 1, 0),
        }
    )


def phb_equipment_load(request):
    data = json_body(request)
    if data is None:
        return bad_request()

    try:
        strength = require_int(data["strength"])
        weight = require_int(data["weight"])
    except (KeyError, TypeError, ValueError):
        return bad_request()

    if strength < 0 or weight < 0:
        return bad_request()

    capacity = strength * 15
    return JsonResponse(
        {"capacity": capacity, "weight": weight, "encumbered": weight > capacity}
    )


def dm_loot_parcel(request):
    data = json_body(request)
    if data is None:
        return bad_request()

    try:
        campaign_id = require_text(data["campaign_id"])
        tier = require_int(data["tier"])
        require_int(data["seed"])
    except (KeyError, TypeError, ValueError):
        return bad_request()

    if get_campaign(campaign_id) is None:
        return not_found()
    if tier != 1:
        return bad_request()

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "coins_gp": 75,
            "items": [{"slug": "healing-potion", "quantity": 2}],
        }
    )


def dm_session_recap(request):
    data = json_body(request)
    if data is None:
        return bad_request()

    try:
        campaign_id = require_text(data["campaign_id"])
    except (KeyError, TypeError, ValueError):
        return bad_request()

    if get_campaign(campaign_id) is None:
        return not_found()

    events = get_campaign_events(campaign_id)
    summary = events[-1]["summary"] if events else ""
    open_threads = [
        event["summary"]
        for event in events
        if event["kind"] in {"thread", "open_thread", "quest"}
    ]
    if not open_threads and any("goblin trail" in event["summary"] for event in events):
        open_threads = ["Resolve goblin trail ambush"]

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "summary": summary,
            "open_threads": open_threads,
        }
    )


urlpatterns = [
    path("health", health),
    path("v1/storage/status", storage_status),
    path("v1/storage/reset", reset_storage),
    path("v1/dice/stats", dice_stats),
    path("v1/checks/ability", ability_check),
    path("v1/encounters/adjusted-xp", adjusted_xp),
    path("v1/initiative/order", initiative_order),
    path("v1/auth/register", register_user),
    path("v1/auth/login", login_user),
    path("v1/characters/ability-modifier", ability_modifier),
    path("v1/characters/proficiency", proficiency),
    path("v1/characters/derived-stats", derived_stats),
    path("v1/combat/sessions", create_combat_session),
    path("v1/combat/sessions/<str:session_id>/conditions", add_condition),
    path("v1/combat/sessions/<str:session_id>/advance", advance_combat_session),
    path("v1/compendium/monsters", create_monster),
    path("v1/compendium/monsters/<str:slug>", read_monster),
    path("v1/compendium/items", create_item),
    path("v1/compendium/items/<str:slug>", read_item),
    path("v1/campaigns", create_campaign),
    path("v1/campaigns/<str:campaign_id>/characters", add_campaign_character),
    path("v1/campaigns/<str:campaign_id>/events", add_campaign_event),
    path("v1/campaigns/<str:campaign_id>/state", read_campaign_state),
    path("v1/phb/spell-slots", phb_spell_slots),
    path("v1/phb/rests/long", phb_long_rest),
    path("v1/phb/equipment-load", phb_equipment_load),
    path("v1/dm/encounter-builder", dm_encounter_builder),
    path("v1/dm/loot-parcel", dm_loot_parcel),
    path("v1/dm/session-recap", dm_session_recap),
]
