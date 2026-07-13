import { NextResponse } from "next/server";
import { getCampaign, hasCharacter, insertCharacter } from "../../store";

export async function POST(
  req: Request,
  ctx: { params: Promise<{ id: string }> }
) {
  const { id: campaignId } = await ctx.params;

  if (!getCampaign(campaignId)) {
    return NextResponse.json({ error: "unknown campaign" }, { status: 404 });
  }

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
  const id = obj.id;
  const name = obj.name;
  const level = obj.level;
  const klass = obj.class;

  if (typeof id !== "string" || id.length === 0) {
    return NextResponse.json({ error: "invalid id" }, { status: 400 });
  }
  if (typeof name !== "string" || name.length === 0) {
    return NextResponse.json({ error: "invalid name" }, { status: 400 });
  }
  if (typeof level !== "number" || !Number.isInteger(level)) {
    return NextResponse.json({ error: "invalid level" }, { status: 400 });
  }
  if (typeof klass !== "string" || klass.length === 0) {
    return NextResponse.json({ error: "invalid class" }, { status: 400 });
  }

  if (hasCharacter(campaignId, id)) {
    return NextResponse.json({ error: "duplicate id" }, { status: 409 });
  }

  insertCharacter(campaignId, { id, name, level, class: klass });
  return NextResponse.json({ id, name, level, class: klass }, { status: 201 });
}
