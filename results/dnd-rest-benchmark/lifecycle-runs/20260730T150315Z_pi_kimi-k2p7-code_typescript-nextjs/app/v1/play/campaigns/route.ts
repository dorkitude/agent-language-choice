import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../lib/auth.js";
import { badRequest, conflict, parseJsonBody } from "../../../lib/http.js";
import { createPlayCampaign, getPlayCampaign } from "../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (
    typeof b.id !== "string" ||
    typeof b.name !== "string" ||
    typeof b.max_players !== "number"
  ) {
    return badRequest();
  }

  if (getPlayCampaign(b.id)) {
    return conflict();
  }

  const result = createPlayCampaign({
    id: b.id,
    name: b.name,
    owner: auth.user.username,
    max_players: b.max_players,
  });
  if (!result) {
    return conflict();
  }

  return NextResponse.json(result, { status: 201 });
}
