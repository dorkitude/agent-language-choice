// Persistent combat sessions: initiative order, turn advancement, and
// conditions. Session state is stored as a single JSON blob per row
// (`combat_order`) rather than normalized tables, since it's always read
// and written as a whole per request.
import type { ServerResponse } from "node:http";
import { db } from "../db.js";
import { sendJson } from "../http.js";
import { isPlainObject, isValidInt } from "../validation.js";
import { compareInitiative } from "../domain/rules.js";

interface Condition {
  condition: string;
  remaining_rounds: number;
}

interface CombatCombatant {
  name: string;
  dex: number;
  score: number;
  conditions: Condition[];
}

interface CombatSession {
  id: string;
  round: number;
  turn_index: number;
  order: CombatCombatant[];
}

function getCombatSession(id: string): CombatSession | undefined {
  const row = db
    .prepare("SELECT id, round, turn_index, combat_order FROM combat_sessions WHERE id = ?")
    .get(id) as { id: string; round: number; turn_index: number; combat_order: string } | undefined;
  if (!row) return undefined;
  return {
    id: row.id,
    round: row.round,
    turn_index: row.turn_index,
    order: JSON.parse(row.combat_order) as CombatCombatant[],
  };
}

function saveCombatSession(session: CombatSession): void {
  db.prepare(
    `INSERT INTO combat_sessions (id, round, turn_index, combat_order) VALUES (?, ?, ?, ?)
     ON CONFLICT(id) DO UPDATE SET round = excluded.round, turn_index = excluded.turn_index, combat_order = excluded.combat_order`,
  ).run(session.id, session.round, session.turn_index, JSON.stringify(session.order));
}

function hasCombatSession(id: string): boolean {
  const row = db.prepare("SELECT 1 FROM combat_sessions WHERE id = ?").get(id);
  return row !== undefined;
}

function activeSummary(session: CombatSession): { name: string; score: number } {
  const active = session.order[session.turn_index];
  return { name: active.name, score: active.score };
}

function sessionCreateResponse(session: CombatSession) {
  return {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: activeSummary(session),
    order: session.order.map(({ name, score }) => ({ name, score })),
  };
}

export function handleCreateCombatSession(res: ServerResponse, body: unknown): void {
  if (
    !isPlainObject(body) ||
    typeof body.id !== "string" ||
    !body.id ||
    !Array.isArray(body.combatants) ||
    body.combatants.length === 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (hasCombatSession(body.id)) {
    sendJson(res, 400, { error: "session already exists" });
    return;
  }

  const combatants = body.combatants as unknown[];
  const scored: CombatCombatant[] = [];
  for (const combatant of combatants) {
    if (
      !isPlainObject(combatant) ||
      typeof combatant.name !== "string" ||
      typeof combatant.dex !== "number" ||
      typeof combatant.roll !== "number"
    ) {
      sendJson(res, 400, { error: "invalid combatant" });
      return;
    }
    scored.push({
      name: combatant.name,
      dex: combatant.dex,
      score: combatant.roll + combatant.dex,
      conditions: [],
    });
  }

  scored.sort(compareInitiative);

  const session: CombatSession = {
    id: body.id,
    round: 1,
    turn_index: 0,
    order: scored,
  };

  saveCombatSession(session);
  sendJson(res, 200, sessionCreateResponse(session));
}

export function handleAddCondition(res: ServerResponse, sessionId: string, body: unknown): void {
  const session = getCombatSession(sessionId);
  if (!session) {
    sendJson(res, 404, { error: "session not found" });
    return;
  }

  if (
    !isPlainObject(body) ||
    typeof body.target !== "string" ||
    typeof body.condition !== "string" ||
    !isValidInt(body.duration_rounds, 1, Number.MAX_SAFE_INTEGER)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const target = session.order.find((c) => c.name === body.target);
  if (!target) {
    sendJson(res, 400, { error: "unknown target" });
    return;
  }

  target.conditions.push({ condition: body.condition, remaining_rounds: body.duration_rounds });

  saveCombatSession(session);

  sendJson(res, 200, {
    target: target.name,
    conditions: target.conditions.map(({ condition, remaining_rounds }) => ({ condition, remaining_rounds })),
  });
}

export function handleAdvanceTurn(res: ServerResponse, sessionId: string): void {
  const session = getCombatSession(sessionId);
  if (!session) {
    sendJson(res, 404, { error: "session not found" });
    return;
  }

  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }

  const active = session.order[session.turn_index];
  const activeHadConditions = active.conditions.length > 0;
  active.conditions = active.conditions
    .map((c) => ({ ...c, remaining_rounds: c.remaining_rounds - 1 }))
    .filter((c) => c.remaining_rounds > 0);

  const conditions: Record<string, Condition[]> = {};
  for (const combatant of session.order) {
    if (combatant.conditions.length > 0 || (combatant === active && activeHadConditions)) {
      conditions[combatant.name] = combatant.conditions.map(({ condition, remaining_rounds }) => ({
        condition,
        remaining_rounds,
      }));
    }
  }

  saveCombatSession(session);

  sendJson(res, 200, {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: activeSummary(session),
    conditions,
  });
}
