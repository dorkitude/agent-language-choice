import { NextResponse } from "next/server";
import {
  createMonster,
  hasMonster,
  SLUG_RE,
  type Monster,
} from "../store";

function isInt(n: unknown): n is number {
  return typeof n === "number" && Number.isInteger(n);
}

export async function POST(req: Request) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const obj =
    typeof body === "object" && body !== null
      ? (body as Record<string, unknown>)
      : {};

  const { slug, name, cr, armor_class, hit_points, tags } = obj;

  if (typeof slug !== "string" || !SLUG_RE.test(slug)) {
    return NextResponse.json({ error: "invalid slug" }, { status: 400 });
  }
  if (typeof name !== "string" || name.length === 0) {
    return NextResponse.json({ error: "invalid name" }, { status: 400 });
  }
  if (typeof cr !== "string" || cr.length === 0) {
    return NextResponse.json({ error: "invalid cr" }, { status: 400 });
  }
  if (!isInt(armor_class)) {
    return NextResponse.json({ error: "invalid armor_class" }, { status: 400 });
  }
  if (!isInt(hit_points)) {
    return NextResponse.json({ error: "invalid hit_points" }, { status: 400 });
  }
  let tagList: string[] = [];
  if (tags !== undefined) {
    if (!Array.isArray(tags) || !tags.every((t) => typeof t === "string")) {
      return NextResponse.json({ error: "invalid tags" }, { status: 400 });
    }
    tagList = tags as string[];
  }

  if (hasMonster(slug)) {
    return NextResponse.json({ error: "duplicate slug" }, { status: 409 });
  }

  const monster: Monster = {
    slug,
    name,
    cr,
    armor_class,
    hit_points,
    tags: tagList,
  };
  createMonster(monster);

  return NextResponse.json(
    {
      slug,
      name,
      cr,
      armor_class,
      hit_points,
    },
    { status: 201 }
  );
}
