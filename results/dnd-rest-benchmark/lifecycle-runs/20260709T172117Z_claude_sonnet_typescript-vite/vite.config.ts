import type { Plugin, ViteDevServer } from "vite";
import type { IncomingMessage, ServerResponse } from "node:http";
import {
  computeDiceStats,
  computeAbilityCheck,
  computeAdjustedXp,
  computeInitiativeOrder,
  computeAbilityModifier,
  isValidAbilityScore,
  computeProficiencyBonus,
  isValidLevel,
  computeDerivedStats,
  createCombatSession,
  activeCombatant,
  addCombatCondition,
  advanceCombatTurn,
  type Abilities,
  type Armor,
  type Combatant,
  type CombatSessionState,
} from "./src/api.js";

const combatSessions = new Map<string, CombatSessionState>();

function isValidCombatants(value: unknown): value is Combatant[] {
  return (
    Array.isArray(value) &&
    value.length > 0 &&
    value.every(
      (c) =>
        c !== null &&
        typeof c === "object" &&
        typeof (c as Combatant).name === "string" &&
        typeof (c as Combatant).dex === "number" &&
        typeof (c as Combatant).roll === "number"
    )
  );
}

function readJsonBody(req: IncomingMessage): Promise<any> {
  return new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (chunk) => {
      data += chunk;
    });
    req.on("end", () => {
      if (!data) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(data));
      } catch {
        reject(new Error("invalid json"));
      }
    });
    req.on("error", reject);
  });
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json");
  res.end(payload);
}

