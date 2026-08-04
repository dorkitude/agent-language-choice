import { parseJsonBody } from "../../http.js";

export async function POST(request: Request) {
  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { roll, modifier, dc } = (body ?? {}) as {
    roll?: unknown;
    modifier?: unknown;
    dc?: unknown;
  };

  if (typeof roll !== "number" || typeof modifier !== "number" || typeof dc !== "number") {
    return Response.json({ error: "roll, modifier, and dc must be numbers" }, { status: 400 });
  }

  const total = roll + modifier;
  const success = total >= dc;
  const margin = total - dc;

  return Response.json({ total, success, margin });
}
