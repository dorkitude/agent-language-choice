/**
 * Campaign-scoped deterministic fixture seeding: only the campaign DM may
 * seed the canonical fixture; any campaign member (including the DM) may
 * read the seeded state.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign, requireParticipant } from './shared.ts';

const CANONICAL_FIXTURE_ID = 'canonical-v1';

const CANONICAL_FIXTURE_STATE = {
  fixture_id: CANONICAL_FIXTURE_ID,
  status: 'seeded',
  characters: [
    { character_id: 'fixture-hero', name: 'Ari', class: 'fighter' },
    { character_id: 'fixture-mage', name: 'Bea', class: 'wizard' },
  ],
  story: 'The lantern is lit.',
  event_ids: ['fixture-event-1', 'fixture-event-2'],
} as const;

export function seedFixture(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may seed fixture state' } };
  }

  const fixtureId = body?.fixture_id;
  if (typeof fixtureId !== 'string' || fixtureId.length === 0 || fixtureId !== CANONICAL_FIXTURE_ID) {
    return { status: 400, body: { error: "fixture_id must be exactly 'canonical-v1'" } };
  }

  const existing = db
    .prepare('SELECT fixture_id FROM play_campaign_fixture_seeds WHERE campaign_id = ? AND fixture_id = ?')
    .get(campaignId, fixtureId);

  if (!existing) {
    db.prepare('INSERT INTO play_campaign_fixture_seeds (campaign_id, fixture_id) VALUES (?, ?)').run(
      campaignId,
      fixtureId,
    );
    return { status: 201, body: CANONICAL_FIXTURE_STATE as unknown as JsonValue };
  }

  return { status: 200, body: CANONICAL_FIXTURE_STATE as unknown as JsonValue };
}

export function getFixtureState(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const existing = db
    .prepare('SELECT fixture_id FROM play_campaign_fixture_seeds WHERE campaign_id = ? AND fixture_id = ?')
    .get(campaignId, CANONICAL_FIXTURE_ID);
  if (!existing) {
    return { status: 404, body: { error: 'fixture not seeded for this campaign' } };
  }

  return { status: 200, body: CANONICAL_FIXTURE_STATE as unknown as JsonValue };
}
