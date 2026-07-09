type AbilityCheckRequest = {
  roll?: unknown;
  modifier?: unknown;
  dc?: unknown;
};

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function badRequest() {
  return Response.json({ error: "bad_request" }, { status: 400 });
}

export async function POST(request: Request) {
  let body: AbilityCheckRequest;

  try {
    body = await request.json();
  } catch {
    return badRequest();
  }

  if (!isNumber(body.roll) || !isNumber(body.modifier) || !isNumber(body.dc)) {
    return badRequest();
  }

  const total = body.roll + body.modifier;
  const margin = total - body.dc;

  return Response.json({
    total,
    success: total >= body.dc,
    margin,
  });
}
