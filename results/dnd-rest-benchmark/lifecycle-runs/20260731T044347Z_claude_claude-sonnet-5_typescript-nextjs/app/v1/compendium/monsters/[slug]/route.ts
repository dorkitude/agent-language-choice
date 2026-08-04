import { getMonster } from "../../store.js";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ slug: string }> },
) {
  const { slug } = await params;

  const monster = getMonster(slug);
  if (!monster) {
    return Response.json({ error: `monster ${slug} not found` }, { status: 404 });
  }

  return Response.json(monster);
}
