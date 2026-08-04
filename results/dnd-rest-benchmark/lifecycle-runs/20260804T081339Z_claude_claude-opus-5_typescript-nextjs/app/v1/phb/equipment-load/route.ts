import { badRequest, json, readObject } from "../../../../lib/http";
import { asFiniteNumber, asIntegerInRange } from "../../../../lib/validation";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const body = await readObject(request);
  if (!body) return badRequest("body must be a JSON object");

  const strength = asIntegerInRange(body.strength, 1, 30);
  if (strength === undefined) {
    return badRequest("strength must be an integer from 1 through 30");
  }

  // Carried weight may be fractional, unlike most fields on these endpoints.
  const weight = asFiniteNumber(body.weight);
  if (weight === undefined || weight < 0) {
    return badRequest("weight must be a non-negative number");
  }

  const capacity = strength * 15;

  // Carrying exactly the capacity is not encumbered; only exceeding it is.
  return json({ capacity, weight, encumbered: weight > capacity });
}
