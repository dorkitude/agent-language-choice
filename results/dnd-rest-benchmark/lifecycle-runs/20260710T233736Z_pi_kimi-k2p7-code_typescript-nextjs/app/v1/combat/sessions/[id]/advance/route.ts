import { advanceTurn } from "../../../../../lib/combat.js";

function sessionIdFromUrl(url: string): string {
  const segments = new URL(url).pathname.split("/").filter(Boolean);
  const sessionsIndex = segments.indexOf("sessions");
  return segments[sessionsIndex + 1];
}

export async function POST(request: Request) {
  try {
    const id = sessionIdFromUrl(request.url);
    const result = advanceTurn(id);
    return Response.json(result);
  } catch (error) {
    const message = error instanceof Error ? error.message : "invalid request";
    if (message === "session not found") {
      return Response.json({ error: message }, { status: 404 });
    }
    return Response.json({ error: message }, { status: 400 });
  }
}
