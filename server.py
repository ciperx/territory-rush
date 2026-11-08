#!/usr/bin/env python3
"""
Territory Rush — a tiny turn-based multiplayer strategy game for humans AND agents.

Runs a single Python stdlib HTTP server that:
  * serves the browser UI (HTML/JS)
  * exposes a JSON API agents (and the UI) call to play the same matches

No third-party dependencies. No login. No install.

Play:
  2-4 players. Grid 7x7. Each player starts in a (roughly opposite) corner seed.

On your turn you choose ONE of two moves:
  "expand"  -> claim an empty cell orthogonally adjacent to any cell you own.
               (If no adjacent empty cell exists, you may claim ANY empty cell.)
  "jump"    -> claim an empty cell exactly 2 steps away (straight orthogonal),
               skipping over the in-between cell. Each player has 2 jumps per game.

Win:
  The game ends when the board is full OR every player is stuck (no legal move).
  Winner = most cells owned. Ties split. Every cell counts once.

Why it is strategic (meaningful decision each turn):
  * expand into the open centre (raw territory) vs push along an edge to CUT OFF
    an opponent's front (deny their expansion) vs hoard jumps for the endgame to
    punch through a wall. There is no dominant strategy — greedy expansion loses to
    frontier-cutting, and cutting loses to well-timed jumps.

API (JSON):
  POST /api/game          {"players":2|3|4}            -> game object (creator joins)
  POST /api/game/{id}/join  {}                          -> game object (a bot/human joins)
  GET  /api/game/{id}                                    -> full public state
  POST /api/game/{id}/move {"player":<0..n-1>,"move":"expand"|"jump","cell":[r,c]}
                                                         -> updated state or {"error":...}
  GET  /api/game/{id}/log                                 -> replay log (list of events)

Each game is identified by a short MATCH CODE (e.g. "C4F7A"). Empty seats are filled
by a trivial bot server-side so a lone human can play against the computer.
"""
import json
import os
import random
import string
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
N = 7
DIRS = [(-1, 0), (1, 0), (0, -1), (0, 1)]          # orthogonal
JUMP_DIRS = [(-2, 0), (2, 0), (0, -2), (0, 2)]     # straight 2-step jumps
JUMP_CHARGES = 2


