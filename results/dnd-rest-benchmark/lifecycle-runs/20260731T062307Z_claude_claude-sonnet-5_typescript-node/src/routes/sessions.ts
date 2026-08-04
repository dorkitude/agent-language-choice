// Campaign session scheduling and attendance tracking. Persistent
// (`campaign_sessions`). "Next session" is the one with the earliest
// `starts_at` (ISO 8601 strings sort lexically in chronological order).
import type { ServerResponse } from "node:http";
import { db } from "../db.js";
import { sendJson } from "../http.js";
import { isPlainObject, isValidInt } from "../validation.js";
import { hasCampaign } from "./campaigns.js";

interface SessionRecord {
  campaignId: string;
  id: string;
  startsAt: string;
  durationMinutes: number;
  agenda: string[];
  present: string[];
  absent: string[];
}

function isIsoDateString(value: unknown): value is string {
  return typeof value === "string" && value !== "" && !Number.isNaN(Date.parse(value));
}

function hasSession(campaignId: string, id: string): boolean {
  const row = db.prepare("SELECT 1 FROM campaign_sessions WHERE campaign_id = ? AND id = ?").get(campaignId, id);
  return row !== undefined;
}

function getSession(campaignId: string, id: string): SessionRecord | undefined {
  const row = db
    .prepare(
      "SELECT campaign_id, id, starts_at, duration_minutes, agenda, present, absent FROM campaign_sessions WHERE campaign_id = ? AND id = ?",
    )
    .get(campaignId, id) as
    | {
        campaign_id: string;
        id: string;
        starts_at: string;
        duration_minutes: number;
        agenda: string;
        present: string;
        absent: string;
      }
    | undefined;
  if (!row) return undefined;
  return {
    campaignId: row.campaign_id,
    id: row.id,
    startsAt: row.starts_at,
    durationMinutes: row.duration_minutes,
    agenda: JSON.parse(row.agenda) as string[],
    present: JSON.parse(row.present) as string[],
    absent: JSON.parse(row.absent) as string[],
  };
}

function saveSession(session: SessionRecord): void {
  db.prepare(
    "INSERT INTO campaign_sessions (campaign_id, id, starts_at, duration_minutes, agenda, present, absent) VALUES (?, ?, ?, ?, ?, ?, ?)",
  ).run(
    session.campaignId,
    session.id,
    session.startsAt,
    session.durationMinutes,
    JSON.stringify(session.agenda),
    JSON.stringify(session.present),
    JSON.stringify(session.absent),
  );
}

function updateAttendance(session: SessionRecord): void {
  db.prepare("UPDATE campaign_sessions SET present = ?, absent = ? WHERE campaign_id = ? AND id = ?").run(
    JSON.stringify(session.present),
    JSON.stringify(session.absent),
    session.campaignId,
    session.id,
  );
}

function getNextSession(campaignId: string): SessionRecord | undefined {
  const row = db
    .prepare(
      "SELECT campaign_id, id, starts_at, duration_minutes, agenda, present, absent FROM campaign_sessions WHERE campaign_id = ? ORDER BY starts_at ASC LIMIT 1",
    )
    .get(campaignId) as
    | {
        campaign_id: string;
        id: string;
        starts_at: string;
        duration_minutes: number;
        agenda: string;
        present: string;
        absent: string;
      }
    | undefined;
  if (!row) return undefined;
  return {
    campaignId: row.campaign_id,
    id: row.id,
    startsAt: row.starts_at,
    durationMinutes: row.duration_minutes,
    agenda: JSON.parse(row.agenda) as string[],
    present: JSON.parse(row.present) as string[],
    absent: JSON.parse(row.absent) as string[],
  };
}

export function handleScheduleSession(res: ServerResponse, campaignId: string, body: unknown): void {
  if (!hasCampaign(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.id !== "string" ||
    !body.id ||
    !isIsoDateString(body.starts_at) ||
    !isValidInt(body.duration_minutes, 1, 24 * 60) ||
    !Array.isArray(body.agenda) ||
    !body.agenda.every((item) => typeof item === "string")
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (hasSession(campaignId, body.id)) {
    sendJson(res, 409, { error: "session already exists" });
    return;
  }

  const session: SessionRecord = {
    campaignId,
    id: body.id,
    startsAt: body.starts_at,
    durationMinutes: body.duration_minutes,
    agenda: body.agenda as string[],
    present: [],
    absent: [],
  };
  saveSession(session);

  sendJson(res, 201, {
    id: session.id,
    starts_at: session.startsAt,
    duration_minutes: session.durationMinutes,
    agenda_count: session.agenda.length,
  });
}

export function handleRecordAttendance(
  res: ServerResponse,
  campaignId: string,
  sessionId: string,
  body: unknown,
): void {
  if (!hasCampaign(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const session = getSession(campaignId, sessionId);
  if (!session) {
    sendJson(res, 404, { error: "session not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    !Array.isArray(body.present) ||
    !body.present.every((item) => typeof item === "string") ||
    !Array.isArray(body.absent) ||
    !body.absent.every((item) => typeof item === "string")
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  session.present = body.present as string[];
  session.absent = body.absent as string[];
  updateAttendance(session);

  sendJson(res, 200, {
    session_id: session.id,
    present_count: session.present.length,
    absent_count: session.absent.length,
  });
}

export function handleNextSession(res: ServerResponse, campaignId: string): void {
  if (!hasCampaign(campaignId)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const session = getNextSession(campaignId);
  if (!session) {
    sendJson(res, 404, { error: "no upcoming session" });
    return;
  }

  sendJson(res, 200, {
    id: session.id,
    starts_at: session.startsAt,
    agenda_count: session.agenda.length,
  });
}
