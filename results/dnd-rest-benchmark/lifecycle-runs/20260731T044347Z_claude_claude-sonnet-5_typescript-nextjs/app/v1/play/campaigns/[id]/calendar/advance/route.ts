import { requireSession } from "../../../../../auth/session.js";
import { parseJsonBody } from "../../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../http.js";
import { calendarWeather, getPlayCalendar, updatePlayCalendar } from "../../../../store.js";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the campaign dm may advance the calendar",
  );
  if (ownerCheck) return ownerCheck;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { days?: unknown };

  const { days } = body;
  if (typeof days !== "number" || !Number.isInteger(days) || days < 1 || days > 30) {
    return Response.json({ error: "days must be an integer from 1 through 30" }, { status: 400 });
  }

  const calendar = getPlayCalendar(campaignId);
  if (!calendar) {
    return Response.json(
      { error: `calendar not initialized for campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const advanced = updatePlayCalendar({ ...calendar, day: calendar.day + days });

  return Response.json(
    {
      day: advanced.day,
      season: advanced.season,
      weather: calendarWeather(advanced.day, advanced.season),
    },
    { status: 200 },
  );
}