function dndApiPlugin(): Plugin {
  return {
    name: "dnd-rest-api",
    configureServer(server: ViteDevServer) {
      server.middlewares.use(async (req, res, next) => {
        const url = req.url ?? "";
        const path = url.split("?")[0];

        if (path === "/health" && req.method === "GET") {
          sendJson(res, 200, { ok: true });
          return;
        }

        if (path === "/v1/dice/stats" && req.method === "POST") {
          try {
            const body = await readJsonBody(req);
            if (typeof body.expression !== "string") {
              sendJson(res, 400, { error: "expression is required" });
              return;
            }
            const stats = computeDiceStats(body.expression);
            if (!stats) {
              sendJson(res, 400, { error: "invalid dice expression" });
              return;
            }
            sendJson(res, 200, stats);
          } catch {
            sendJson(res, 400, { error: "invalid request body" });
          }
          return;
        }

        if (path === "/v1/checks/ability" && req.method === "POST") {
          try {
            const body = await readJsonBody(req);
            if (
              typeof body.roll !== "number" ||
              typeof body.modifier !== "number" ||
              typeof body.dc !== "number"
            ) {
              sendJson(res, 400, { error: "roll, modifier, and dc are required" });
              return;
            }
            const result = computeAbilityCheck(body.roll, body.modifier, body.dc);
            sendJson(res, 200, result);
          } catch {
            sendJson(res, 400, { error: "invalid request body" });
          }
          return;
        }

        if (path === "/v1/encounters/adjusted-xp" && req.method === "POST") {
          try {
            const body = await readJsonBody(req);
            if (!Array.isArray(body.party) || !Array.isArray(body.monsters)) {
              sendJson(res, 400, { error: "party and monsters are required" });
              return;
            }
            const result = computeAdjustedXp(body.party, body.monsters);
            if (!result) {
              sendJson(res, 400, { error: "invalid party or monsters" });
              return;
            }
            sendJson(res, 200, result);
          } catch {
            sendJson(res, 400, { error: "invalid request body" });
          }
          return;
        }

        if (path === "/v1/initiative/order" && req.method === "POST") {
          try {
            const body = await readJsonBody(req);
            if (!Array.isArray(body.combatants)) {
              sendJson(res, 400, { error: "combatants is required" });
              return;
            }
            const order = computeInitiativeOrder(body.combatants);
            sendJson(res, 200, { order });
          } catch {
            sendJson(res, 400, { error: "invalid request body" });
          }
          return;
        }

        if (path === "/v1/characters/ability-modifier" && req.method === "POST") {
          try {
            const body = await readJsonBody(req);
            if (!isValidAbilityScore(body.score)) {
              sendJson(res, 400, { error: "score must be an integer from 1 through 30" });
              return;
            }
            const modifier = computeAbilityModifier(body.score);
            sendJson(res, 200, { score: body.score, modifier });
          } catch {
            sendJson(res, 400, { error: "invalid request body" });
          }
          return;
        }

        if (path === "/v1/characters/proficiency" && req.method === "POST") {
          try {
            const body = await readJsonBody(req);
            if (!isValidLevel(body.level)) {
              sendJson(res, 400, { error: "level must be an integer from 1 through 20" });
              return;
            }
            const proficiency_bonus = computeProficiencyBonus(body.level);
            sendJson(res, 200, { level: body.level, proficiency_bonus });
          } catch {
            sendJson(res, 400, { error: "invalid request body" });
          }
          return;
        }

        if (path === "/v1/characters/derived-stats" && req.method === "POST") {
          try {
            const body = await readJsonBody(req);
            const abilityKeys = ["str", "dex", "con", "int", "wis", "cha"] as const;
            const abilities = body.abilities;
            const armor = body.armor;
            if (
              !isValidLevel(body.level) ||
              typeof abilities !== "object" ||
              abilities === null ||
              !abilityKeys.every((k) => isValidAbilityScore(abilities[k])) ||
              typeof armor !== "object" ||
              armor === null ||
              typeof armor.base !== "number" ||
              typeof armor.shield !== "boolean" ||
              typeof armor.dex_cap !== "number"
            ) {
              sendJson(res, 400, { error: "invalid derived-stats request" });
              return;
            }
            const result = computeDerivedStats(
              body.level,
              abilities as Abilities,
              armor as Armor
            );
            sendJson(res, 200, result);
          } catch {
            sendJson(res, 400, { error: "invalid request body" });
          }
          return;
        }

        if (path === "/v1/combat/sessions" && req.method === "POST") {
          try {
            const body = await readJsonBody(req);
            if (typeof body.id !== "string" || body.id.length === 0) {
              sendJson(res, 400, { error: "id is required" });
              return;
            }
            if (combatSessions.has(body.id)) {
              sendJson(res, 400, { error: "session id already exists" });
              return;
            }
            if (!isValidCombatants(body.combatants)) {
              sendJson(res, 400, { error: "combatants is required" });
              return;
            }
            const session = createCombatSession(body.id, body.combatants);
            combatSessions.set(session.id, session);
            sendJson(res, 200, {
              id: session.id,
              round: session.round,
              turn_index: session.turn_index,
              active: activeCombatant(session),
              order: session.order,
            });
          } catch {
            sendJson(res, 400, { error: "invalid request body" });
          }
          return;
        }

        const conditionsMatch = path.match(
          /^\/v1\/combat\/sessions\/([^/]+)\/conditions$/
        );
        if (conditionsMatch && req.method === "POST") {
          try {
            const session = combatSessions.get(decodeURIComponent(conditionsMatch[1]));
            if (!session) {
              sendJson(res, 404, { error: "session not found" });
              return;
            }
            const body = await readJsonBody(req);
            const target = body.target;
            const condition = body.condition;
            const duration_rounds = body.duration_rounds;
            if (typeof target !== "string" || !session.order.some((c) => c.name === target)) {
              sendJson(res, 400, { error: "target must name a combatant in the session" });
              return;
            }
            if (typeof condition !== "string" || condition.length === 0) {
              sendJson(res, 400, { error: "condition is required" });
              return;
            }
            if (
              typeof duration_rounds !== "number" ||
              !Number.isInteger(duration_rounds) ||
              duration_rounds <= 0
            ) {
              sendJson(res, 400, { error: "duration_rounds must be a positive integer" });
              return;
            }
            const conditions = addCombatCondition(session, target, condition, duration_rounds);
            sendJson(res, 200, { target, conditions });
          } catch {
            sendJson(res, 400, { error: "invalid request body" });
          }
          return;
        }

        const advanceMatch = path.match(/^\/v1\/combat\/sessions\/([^/]+)\/advance$/);
        if (advanceMatch && req.method === "POST") {
          const session = combatSessions.get(decodeURIComponent(advanceMatch[1]));
          if (!session) {
            sendJson(res, 404, { error: "session not found" });
            return;
          }
          advanceCombatTurn(session);
          sendJson(res, 200, {
            id: session.id,
            round: session.round,
            turn_index: session.turn_index,
            active: activeCombatant(session),
            conditions: session.conditions,
          });
          return;
        }

        next();
      });
    },
  };
}

export default {
  plugins: [dndApiPlugin()],
  server: {
    host: "127.0.0.1",
  },
};
