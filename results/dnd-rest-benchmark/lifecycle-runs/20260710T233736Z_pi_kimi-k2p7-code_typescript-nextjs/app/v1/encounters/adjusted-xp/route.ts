import { calculateEncounter } from "../../../lib/encounter.js";

export async function POST(request: Request) {
  const body = await request.json();
  const party: Array<{ level: number }> = body.party ?? [];
  const monsters: Array<{ cr: string; count: number }> = body.monsters ?? [];
  return Response.json(calculateEncounter(party, monsters));
}
