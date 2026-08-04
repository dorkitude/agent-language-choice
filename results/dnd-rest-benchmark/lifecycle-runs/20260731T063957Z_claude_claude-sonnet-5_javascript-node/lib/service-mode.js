// Process-global maintenance switch shared across all campaigns and the
// public /readyz endpoint. Deliberately not campaign-scoped: any DM can
// toggle it through any campaign, and it affects the whole test-run server.
let maintenance = false;

export function isMaintenance() {
  return maintenance;
}

export function setMaintenance(value) {
  maintenance = value;
}
