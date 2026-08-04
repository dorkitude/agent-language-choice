import { sendJson, parseJsonBody } from '../lib/http.js';
import { campaigns, campaignSessions } from '../lib/stores.js';

export function registerSessionRoutes(router) {
  router.post('/v1/campaigns/:campaignId/sessions', async (req, res, { campaignId }) => {
    const campaign = campaigns.get(campaignId);
    if (!campaign) {
      sendJson(res, 404, { error: 'campaign not found' });
      return;
    }
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const id = body.data && body.data.id;
    const startsAt = body.data && body.data.starts_at;
    const durationMinutes = body.data && body.data.duration_minutes;
    const agenda = body.data && body.data.agenda;
    if (
      typeof id !== 'string' ||
      id.length === 0 ||
      typeof startsAt !== 'string' ||
      startsAt.length === 0 ||
      !Number.isInteger(durationMinutes) ||
      durationMinutes <= 0 ||
      !Array.isArray(agenda) ||
      !agenda.every((a) => typeof a === 'string' && a.length > 0)
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (campaignSessions.has(campaignId, id)) {
      sendJson(res, 409, { error: 'session already exists' });
      return;
    }
    const record = {
      id,
      starts_at: startsAt,
      duration_minutes: durationMinutes,
      agenda,
      present: [],
      absent: [],
    };
    campaignSessions.set(campaignId, id, record);
    sendJson(res, 201, {
      id: record.id,
      starts_at: record.starts_at,
      duration_minutes: record.duration_minutes,
      agenda_count: record.agenda.length,
    });
  });

  router.post(
    '/v1/campaigns/:campaignId/sessions/:sessionId/attendance',
    async (req, res, { campaignId, sessionId }) => {
      const campaign = campaigns.get(campaignId);
      if (!campaign) {
        sendJson(res, 404, { error: 'campaign not found' });
        return;
      }
      const record = campaignSessions.get(campaignId, sessionId);
      if (!record) {
        sendJson(res, 404, { error: 'session not found' });
        return;
      }
      const body = await parseJsonBody(req, res);
      if (!body.ok) return;
      const present = body.data && body.data.present;
      const absent = body.data && body.data.absent;
      if (
        !Array.isArray(present) ||
        !present.every((c) => typeof c === 'string' && c.length > 0) ||
        !Array.isArray(absent) ||
        !absent.every((c) => typeof c === 'string' && c.length > 0)
      ) {
        sendJson(res, 400, { error: 'invalid request' });
        return;
      }
      record.present = present;
      record.absent = absent;
      campaignSessions.set(campaignId, sessionId, record);
      sendJson(res, 200, {
        session_id: record.id,
        present_count: present.length,
        absent_count: absent.length,
      });
    }
  );

  router.get('/v1/campaigns/:campaignId/sessions/next', (req, res, { campaignId }) => {
    const campaign = campaigns.get(campaignId);
    if (!campaign) {
      sendJson(res, 404, { error: 'campaign not found' });
      return;
    }
    const sessions = campaignSessions.listByCampaign(campaignId);
    if (sessions.length === 0) {
      sendJson(res, 404, { error: 'no sessions scheduled' });
      return;
    }
    const next = sessions.reduce((earliest, session) =>
      new Date(session.starts_at).getTime() < new Date(earliest.starts_at).getTime() ? session : earliest
    );
    sendJson(res, 200, {
      id: next.id,
      starts_at: next.starts_at,
      agenda_count: next.agenda.length,
    });
  });
}
