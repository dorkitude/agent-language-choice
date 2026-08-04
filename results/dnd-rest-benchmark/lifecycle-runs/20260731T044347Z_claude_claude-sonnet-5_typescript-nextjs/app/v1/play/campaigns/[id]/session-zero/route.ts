import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody } from "../../../../http.js";
import { PlaySessionZero, hasPlayMemberForUser, updatePlayCampaign } from "../../../store.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../http.js";

function parseSessionZero(body: unknown): PlaySessionZero | Response {
  const { rules, tone, consent } = (body ?? {}) as {
    rules?: unknown;
    tone?: unknown;
    consent?: unknown;
  };

  if (typeof rules !== "string" || rules.length === 0) {
    return Response.json({ error: "rules must be a non-empty string" }, { status: 400 });
  }

  if (typeof tone !== "string" || tone.length === 0) {
    return Response.json({ error: "tone must be a non-empty string" }, { status: 400 });
  }

  if (!Array.isArray(consent) || consent.length === 0) {
    return Response.json({ error: "consent must be a non-empty array" }, { status: 400 });
  }

  if (!consent.every((item): item is string => typeof item === "string" && item.length > 0)) {
    return Response.json({ error: "consent must contain only non-empty strings" }, { status: 400 });
  }

  if (new Set(consent).size !== consent.length) {
    return Response.json({ error: "consent must contain unique entries" }, { status: 400 });
  }

  return { rules, tone, consent };
}

export async function PUT(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the owning dm may set session-zero settings",
  );
  if (ownerCheck) return ownerCheck;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;

  const sessionZero = parseSessionZero(parsed.body);
  if (sessionZero instanceof Response) return sessionZero;

  if (campaign.status !== "lobby") {
    return Response.json(
      { error: `play campaign ${campaignId} session-zero settings can only change in lobby` },
      { status: 409 },
    );
  }

  updatePlayCampaign({ ...campaign, session_zero: sessionZero });

  return Response.json(sessionZero, { status: 200 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const isMember =
    session.user.username === campaign.owner || hasPlayMemberForUser(campaignId, session.user.username);
  if (!isMember) {
    return Response.json(
      { error: `${session.user.username} is not a member of campaign ${campaignId}` },
      { status: 403 },
    );
  }

  if (!campaign.session_zero) {
    return Response.json(
      { error: `play campaign ${campaignId} has no session-zero settings` },
      { status: 404 },
    );
  }

  return Response.json(campaign.session_zero, { status: 200 });
}
