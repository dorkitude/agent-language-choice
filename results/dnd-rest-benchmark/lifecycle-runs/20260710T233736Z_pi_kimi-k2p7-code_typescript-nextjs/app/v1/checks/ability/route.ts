export async function POST(request: Request) {
  const body = await request.json();
  const { roll, modifier, dc } = body;
  const total = roll + modifier;
  return Response.json({
    total,
    success: total >= dc,
    margin: total - dc,
  });
}
