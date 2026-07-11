import { json } from "../../../../api.js";
import { isValidSlug, monsters } from "../../data.js";

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ slug: string }>;
};

export async function GET(_request: Request, context: RouteContext) {
  const { slug } = await context.params;
  if (!isValidSlug(slug)) {
    return json({ error: "not_found" }, 404);
  }

  const monster = monsters.get(slug);
  if (monster === undefined) {
    return json({ error: "not_found" }, 404);
  }

  return json(monster);
}
