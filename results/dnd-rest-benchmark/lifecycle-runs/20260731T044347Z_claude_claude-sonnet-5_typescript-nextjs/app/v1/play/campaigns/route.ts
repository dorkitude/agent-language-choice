import { requireSession } from "../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../http.js";
import { createPlayCampaign, hasPlayCampaign, PlayCampaign } from "../store.js";

export async function POST(request: Request) {
  const session = requireSession(request);
  if (!session.ok) return session.response;

  if (session.user.role !== "dm") {
    return Response.json({ error: "only a dm may create a play campaign" }, { status: 403 });
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { id, name, max_players } = (body ?? {}) as {
    id?: unknown;
    name?: unknown;
    max_players?: unknown;
  };

  const validId = requireNonEmptyString(id, "id");
  if (validId instanceof Response) return validId;

  const validName = requireNonEmptyString(name, "name");
  if (validName instanceof Response) return validName;

  if (typeof max_players !== "number" || !Number.isInteger(max_players) || max_players <= 0) {
    return Response.json({ error: "max_players must be a positive integer" }, { status: 400 });
  }

  if (hasPlayCampaign(validId)) {
    return Response.json({ error: `play campaign ${validId} already exists` }, { status: 409 });
  }

  const campaign: PlayCampaign = {
    id: validId,
    name: validName,
    owner: session.user.username,
    status: "lobby",
    max_players,
  };
  createPlayCampaign(campaign);

  return Response.json(campaign, { status: 201 });
}
