// Entry point: opens the SQLite database, wires the HTTP server to the
// route table in router.ts, and listens on 127.0.0.1:PORT.
//
// See CODEBASE.md for an overview of the module layout and request flow.
import { createServer } from "node:http";
import { openDatabase } from "./db.js";
import { dispatch } from "./router.js";
import { sendJson } from "./http.js";

const server = createServer(async (req, res) => {
  try {
    await dispatch(req, res);
  } catch {
    sendJson(res, 400, { error: "invalid request body" });
  }
});

openDatabase();

const port = Number(process.env.PORT ?? "3000");
server.listen(port, "127.0.0.1", () => {
  // eslint-disable-next-line no-console
  console.log(`listening on 127.0.0.1:${port}`);
});
