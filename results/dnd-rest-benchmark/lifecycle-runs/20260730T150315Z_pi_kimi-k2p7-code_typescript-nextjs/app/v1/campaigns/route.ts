import { NextResponse } from "next/server";
import { badRequest, conflict, parseJsonBody } from "../../lib/http.js";
import { createCampaign, getCampaign } from "../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (
    typeof b.id !== "string" ||
    typeof b.name !== "string" ||
    typeof b.dm !== "string"
  ) {
    return badRequest();
  }

  if (getCampaign(b.id)) {
    return conflict();
  }

  const result = createCampaign({ id: b.id, name: b.name, dm: b.dm });
  if (!result) {
    return conflict();
  }

  return NextResponse.json(result, { status: 201 });
}