class Territory:
    """Pure game state + rules. No I/O, fully testable."""

    def __init__(self, n_players):
        if n_players not in (2, 3, 4):
            raise ValueError("players must be 2, 3 or 4")
        self.n = N
        self.n_players = n_players
        self.board = [[-1] * N for _ in range(N)]   # -1 empty, else owner id
        self.turn = 0
        self.jumps = [JUMP_CHARGES] * n_players
        self.winner = None
        self.over = False
        self.log = []
        self.stuck_streak = 0
        self.joined = {0}   # player ids controlled by a real human/agent (0 = creator)
        # corner seeds (maximally separated per player count)
        seed_map = {
            2: [(0, 0), (N - 1, N - 1)],
            3: [(0, 0), (0, N - 1), (N - 1, (N - 1) // 2)],
            4: [(0, 0), (0, N - 1), (N - 1, N - 1), (N - 1, 0)],
        }
        for p in range(n_players):
            r, c = seed_map[n_players][p]
            self.board[r][c] = p
        self.log.append({"t": "start", "players": n_players})

    def own(self, p):
        return [(r, c) for r in range(N) for c in range(N) if self.board[r][c] == p]

    def legal(self, p):
        """Return {'expand': [...], 'jump': [...]} lists of (r,c)."""
        out = {"expand": [], "jump": []}
        mine = set(self.own(p))
        empties = {(r, c) for r in range(N) for c in range(N) if self.board[r][c] == -1}
        for r, c in mine:
            for dr, dc in DIRS:
                a = (r + dr, c + dc)
                if a in empties:
                    out["expand"].append(a)
        if self.jumps[p] > 0:
            for r, c in mine:
                for dr, dc in JUMP_DIRS:
                    a = (r + dr, c + dc)
                    if a in empties:
                        out["jump"].append(a)
        # fallback: if no expand cell, any empty is legal
        if not out["expand"] and empties:
            out["expand"] = sorted(empties)
        out["expand"] = sorted(set(out["expand"]))
        out["jump"] = sorted(set(out["jump"]))
        return out

    def move(self, p, kind, cell):
        if self.over:
            return {"error": "game over"}
        if p != self.turn:
            return {"error": f"not player {p}'s turn"}
        r, c = cell
        if not (0 <= r < N and 0 <= c < N):
            return {"error": "cell out of bounds"}
        legal = self.legal(p)
        if (r, c) not in legal.get(kind, []):
            return {"error": f"illegal {kind} move to {cell}"}
        self.board[r][c] = p
        if kind == "jump":
            self.jumps[p] -= 1
        self.log.append({"t": "move", "player": p, "move": kind, "cell": cell})
        self._advance()
        return {"ok": True}

    def _advance(self):
        # rotate to next player who still has a legal move; if a player is stuck
        # they are skipped (but the game only ends when NO ONE can move, or board full)
        full = all(self.board[r][c] != -1 for r in range(N) for c in range(N))
        if full:
            self._finish()
            return
        for _ in range(self.n_players):
            self.turn = (self.turn + 1) % self.n_players
            if self.legal(self.turn)["expand"] or self.legal(self.turn)["jump"]:
                return
        # nobody can move
        self._finish()

    def _finish(self):
        counts = [0] * self.n_players
        for r in range(N):
            for c in range(N):
                if self.board[r][c] >= 0:
                    counts[self.board[r][c]] += 1
        best = max(counts) if counts else -1
        winners = [p for p in range(self.n_players) if counts[p] == best]
        self.winner = winners[0] if len(winners) == 1 else -1  # -1 = tie
        self.tied = len(winners) > 1
        self.winners = winners
        self.over = True
        self.log.append({"t": "end", "counts": counts, "winners": winners})

    def state(self, viewer=None):
        return {
            "n": self.n,
            "players": self.n_players,
            "board": [row[:] for row in self.board],
            "turn": self.turn,
            "jumps": self.jumps[:],
            "winner": self.winner,
            "winners": getattr(self, "winners", None),
            "tied": getattr(self, "tied", False),
            "over": self.over,
            "counts": self._counts(),
            "joined": sorted(self.joined),
            "bot_seats": sorted(set(range(self.n_players)) - self.joined),
        }

    def _counts(self):
        c = [0] * self.n_players
        for r in range(N):
            for cc in range(N):
                if self.board[r][cc] >= 0:
                    c[self.board[r][cc]] += 1
        return c


# ---------------------------------------------------------------------------
# In-memory lobby + trivial bot that fills empty seats
# ---------------------------------------------------------------------------
GAMES = {}
GAMES_LOCK = threading.Lock()


def make_code():
    return "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(5))


def bot_move(game):
    """Trivial heuristic bot: expand toward the most-empty quadrant, else any legal."""
    leg = game.legal(game.turn)
    if leg["expand"]:
        r, c = max(leg["expand"], key=lambda a: a[0] * a[1] + a[0] + a[1])
        return ("expand", [r, c])
    if leg["jump"]:
        return ("jump", leg["jump"][0])
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "TerritoryRush/1.0"

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        if isinstance(body, bytes):
            data = body
        else:
            data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self):
        try:
            ln = int(self.headers.get("Content-Length", 0))
        except ValueError:
            ln = 0
        if ln <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(ln).decode("utf-8"))
        except Exception:
            return {}

    def _route(self, method):
        parsed = urllib.parse.urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        return method, parts, parsed.query

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        method, parts, q = self._route("GET")
        if parts == ["api", "game"]:
            return self._list_games()
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "game":
            return self._game_state(parts[2])
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "game":
            gid = parts[2]
            if parts[3] == "log":
                return self._game_log(gid)
            return self._game_state(gid)
        return self._serve_static()

    def do_POST(self):
        method, parts, q = self._route("POST")
        if parts == ["api", "game"]:
            return self._create_game(self._read_json())
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "game" and parts[3] == "join":
            return self._join_game(parts[2])
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "game" and parts[3] == "move":
            return self._do_move(parts[2], self._read_json())
        return self._send(404, {"error": "not found"})

    # ---- API ----
    def _list_games(self):
        with GAMES_LOCK:
            gs = [{"code": c, "players": g.n_players, "joinable": not g.over and len(g.own(0)) + len(g.own(1)) + 0 >= 0,
                   "over": g.over} for c, g in GAMES.items()]
        # simplify: joinable if there are empty seeds (we don't track explicit joins; recompute)
        with GAMES_LOCK:
            out = []
            for c, g in GAMES.items():
                joined = sum(1 for p in range(g.n_players) if any(g.board[r][cc] == p for r in range(N) for cc in range(N)))
                joined = self._joined_count(g)
                out.append({"code": c, "players": g.n_players, "joined": joined, "over": g.over})
        self._send(200, out)

    def _joined_count(self, g):
        return len(g.joined)

    def _create_game(self, body):
        try:
            np_ = int(body.get("players", 2))
        except (TypeError, ValueError):
            np_ = 2
        if np_ not in (2, 3, 4):
            return self._send(400, {"error": "players must be 2,3,4"})
        g = Territory(np_)
        code = make_code()
        with GAMES_LOCK:
            while code in GAMES:
                code = make_code()
            GAMES[code] = g
        # fill empty seats with bots immediately (a bot is just a seat, not a player id);
        # real agents/humans can still join and take a player slot via /join.
        self._send(200, {"code": code, "game": g.state(), "players": np_})

    def _join_game(self, code):
        with GAMES_LOCK:
            g = GAMES.get(code)
            if not g:
                return self._send(404, {"error": "no such game"})
            free = sorted(set(range(g.n_players)) - g.joined)
            if free:
                g.joined.add(free[0])
            return self._send(200, {"code": code, "game": g.state(), "player": free[0] if free else None})

    def _game_state(self, code):
        with GAMES_LOCK:
            g = GAMES.get(code)
            if not g:
                return self._send(404, {"error": "no such game"})
            return self._send(200, {"code": code, "game": g.state()})

    def _game_log(self, code):
        with GAMES_LOCK:
            g = GAMES.get(code)
            if not g:
                return self._send(404, {"error": "no such game"})
            return self._send(200, {"code": code, "log": g.log})

    def _do_move(self, code, body):
        with GAMES_LOCK:
            g = GAMES.get(code)
            if not g:
                return self._send(404, {"error": "no such game"})
            p = int(body.get("player", -1))
            kind = body.get("move")
            cell = body.get("cell")
            if not isinstance(cell, list) or len(cell) != 2:
                return self._send(400, {"error": "cell must be [r,c]"})
            res = g.move(p, kind, tuple(cell))
            if "error" in res:
                return self._send(400, res)
            # if the next turn belongs to a bot (unjoined seat), auto-play it
            auto = 0
            while not g.over and g.turn in self._bot_seats(g):
                mv = bot_move(g)
                if mv is None:
                    break
                g.move(g.turn, mv[0], mv[1])
                auto += 1
                if auto > 200:
                    break
            return self._send(200, {"code": code, "game": g.state(), "auto_bot_moves": auto})

    def _bot_seats(self, g):
        """Player ids not controlled by a real human/agent are auto-played by the bot."""
        return set(range(g.n_players)) - g.joined

    # ---- static ----
    def _serve_static(self):
        path = urllib.parse.urlparse(self.path).path or "/"
        if path == "/" or path == "/index.html":
            fp = os.path.join(HERE, "index.html")
            if not os.path.exists(fp):
                return self._send(200, "<h1>Territory Rush</h1><p>UI not found</p>", "text/html")
            body = open(fp, "rb").read()
            return self._send(200, body, "text/html; charset=utf-8")
        return self._send(404, "not found", "text/plain")

    def log_message(self, *a):
        pass


def main():
    port = int(os.environ.get("PORT", "8787"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Territory Rush running on http://0.0.0.0:{port}")
    srv.serve_forever()


if __name__ == "__main__":
    main()