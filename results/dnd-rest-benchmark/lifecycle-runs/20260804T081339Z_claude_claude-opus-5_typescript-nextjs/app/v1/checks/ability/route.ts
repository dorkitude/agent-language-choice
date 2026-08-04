import { badRequest, json, readObject } from "../../../../lib/http";
import { asInteger } from "../../../../lib/validation";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const body = await readObject(request);
  if (!body) return badRequest("body must be a JSON object");

  const roll = asInteger(body.roll);
  const modifier = asInteger(body.modifier ?? 0);
  const dc = asInteger(body.dc);

  if (roll === undefined || modifier === undefined || dc === undefined) {
    return badRequest("roll, modifier and dc must be integers");
  }

  const total = roll + modifier;
  return json({ total, success: total >= dc, margin: total - dc });
}
