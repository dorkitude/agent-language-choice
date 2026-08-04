export const runtime = "nodejs";

export async function register() {
  // Importing the storage module opens game.db and applies the schema.
  await import("./app/lib/storage");
}
