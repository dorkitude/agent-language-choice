import { PlaySettlement, PlaySettlementAvailability } from "../../../store.js";

const VALID_AVAILABILITIES: PlaySettlementAvailability[] = ["open", "limited", "closed"];

export function serializeSettlementForDm(settlement: PlaySettlement) {
  return {
    settlement_id: settlement.settlement_id,
    name: settlement.name,
    services: settlement.services,
    availability: settlement.availability,
    discovered_by: settlement.discovered_by,
  };
}

export function serializeSettlementForPlayer(settlement: PlaySettlement, characterId: string) {
  return {
    settlement_id: settlement.settlement_id,
    name: settlement.name,
    services: settlement.services,
    availability: settlement.availability,
    discovered_by: settlement.discovered_by.includes(characterId) ? [characterId] : [],
  };
}

export function validateServices(services: unknown): string[] | Response {
  if (!Array.isArray(services) || services.length === 0) {
    return Response.json(
      { error: "services must be a non-empty array of non-empty strings" },
      { status: 400 },
    );
  }
  const normalized: string[] = [];
  for (const service of services) {
    if (typeof service !== "string" || service.trim().length === 0) {
      return Response.json(
        { error: "services must be a non-empty array of non-empty strings" },
        { status: 400 },
      );
    }
    normalized.push(service.trim());
  }
  const unique = new Set(normalized);
  if (unique.size !== normalized.length) {
    return Response.json({ error: "services must be unique after trimming" }, { status: 400 });
  }
  return normalized;
}

export function validateAvailability(
  availability: unknown,
): PlaySettlementAvailability | Response {
  if (
    typeof availability !== "string" ||
    !VALID_AVAILABILITIES.includes(availability as PlaySettlementAvailability)
  ) {
    return Response.json(
      { error: `availability must be exactly one of: ${VALID_AVAILABILITIES.join(", ")}` },
      { status: 400 },
    );
  }
  return availability as PlaySettlementAvailability;
}
