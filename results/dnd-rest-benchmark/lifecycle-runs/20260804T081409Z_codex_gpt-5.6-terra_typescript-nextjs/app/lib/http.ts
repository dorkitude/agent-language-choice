import { NextResponse } from "next/server";

export function badRequest(message = "Invalid request") {
  return NextResponse.json({ error: message }, { status: 400 });
}

export async function jsonBody(request: Request): Promise<unknown | null> {
  try {
    return await request.json();
  } catch {
    return null;
  }
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value);
}
