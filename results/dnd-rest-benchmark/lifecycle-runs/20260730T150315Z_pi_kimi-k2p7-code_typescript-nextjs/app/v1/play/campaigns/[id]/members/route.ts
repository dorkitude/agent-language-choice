import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../lib/auth.js";
import { badRequest, conflict, notFound, parseJsonBody } from "../../../../../lib/http.js";
import {
  createPlayCampaignMembership,
  getPlayCampaign,
} from "../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  const auth = requireBearerAuth(req, "player");
  if (!auth.ok) return auth.response;

  if (!getPlayCampaign(id)) {
    return notFound();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (
    typeof b.character_id !== "string" ||
    typeof b.name !== "string" ||
    typeof b.class !== "string"
  ) {
    return badRequest();
  }

  const result = createPlayCampaignMembership(id, auth.user.username, {
    character_id: b.character_id,
    name: b.name,
    class: b.class,
  });
  if (!result) {
    return conflict();
  }

  return NextResponse.json(result, { status: 201 });
}
