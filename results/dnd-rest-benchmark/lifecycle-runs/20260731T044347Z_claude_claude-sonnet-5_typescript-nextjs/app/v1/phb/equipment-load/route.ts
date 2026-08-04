import { parseJsonBody } from "../../http.js";

export async function POST(request: Request) {
  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { strength, weight } = (body ?? {}) as {
    strength?: unknown;
    weight?: unknown;
  };

  if (typeof strength !== "number" || typeof weight !== "number") {
    return Response.json({ error: "strength and weight must be numbers" }, { status: 400 });
  }

  const capacity = strength * 15;
  const encumbered = weight > capacity;

  return Response.json({ capacity, weight, encumbered });
}
