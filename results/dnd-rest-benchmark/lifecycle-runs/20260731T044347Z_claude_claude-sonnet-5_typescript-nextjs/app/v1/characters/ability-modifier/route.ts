import { abilityModifier } from "../rules.js";
import { parseJsonBody } from "../../http.js";

export async function POST(request: Request) {
  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { score } = (body ?? {}) as { score?: unknown };

  if (typeof score !== "number" || !Number.isInteger(score) || score < 1 || score > 30) {
    return Response.json({ error: "score must be an integer from 1 through 30" }, { status: 400 });
  }

  return Response.json({ score, modifier: abilityModifier(score) });
}
