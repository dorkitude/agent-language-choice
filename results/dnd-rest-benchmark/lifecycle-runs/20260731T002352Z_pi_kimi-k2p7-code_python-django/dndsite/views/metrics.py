"""Campaign-scoped service metrics view."""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import require_play_campaign_owner
from ..db import db_conn, _count_rejected_rate_events
from ..http import require_method


@csrf_exempt
def get_metrics(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        accepted = conn.execute(
            "SELECT COUNT(*) AS count FROM play_rate_events WHERE campaign_id = ?",
            (id,),
        ).fetchone()["count"]
        projection = conn.execute(
            "SELECT COUNT(*) AS count FROM projection_events WHERE campaign_id = ?",
            (id,),
        ).fetchone()["count"]
        rejected = _count_rejected_rate_events(conn, id)

    return JsonResponse(
        {
            "accepted_rate_events": accepted,
            "rejected_rate_events": rejected,
            "projection_events": projection,
            "uptime_ticks": 1,
        }
    )
