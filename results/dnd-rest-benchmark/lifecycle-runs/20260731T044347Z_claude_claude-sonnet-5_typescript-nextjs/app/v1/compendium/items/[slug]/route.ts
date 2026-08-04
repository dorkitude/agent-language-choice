import { getItem } from "../../store.js";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ slug: string }> },
) {
  const { slug } = await params;

  const item = getItem(slug);
  if (!item) {
    return Response.json({ error: `item ${slug} not found` }, { status: 404 });
  }

  return Response.json(item);
}
