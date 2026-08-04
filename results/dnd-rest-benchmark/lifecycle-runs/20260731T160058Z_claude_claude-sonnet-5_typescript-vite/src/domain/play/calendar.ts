/**
 * Deterministic campaign calendar: DM-initialized day/season counter with
 * weather derived purely from the current day and season.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign, requireParticipant } from './shared.ts';

type CalendarRow = {
  day: number;
  season: string;
};

const SEASON_OFFSETS: Record<string, number> = { spring: 0, summer: 1, autumn: 2, winter: 3 };
const WEATHER_BY_OFFSET = ['clear', 'rain', 'wind', 'snow'];

function weatherFor(day: number, season: string): string {
  const offset = (day + SEASON_OFFSETS[season]) % 4;
  return WEATHER_BY_OFFSET[offset];
}

function calendarBody(row: CalendarRow): JsonValue {
  return { day: row.day, season: row.season, weather: weatherFor(row.day, row.season) } as JsonValue;
}

function findCalendar(db: ReturnType<typeof getDb>, campaignId: string): CalendarRow | undefined {
  return db
    .prepare('SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?')
    .get(campaignId) as CalendarRow | undefined;
}

export function initCalendar(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may initialize the calendar' } };
  }

  const day = body.day;
  if (typeof day !== 'number' || !Number.isInteger(day) || day < 1) {
    return { status: 400, body: { error: 'day must be an integer greater than or equal to 1' } };
  }
  const season = body.season;
  if (typeof season !== 'string' || !(season in SEASON_OFFSETS)) {
    return { status: 400, body: { error: 'season must be one of spring, summer, autumn, winter' } };
  }

  const existing = findCalendar(db, campaignId);
  if (existing) {
    return { status: 409, body: { error: 'calendar already initialized for this campaign' } };
  }

  db.prepare('INSERT INTO play_campaign_calendars (campaign_id, day, season) VALUES (?, ?, ?)').run(
    campaignId,
    day,
    season,
  );

  return { status: 201, body: calendarBody({ day, season }) };
}

export function getCalendar(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const calendar = findCalendar(db, campaignId);
  if (!calendar) {
    return { status: 404, body: { error: 'calendar not initialized' } };
  }

  return { status: 200, body: calendarBody(calendar) };
}

export function advanceCalendar(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may advance the calendar' } };
  }

  const days = body.days;
  if (typeof days !== 'number' || !Number.isInteger(days) || days < 1 || days > 30) {
    return { status: 400, body: { error: 'days must be an integer from 1 through 30' } };
  }

  const calendar = findCalendar(db, campaignId);
  if (!calendar) {
    return { status: 404, body: { error: 'calendar not initialized' } };
  }

  const newDay = calendar.day + days;
  db.prepare('UPDATE play_campaign_calendars SET day = ? WHERE campaign_id = ?').run(newDay, campaignId);

  return { status: 200, body: calendarBody({ day: newDay, season: calendar.season }) };
}
