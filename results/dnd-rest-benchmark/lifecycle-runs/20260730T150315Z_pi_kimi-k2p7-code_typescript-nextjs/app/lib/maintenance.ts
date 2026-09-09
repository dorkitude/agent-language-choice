/**
 * Process-global maintenance switch controlled by an authenticated DM.
 *
 * This lives outside of the SQLite store because readiness is a runtime
 * property of the current server process, not campaign-local persisted state.
 */

let maintenance = false;

export function getMaintenanceMode(): boolean {
  return maintenance;
}

export function setMaintenanceMode(value: boolean): void {
  maintenance = value;
}
