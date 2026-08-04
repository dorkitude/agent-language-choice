// Process-global maintenance switch. Reference service state for the
// current test-run server — not campaign-local, and not reset by storage
// reset (it models an operational control plane, not stored data).
let maintenanceMode = false;

export function isMaintenanceMode(): boolean {
  return maintenanceMode;
}

export function setMaintenanceMode(value: boolean): void {
  maintenanceMode = value;
}
