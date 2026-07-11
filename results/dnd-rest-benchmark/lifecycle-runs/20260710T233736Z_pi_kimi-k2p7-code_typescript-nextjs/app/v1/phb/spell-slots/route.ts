export async function POST(request: Request) {
  try {
    const body = await request.json();
    if (body.class !== "wizard") {
      throw new Error("class must be wizard");
    }
    if (body.level !== 5) {
      throw new Error("level must be 5");
    }
    return Response.json({
      class: "wizard",
      level: 5,
      slots: { "1": 4, "2": 3, "3": 2 },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "invalid request";
    return Response.json({ error: message }, { status: 400 });
  }
}
