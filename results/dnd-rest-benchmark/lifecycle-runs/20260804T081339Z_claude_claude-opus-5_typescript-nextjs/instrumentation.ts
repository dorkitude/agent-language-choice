/** Create the SQLite schema once, at server startup, before any request runs. */
export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  const { initSchema } = await import("./lib/db");
  initSchema();
}
