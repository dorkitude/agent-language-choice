/**
 * Campaign-scoped safe turn submission. Each campaign tracks a single
 * `current_turn` counter starting at 1. A submission is only accepted when
 * its `expected_turn` matches the current counter, which is what makes
 * concurrent/racing submissions for a stale turn safe to reject without
 * mutating queue state.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign, isMember } from './shared.ts';

interface SafeTurnStateRow {
  current_turn: number;
}

interface SafeTurnSubmissionRow {
  sequence: number;
  submission_id: string;
  action: string;
  accepted_turn: number;
  next_turn: number;
}

function getOrInitState(db: ReturnType<typeof getDb>, campaignId: string): number {
  const row = db
    .prepare('SELECT current_turn FROM play_campaign_safe_turns WHERE campaign_id = ?')
    .get(campaignId) as SafeTurnStateRow | undefined;
  if (row) return row.current_turn;

  db.prepare('INSERT INTO play_campaign_safe_turns (campaign_id, current_turn) VALUES (?, 1)').run(campaignId);
  return 1;
}

function toSubmissionBody(row: SafeTurnSubmissionRow): JsonValue {
  return {
    submission_id: row.submission_id,
    action: row.action,
    accepted_turn: row.accepted_turn,
    next_turn: row.next_turn,
  } as unknown as JsonValue;
}

export function submitSafeTurn(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const isOwner = actor.username === campaign.owner;
  if (!isOwner && !isMember(db, campaignId, actor.username)) {
    return { status: 403, body: { error: 'only campaign members may submit safe turns' } };
  }

  const submissionId = body.submission_id;
  if (typeof submissionId !== 'string' || submissionId.length === 0) {
    return { status: 400, body: { error: 'submission_id must be a non-empty string' } };
  }

  const action = body.action;
  if (typeof action !== 'string' || action.length === 0) {
    return { status: 400, body: { error: 'action must be a non-empty string' } };
  }

  const expectedTurn = body.expected_turn;
  if (typeof expectedTurn !== 'number' || !Number.isInteger(expectedTurn) || expectedTurn <= 0) {
    return { status: 400, body: { error: 'expected_turn must be a positive integer' } };
  }

  const currentTurn = getOrInitState(db, campaignId);

  const existingSubmission = db
    .prepare('SELECT sequence FROM play_campaign_safe_turn_submissions WHERE campaign_id = ? AND submission_id = ?')
    .get(campaignId, submissionId);
  if (existingSubmission) {
    return { status: 409, body: { error: 'submission_id already used in this campaign' } };
  }

  if (expectedTurn !== currentTurn) {
    return { status: 409, body: { current_turn: currentTurn } as unknown as JsonValue };
  }

  const nextTurn = currentTurn + 1;
  const sequenceRow = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_safe_turn_submissions WHERE campaign_id = ?')
    .get(campaignId) as { max_sequence: number };
  const sequence = sequenceRow.max_sequence + 1;

  db.prepare(
    'INSERT INTO play_campaign_safe_turn_submissions (campaign_id, sequence, submission_id, action, accepted_turn, next_turn) VALUES (?, ?, ?, ?, ?, ?)',
  ).run(campaignId, sequence, submissionId, action, currentTurn, nextTurn);

  db.prepare('UPDATE play_campaign_safe_turns SET current_turn = ? WHERE campaign_id = ?').run(nextTurn, campaignId);

  return {
    status: 201,
    body: { submission_id: submissionId, action, accepted_turn: currentTurn, next_turn: nextTurn } as unknown as JsonValue,
  };
}

export function getSafeTurns(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const isOwner = actor.username === campaign.owner;
  if (!isOwner && !isMember(db, campaignId, actor.username)) {
    return { status: 403, body: { error: 'only the campaign DM or members may read safe turns' } };
  }

  const currentTurn = getOrInitState(db, campaignId);

  const rows = db
    .prepare(
      'SELECT sequence, submission_id, action, accepted_turn, next_turn FROM play_campaign_safe_turn_submissions WHERE campaign_id = ? ORDER BY sequence ASC',
    )
    .all(campaignId) as unknown as SafeTurnSubmissionRow[];

  return {
    status: 200,
    body: { current_turn: currentTurn, accepted: rows.map(toSubmissionBody) } as unknown as JsonValue,
  };
}
