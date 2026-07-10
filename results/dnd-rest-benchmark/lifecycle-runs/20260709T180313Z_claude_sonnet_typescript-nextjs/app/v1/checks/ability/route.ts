function badRequest(message: string) {
  return Response.json({ error: message }, { status: 400 });
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return badRequest("invalid JSON body");
  }

  if (typeof body !== "object" || body === null) {
    return badRequest("body must be an object");
  }

  const { roll, modifier, dc } = body as {
    roll?: unknown;
    modifier?: unknown;
    dc?: unknown;
  };

  if (
    typeof roll !== "number" ||
    typeof modifier !== "number" ||
    typeof dc !== "number"
  ) {
    return badRequest("roll, modifier, and dc must be numbers");
  }

  const total = roll + modifier;
  const success = total >= dc;
  const margin = total - dc;

  return Response.json({ total, success, margin });
}
