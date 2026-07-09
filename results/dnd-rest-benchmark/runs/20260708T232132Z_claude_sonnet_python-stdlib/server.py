import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CR_XP = {
    "0": 10,
    "1/8": 25,
    "1/4": 50,
    "1/2": 100,
    "1": 200,
    "2": 450,
    "3": 700,
    "4": 1100,
    "5": 1800,
}

THRESHOLDS = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}

DICE_RE = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$")


def multiplier_for_count(n):
    if n <= 1:
        return 1
    if n == 2:
        return 1.5
    if 3 <= n <= 6:
        return 2
    if 7 <= n <= 10:
        return 2.5
    if 11 <= n <= 14:
        return 3
    return 4


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        return json.loads(raw)

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        try:
            body = self._read_json()
        except (ValueError, TypeError):
            self._send_json(400, {"error": "invalid json"})
            return

        try:
            if self.path == "/v1/dice/stats":
                self._dice_stats(body)
            elif self.path == "/v1/checks/ability":
                self._ability_check(body)
            elif self.path == "/v1/encounters/adjusted-xp":
                self._adjusted_xp(body)
            elif self.path == "/v1/initiative/order":
                self._initiative_order(body)
            else:
                self._send_json(404, {"error": "not found"})
        except (ValueError, KeyError, TypeError):
            self._send_json(400, {"error": "invalid request"})

    def _dice_stats(self, body):
        expr = body.get("expression")
        if not isinstance(expr, str):
            self._send_json(400, {"error": "invalid expression"})
            return
        m = DICE_RE.match(expr.strip())
        if not m:
            self._send_json(400, {"error": "invalid expression"})
            return
        count = int(m.group(1))
        sides = int(m.group(2))
        modifier = int(m.group(3)) if m.group(3) else 0
        if count <= 0 or sides <= 0:
            self._send_json(400, {"error": "invalid expression"})
            return
        min_v = count * 1 + modifier
        max_v = count * sides + modifier
        average = (count * (sides + 1) / 2) + modifier
        if isinstance(average, float) and average.is_integer():
            average = int(average)
        self._send_json(200, {
            "dice_count": count,
            "sides": sides,
            "modifier": modifier,
            "min": min_v,
            "max": max_v,
            "average": average,
        })

    def _ability_check(self, body):
        roll = body["roll"]
        modifier = body["modifier"]
        dc = body["dc"]
        total = roll + modifier
        success = total >= dc
        margin = total - dc
        self._send_json(200, {"total": total, "success": success, "margin": margin})

    def _adjusted_xp(self, body):
        party = body.get("party", [])
        monsters = body.get("monsters", [])

        base_xp = 0
        monster_count = 0
        for m in monsters:
            cr = str(m["cr"])
            count = int(m["count"])
            if cr not in CR_XP:
                self._send_json(400, {"error": "unsupported cr"})
                return
            base_xp += CR_XP[cr] * count
            monster_count += count

        multiplier = multiplier_for_count(monster_count)
        adjusted_xp = base_xp * multiplier

        thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
        for p in party:
            level = int(p["level"])
            if level not in THRESHOLDS:
                self._send_json(400, {"error": "unsupported level"})
                return
            for k in thresholds:
                thresholds[k] += THRESHOLDS[level][k]

        difficulty = "trivial"
        if adjusted_xp >= thresholds["deadly"]:
            difficulty = "deadly"
        elif adjusted_xp >= thresholds["hard"]:
            difficulty = "hard"
        elif adjusted_xp >= thresholds["medium"]:
            difficulty = "medium"
        elif adjusted_xp >= thresholds["easy"]:
            difficulty = "easy"

        if isinstance(adjusted_xp, float) and adjusted_xp.is_integer():
            adjusted_xp = int(adjusted_xp)

        self._send_json(200, {
            "base_xp": base_xp,
            "monster_count": monster_count,
            "multiplier": multiplier,
            "adjusted_xp": adjusted_xp,
            "difficulty": difficulty,
            "thresholds": thresholds,
        })

    def _initiative_order(self, body):
        combatants = body.get("combatants", [])
        scored = []
        for c in combatants:
            score = c["roll"] + c["dex"]
            scored.append({"name": c["name"], "dex": c["dex"], "score": score})
        scored.sort(key=lambda x: (-x["score"], -x["dex"], x["name"]))
        order = [{"name": c["name"], "score": c["score"]} for c in scored]
        self._send_json(200, {"order": order})


def main():
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
