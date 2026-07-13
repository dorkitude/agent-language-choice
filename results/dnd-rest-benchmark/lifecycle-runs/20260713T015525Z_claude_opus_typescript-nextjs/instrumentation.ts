export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { getDb } = await import("./app/v1/db");
    getDb(); // create game.db and initialize schema on server startup
  }
}
