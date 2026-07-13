import { NextResponse } from "next/server";
import { getCampaign, insertCampaign } from "./store";

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
  const id = obj.id;
  const name = obj.name;
  const dm = obj.dm;

  if (typeof id !== "string" || id.length === 0) {
    return NextResponse.json({ error: "invalid id" }, { status: 400 });
  }
  if (typeof name !== "string" || name.length === 0) {
    return NextResponse.json({ error: "invalid name" }, { status: 400 });
  }
  if (typeof dm !== "string" || dm.length === 0) {
    return NextResponse.json({ error: "invalid dm" }, { status: 400 });
  }

  if (getCampaign(id)) {
    return NextResponse.json({ error: "duplicate id" }, { status: 409 });
  }

  insertCampaign({ id, name, dm });
  return NextResponse.json({ id, name, dm }, { status: 201 });
}
