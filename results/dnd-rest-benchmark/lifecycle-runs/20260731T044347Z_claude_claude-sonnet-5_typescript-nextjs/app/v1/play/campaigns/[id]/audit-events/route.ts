import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../http.js";
import {
  createPlayAuditEntry,
  getNextPlayAuditTimestamp,
  getPlayMemberForUser,
  hasPlayAuditEntryForCorrelationId,
  listPlayAuditEntries,
  PlayAuditEntry,
} from "../../../store.js";

function serializeAuditEntry(entry: PlayAuditEntry) {
  return {
    kind: entry.kind,
    actor: entry.actor,
    role: entry.role,
    timestamp: entry.timestamp,
    correlation_id: entry.correlation_id,
  };
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const isDm = username === campaign.owner;
  const isMember = isDm || getPlayMemberForUser(campaignId, username) !== undefined;
  if (!isMember) {
    return Response.json(
      { error: `${username} is not a member of campaign ${campaignId}` },
      { status: 403 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { kind?: unknown; correlation_id?: unknown };

  const validKind = requireNonEmptyString(body.kind, "kind");
  if (validKind instanceof Response) return validKind;

  const validCorrelationId = requireNonEmptyString(body.correlation_id, "correlation_id");
  if (validCorrelationId instanceof Response) return validCorrelationId;

  if (hasPlayAuditEntryForCorrelationId(campaignId, validCorrelationId)) {
    return Response.json(
      { error: `correlation_id ${validCorrelationId} already used in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const entry: PlayAuditEntry = {
    kind: validKind,
    actor: username,
    role: isDm ? "DM" : "player",
    timestamp: getNextPlayAuditTimestamp(campaignId),
    correlation_id: validCorrelationId,
  };

  createPlayAuditEntry(campaignId, entry);

  return Response.json(serializeAuditEntry(entry), { status: 201 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the campaign owner may read the audit trail",
  );
  if (ownerCheck) return ownerCheck;

  const entries = listPlayAuditEntries(campaignId);

  return Response.json({ entries: entries.map(serializeAuditEntry) }, { status: 200 });
}
