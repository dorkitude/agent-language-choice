import { addCondition } from "../../../../../lib/combat.js";

function sessionIdFromUrl(url: string): string {
  const segments = new URL(url).pathname.split("/").filter(Boolean);
  const sessionsIndex = segments.indexOf("sessions");
  return segments[sessionsIndex + 1];
}

export async function POST(request: Request) {
  try {
    const id = sessionIdFromUrl(request.url);
    const body = await request.json();
    const result = addCondition(
      id,
      body.target,
      body.condition,
      body.duration_rounds
    );
    return Response.json(result);
  } catch (error) {
    const message = error instanceof Error ? error.message : "invalid request";
    if (message === "session not found") {
      return Response.json({ error: message }, { status: 404 });
    }
    return Response.json({ error: message }, { status: 400 });
  }
}
