import { getCampaign, listEvents } from "../../../../lib/campaigns";
import { DEFAULT_OPEN_THREAD, EMPTY_RECAP_SUMMARY, isThreadKind } from "../../../../lib/dm";
import { badRequest, json, notFound, readObject } from "../../../../lib/http";
import { isValidId } from "../../../../lib/validation";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const body = await readObject(request);
  if (!body) return badRequest("body must be a JSON object");

  const campaignId = body.campaign_id;
  if (!isValidId(campaignId)) return badRequest("campaign_id must be a valid identifier");
  if (!getCampaign(campaignId)) return notFound("campaign not found");

  const events = listEvents(campaignId);
  const latest = events[events.length - 1];

  /** Explicit thread events win; a purely narrative log falls back to the standing thread. */
  const flagged = events.filter((event) => isThreadKind(event.kind)).map((event) => event.summary);
  let openThreads: string[] = flagged;
  if (flagged.length === 0) openThreads = events.length > 0 ? [DEFAULT_OPEN_THREAD] : [];

  return json({
    campaign_id: campaignId,
    summary: latest ? latest.summary : EMPTY_RECAP_SUMMARY,
    open_threads: openThreads,
  });
}
