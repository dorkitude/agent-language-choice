// Health check, dice math, and generic ability checks — endpoints with no
// persistence and no dependency on the rest of the domain.
import type { ServerResponse } from "node:http";
import { sendJson } from "../http.js";
import { isPlainObject } from "../validation.js";
import { isMaintenanceMode } from "../serviceMode.js";

export function handleHealth(res: ServerResponse): void {
  sendJson(res, 200, { ok: true });
}

export function handleLiveness(res: ServerResponse): void {
  sendJson(res, 200, { status: "ok" });
}

export function handleReadiness(res: ServerResponse): void {
  if (isMaintenanceMode()) {
    sendJson(res, 503, { status: "maintenance", schema_version: 2 });
    return;
  }
  sendJson(res, 200, { status: "ready", schema_version: 2 });
}

const DICE_EXPRESSION_RE = /^(\d+)d(\d+)(?:([+-])(\d+))?$/;

export function handleDiceStats(res: ServerResponse, body: unknown): void {
  if (!isPlainObject(body) || typeof body.expression !== "string") {
    sendJson(res, 400, { error: "invalid expression" });
    return;
  }

  const match = DICE_EXPRESSION_RE.exec(body.expression.trim());
  if (!match) {
    sendJson(res, 400, { error: "invalid expression" });
    return;
  }

  const diceCount = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const sign = match[3];
  const modifierMagnitude = match[4] !== undefined ? parseInt(match[4], 10) : 0;
  const modifier = sign === "-" ? -modifierMagnitude : modifierMagnitude;

  if (diceCount <= 0 || sides <= 0) {
    sendJson(res, 400, { error: "invalid expression" });
    return;
  }

  const min = diceCount * 1 + modifier;
  const max = diceCount * sides + modifier;
  const average = (diceCount * (sides + 1)) / 2 + modifier;

  sendJson(res, 200, {
    dice_count: diceCount,
    sides,
    modifier,
    min,
    max,
    average,
  });
}

const API_SCHEMA = {
  version: "2026-07-29",
  endpoints: [
    { method: "GET", path: "/v1/play/campaigns/{id}/rng-ledger", auth: "member" },
    { method: "GET", path: "/v1/schema", auth: "public" },
    { method: "POST", path: "/v1/play/campaigns", auth: "dm" },
    { method: "POST", path: "/v1/play/campaigns/{id}/fixture-seeds", auth: "dm" },
    { method: "POST", path: "/v1/play/campaigns/{id}/members", auth: "member" },
    { method: "POST", path: "/v1/play/campaigns/{id}/moderation/reports", auth: "member" },
    { method: "POST", path: "/v1/play/campaigns/{id}/rng-rolls", auth: "member" },
    { method: "PUT", path: "/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution", auth: "dm" },
    { method: "PUT", path: "/v1/play/campaigns/{id}/rng-seed", auth: "dm" },
    { method: "PUT", path: "/v1/play/campaigns/{id}/safety-boundaries", auth: "dm" },
  ],
} as const;

export function handleGetApiSchema(res: ServerResponse): void {
  sendJson(res, 200, API_SCHEMA);
}

export function handleAbilityCheck(res: ServerResponse, body: unknown): void {
  if (
    !isPlainObject(body) ||
    typeof body.roll !== "number" ||
    typeof body.modifier !== "number" ||
    typeof body.dc !== "number"
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const total = body.roll + body.modifier;
  const success = total >= body.dc;
  const margin = total - body.dc;

  sendJson(res, 200, { total, success, margin });
}
