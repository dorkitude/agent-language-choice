export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { getDb } = await import("./app/lib/db.js");
    getDb();
  }
}
