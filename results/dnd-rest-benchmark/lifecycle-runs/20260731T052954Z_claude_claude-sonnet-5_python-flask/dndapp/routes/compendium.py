"""Monster and item compendium entries."""

import json

from flask import Blueprint, jsonify, request

from ..db import get_db
from ..validation import valid_int, valid_nonempty_str, valid_slug

bp = Blueprint("compendium", __name__)


@bp.post("/v1/compendium/monsters")
def create_monster():
    data = request.get_json(silent=True) or {}
    slug = data.get("slug")
    name = data.get("name")
    cr = data.get("cr")
    armor_class = data.get("armor_class")
    hit_points = data.get("hit_points")
    tags = data.get("tags", [])

    if not valid_slug(slug):
        return jsonify(error="invalid slug"), 400
    if not valid_nonempty_str(name):
        return jsonify(error="invalid name"), 400
    if not isinstance(cr, str) or not cr.strip():
        return jsonify(error="invalid cr"), 400
    if not valid_int(armor_class):
        return jsonify(error="invalid armor_class"), 400
    if not valid_int(hit_points):
        return jsonify(error="invalid hit_points"), 400
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        return jsonify(error="invalid tags"), 400

    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT slug FROM monsters WHERE slug = ?", (slug,)
        ).fetchone()
        if existing is not None:
            return jsonify(error="slug already exists"), 409

        conn.execute(
            "INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (slug, name, cr, armor_class, hit_points, json.dumps(tags)),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        slug=slug,
        name=name,
        cr=cr,
        armor_class=armor_class,
        hit_points=hit_points,
    ), 201


@bp.get("/v1/compendium/monsters/<slug>")
def get_monster(slug):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT slug, name, cr, armor_class, hit_points, tags_json FROM monsters WHERE slug = ?",
            (slug,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return jsonify(error="monster not found"), 404

    return jsonify(
        slug=row["slug"],
        name=row["name"],
        cr=row["cr"],
        armor_class=row["armor_class"],
        hit_points=row["hit_points"],
        tags=json.loads(row["tags_json"]),
    )


@bp.post("/v1/compendium/items")
def create_item():
    data = request.get_json(silent=True) or {}
    slug = data.get("slug")
    name = data.get("name")
    item_type = data.get("type")
    rarity = data.get("rarity")
    cost_gp = data.get("cost_gp")

    if not valid_slug(slug):
        return jsonify(error="invalid slug"), 400
    if not valid_nonempty_str(name):
        return jsonify(error="invalid name"), 400
    if not valid_nonempty_str(item_type):
        return jsonify(error="invalid type"), 400
    if not valid_nonempty_str(rarity):
        return jsonify(error="invalid rarity"), 400
    if not valid_int(cost_gp) or cost_gp < 0:
        return jsonify(error="invalid cost_gp"), 400

    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT slug FROM items WHERE slug = ?", (slug,)
        ).fetchone()
        if existing is not None:
            return jsonify(error="slug already exists"), 409

        conn.execute(
            "INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)",
            (slug, name, item_type, rarity, cost_gp),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        slug=slug,
        name=name,
        type=item_type,
        rarity=rarity,
        cost_gp=cost_gp,
    ), 201


@bp.get("/v1/compendium/items/<slug>")
def get_item(slug):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?",
            (slug,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return jsonify(error="item not found"), 404

    return jsonify(
        slug=row["slug"],
        name=row["name"],
        type=row["type"],
        rarity=row["rarity"],
        cost_gp=row["cost_gp"],
    )
