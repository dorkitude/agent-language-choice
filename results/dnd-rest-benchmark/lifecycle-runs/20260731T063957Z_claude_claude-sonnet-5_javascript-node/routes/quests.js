import { sendJson, parseJsonBody } from '../lib/http.js';
import { campaigns, campaignQuests } from '../lib/stores.js';

const VALID_STATUSES = new Set(['active', 'completed', 'blocked']);

function toSummary(record) {
  return {
    id: record.id,
    title: record.title,
    status: record.status,
    milestones_total: record.milestones.length,
    milestones_done: record.completed.length,
  };
}

export function registerQuestRoutes(router) {
  router.post('/v1/campaigns/:campaignId/quests', async (req, res, { campaignId }) => {
    const campaign = campaigns.get(campaignId);
    if (!campaign) {
      sendJson(res, 404, { error: 'campaign not found' });
      return;
    }
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const id = body.data && body.data.id;
    const title = body.data && body.data.title;
    const status = body.data && body.data.status;
    const milestones = body.data && body.data.milestones;
    if (
      typeof id !== 'string' ||
      id.length === 0 ||
      typeof title !== 'string' ||
      title.length === 0 ||
      typeof status !== 'string' ||
      !VALID_STATUSES.has(status) ||
      !Array.isArray(milestones) ||
      !milestones.every((m) => typeof m === 'string' && m.length > 0)
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (campaignQuests.has(campaignId, id)) {
      sendJson(res, 409, { error: 'quest already exists' });
      return;
    }
    const record = { id, title, status, milestones, completed: [] };
    campaignQuests.set(campaignId, id, record);
    sendJson(res, 201, toSummary(record));
  });

  router.post('/v1/campaigns/:campaignId/quests/:questId/progress', async (req, res, { campaignId, questId }) => {
    const campaign = campaigns.get(campaignId);
    if (!campaign) {
      sendJson(res, 404, { error: 'campaign not found' });
      return;
    }
    const record = campaignQuests.get(campaignId, questId);
    if (!record) {
      sendJson(res, 404, { error: 'quest not found' });
      return;
    }
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const completed = body.data && body.data.completed;
    if (!Array.isArray(completed) || !completed.every((m) => typeof m === 'string' && m.length > 0)) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    const completedSet = new Set(record.completed);
    for (const milestone of completed) {
      if (record.milestones.includes(milestone)) {
        completedSet.add(milestone);
      }
    }
    record.completed = record.milestones.filter((m) => completedSet.has(m));
    if (record.status === 'active' && record.completed.length === record.milestones.length) {
      record.status = 'completed';
    }
    campaignQuests.set(campaignId, questId, record);
    sendJson(res, 200, {
      id: record.id,
      status: record.status,
      milestones_total: record.milestones.length,
      milestones_done: record.completed.length,
    });
  });

  router.get('/v1/campaigns/:campaignId/quests/summary', (req, res, { campaignId }) => {
    const campaign = campaigns.get(campaignId);
    if (!campaign) {
      sendJson(res, 404, { error: 'campaign not found' });
      return;
    }
    const quests = campaignQuests.listByCampaign(campaignId);
    const summary = { campaign_id: campaignId, active: 0, completed: 0, blocked: 0 };
    for (const quest of quests) {
      if (Object.prototype.hasOwnProperty.call(summary, quest.status)) {
        summary[quest.status] += 1;
      }
    }
    sendJson(res, 200, summary);
  });
}
