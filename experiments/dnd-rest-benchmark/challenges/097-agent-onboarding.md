# 097 Agent Onboarding

This cumulative suite inherits `096-api-schema-endpoint`.

Preserve all earlier behavior. Add authenticated campaign-member onboarding for
agents entering an existing campaign. Do not add later spectator behavior unless
the existing server model already has a spectator member role.

## Read Campaign Onboarding

`GET /v1/play/campaigns/{id}/onboarding`

Authentication and campaign membership are required.

- Missing or invalid `Authorization` returns 401.
- Authenticated requests for unknown campaigns return 404.
- Authenticated users who are not members of the campaign return 403.
- The campaign owner/DM and player members can read onboarding.

For the campaign owner/DM, return exactly:

`{"role":"dm","next_steps":["configure-safety","invite-players","start-campaign"],"can_mutate":true}`

For a player member, return exactly:

`{"role":"player","next_steps":["review-party","take-turn","submit-action"],"can_mutate":true}`

The response is role-specific, stable across repeated reads, and must not depend
on map iteration order or mutate campaign state.
