import { badRequest, isFiniteNumber, isRecord, json, readJson } from "../../../api.js";

export async function POST(request: Request) {
  const body = await readJson(request);
  if (!isRecord(body) || !isFiniteNumber(body.roll) || !isFiniteNumber(body.modifier) || !isFiniteNumber(body.dc)) {
    return badRequest();
  }

  const total = body.roll + body.modifier;

  return json({
    total,
    success: total >= body.dc,
    margin: total - body.dc,
  });
}
