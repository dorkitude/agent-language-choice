import { NextResponse } from "next/server";
import { createItem, hasItem, SLUG_RE, type Item } from "../store";

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

  const { slug, name, type, rarity, cost_gp } = obj;

  if (typeof slug !== "string" || !SLUG_RE.test(slug)) {
    return NextResponse.json({ error: "invalid slug" }, { status: 400 });
  }
  if (typeof name !== "string" || name.length === 0) {
    return NextResponse.json({ error: "invalid name" }, { status: 400 });
  }
  if (typeof type !== "string" || type.length === 0) {
    return NextResponse.json({ error: "invalid type" }, { status: 400 });
  }
  if (typeof rarity !== "string" || rarity.length === 0) {
    return NextResponse.json({ error: "invalid rarity" }, { status: 400 });
  }
  if (!isInt(cost_gp) || cost_gp < 0) {
    return NextResponse.json({ error: "invalid cost_gp" }, { status: 400 });
  }

  if (hasItem(slug)) {
    return NextResponse.json({ error: "duplicate slug" }, { status: 409 });
  }

  const item: Item = { slug, name, type, rarity, cost_gp };
  createItem(item);

  return NextResponse.json(item, { status: 201 });
}
