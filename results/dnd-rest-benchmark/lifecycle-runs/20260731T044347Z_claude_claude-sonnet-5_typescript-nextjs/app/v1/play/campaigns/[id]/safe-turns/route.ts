import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requirePlayCampaign } from "../../../http.js";
import {
  acceptPlaySafeTurn,
  getPlayMemberForUser,
  getPlaySafeTurnBySubmissionId,
  getPlaySafeTurnCurrentTurn,
  listPlaySafeTurns,
  PlaySafeTurn,
} from "../../../store.js";

function serializeSafeTurn(turn: PlaySafeTurn) {
  return {
    submission_id: turn.submission_id,
    action: turn.action,
    accepted_turn: turn.accepted_turn,
    next_turn: turn.next_turn,
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
  const body = parsed.body as { submission_id?: unknown; expected_turn?: unknown; action?: unknown };

  const validSubmissionId = requireNonEmptyString(body.submission_id, "submission_id");
  if (validSubmissionId instanceof Response) return validSubmissionId;

  const validAction = requireNonEmptyString(body.action, "action");
  if (validAction instanceof Response) return validAction;

  if (
    typeof body.expected_turn !== "number" ||
    !Number.isInteger(body.expected_turn) ||
    body.expected_turn <= 0
  ) {
    return Response.json({ error: "expected_turn must be a positive integer" }, { status: 400 });
  }
  const expectedTurn = body.expected_turn;

  const existing = getPlaySafeTurnBySubmissionId(campaignId, validSubmissionId);
  if (existing) {
    return Response.json(
      { error: `submission_id ${validSubmissionId} was already used in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const currentTurn = getPlaySafeTurnCurrentTurn(campaignId);
  if (expectedTurn !== currentTurn) {
    return Response.json({ current_turn: currentTurn }, { status: 409 });
  }

  const turn = acceptPlaySafeTurn(campaignId, validSubmissionId, validAction);

  return Response.json(serializeSafeTurn(turn), { status: 201 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
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

  const currentTurn = getPlaySafeTurnCurrentTurn(campaignId);
  const accepted = listPlaySafeTurns(campaignId);

  return Response.json(
    { current_turn: currentTurn, accepted: accepted.map(serializeSafeTurn) },
    { status: 200 },
  );
}
