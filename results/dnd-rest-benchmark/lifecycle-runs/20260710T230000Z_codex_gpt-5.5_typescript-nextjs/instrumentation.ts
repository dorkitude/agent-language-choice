export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { initializeSchema } = await import("./app/v1/storage/db.js");
    initializeSchema();
  }
}
