import { json } from "../../../../api.js";
import { isValidSlug, items } from "../../data.js";

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ slug: string }>;
};

export async function GET(_request: Request, context: RouteContext) {
  const { slug } = await context.params;
  if (!isValidSlug(slug)) {
    return json({ error: "not_found" }, 404);
  }

  const item = items.get(slug);
  if (item === undefined) {
    return json({ error: "not_found" }, 404);
  }

  return json(item);
}
