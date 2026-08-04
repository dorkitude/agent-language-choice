/** Shared request/response shapes used across all domain handlers. */

export type JsonValue = Record<string, unknown>;

export interface ApiResult {
  status: number;
  body: JsonValue;
}
