type ServiceState = typeof globalThis & { __dndServiceMaintenance?: boolean };

const state = globalThis as ServiceState;

if (state.__dndServiceMaintenance === undefined) state.__dndServiceMaintenance = false;

export function isMaintenanceMode(): boolean {
  return state.__dndServiceMaintenance === true;
}

export function setMaintenanceMode(maintenance: boolean): boolean {
  state.__dndServiceMaintenance = maintenance;
  return state.__dndServiceMaintenance;
}
