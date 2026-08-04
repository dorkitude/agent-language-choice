export async function register() {
  // SQLite is a Node.js-only API.  Use a dynamic import so the Edge Runtime
  // instrumentation bundle does not statically analyze the storage module.
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { initStorage } = await import("./app/lib/storage.js");
    initStorage();
  }
}
