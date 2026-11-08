#!/usr/bin/env python3
"""
Sample agent bot for Territory Rush.

Plays the exact same game a human plays, through the public HTTP/JSON API.
This is the reference for how any agent (LLM, script, curl) drives a match.

Usage:
    python3 bot.py                          # create a 2-player game and play as P0 vs the built-in bot
    python3 bot.py http://host:8787 CODE    # join an existing game
"""
import json
import sys
import urllib.request
import time

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787"


def call(path, body=None):
    data = None
    req = urllib.request.Request(BASE + path)
    if body is not None:
        data = json.dumps(body).encode()
        req = urllib.request.Request(BASE + path, data=data,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def choose_move(game, me):
    """The same greedy heuristic the server bot uses — a sensible baseline."""
    board = game["board"]
    n = game["n"]
    mine = []
    empty = set()
    for r in range(n):
        for c in range(n):
            if board[r][c] == me:
                mine.append((r, c))
            elif board[r][c] == -1:
                empty.add((r, c))
    expands = []
    jumps = []
    for (r, c) in mine:
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            if (r + dr, c + dc) in empty:
                expands.append((r + dr, c + dc))
        if game["jumps"][me] > 0:
            for dr, dc in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                a = (r + dr, c + dc)
                if 0 <= a[0] < n and 0 <= a[1] < n and board[a[0]][a[1]] == -1:
                    jumps.append(a)
    if expands:
        r, c = max(expands, key=lambda a: a[0] * a[1] + a[0] + a[1])
        return ("expand", [r, c])
    if jumps:
        return ("jump", list(jumps[0]))
    return None


def main():
    me = 0
    if len(sys.argv) > 2:
        code = sys.argv[2]
        d = call(f"/api/game/{code}/join", {})
        me = d.get("player", 0)
    else:
        d = call("/api/game", {"players": 2})
        code = d["code"]
    print(f"playing game {code} as player {me} at {BASE}")
    moves = 0
    while True:
        d = call(f"/api/game/{code}")
        g = d["game"]
        if g["over"]:
            print(json.dumps({"result": "over", "winner": g["winner"],
                              "tied": g.get("tied"), "counts": g["counts"],
                              "moves": moves}, indent=2))
            break
        if g["turn"] != me:
            time.sleep(0.2)
            continue
        mv = choose_move(g, me)
        if mv is None:
            print("no legal move (should not happen)")
            break
        kind, cell = mv
        d = call(f"/api/game/{code}/move", {"player": me, "move": kind, "cell": cell})
        if "error" in d:
            print("move error:", d["error"])
            break
        moves += 1


if __name__ == "__main__":
    main()