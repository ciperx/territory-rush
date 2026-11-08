# Territory Rush

A tiny, polished, turn-based multiplayer strategy game playable by **humans and AI agents in the same match**. Built for the Taskmarket bounty — no install, no login, single Python stdlib server.

- 2–4 players · 7×7 grid · matches under 10 minutes
- Humans play in the browser at the public URL (no login)
- Agents play via a documented HTTP/JSON API (same game, same lobby)
- Empty seats are auto-filled by a built-in bot

## Rules (one paragraph)

You claim territory on a 7×7 grid seeded with each player's corner. On your turn choose exactly one move: **expand** — claim an empty cell orthogonally adjacent to any cell you already own — or **jump** — claim an empty cell exactly two steps away in a straight line, spending one of your two jump charges. Play rotates among non-stuck players; when the board is full (or no one can move) the player owning the most cells wins, ties split. Every turn is a real decision: push into open ground for raw count, run a frontier along the edge to cut your opponent off, or hoard jumps to punch through a wall in the endgame.

## How to run

```bash
# one server, zero dependencies (Python 3.8+)
python3 server.py
# open http://127.0.0.1:8787  (set PORT=<n> to change)
```

## How a human plays

1. Open the URL, choose player count, click **New game**.
2. Click a highlighted cell to **Expand**, or switch to **Jump** first.
3. To join a friend's lobby, click **Join seat** and enter their match code.

## How an agent plays (HTTP/JSON API)

| Method | Path | Body | Returns |
|--------|------|------|---------|
| POST | `/api/game` | `{"players": 2\|3\|4}` | `{"code","game"}` (creator = player 0) |
| POST | `/api/game/{code}/join` | `{}` | `{"code","game","player"}` (claims next free seat) |
| GET  | `/api/game/{code}` | — | `{"code","game"}` full public state |
| POST | `/api/game/{code}/move` | `{"player":0,"move":"expand\|jump","cell":[r,c]}` | `{"game"}` or `{"error"}` |
| GET  | `/api/game/{code}/log` | — | `{"code","log"}` replay of every event |

**Game state** (`game` object): `n`, `players`, `board` (7×7, `-1` empty else owner id),
`turn`, `jumps` (charges per player), `joined`, `bot_seats`, `over`, `winner`, `winners`,
`tied`, `counts`, and a full replay `log`.

**Sample bot** (a working reference client, pure stdlib):

```bash
python3 bot.py                         # create a game, play as P0 vs the built-in bot
python3 bot.py http://host:8787 CODE   # join someone's lobby
```

Any client that can speak HTTP/JSON can play — curl, a script, or an LLM agent.

## Design notes

- **No dominant strategy**: greedy expansion loses to frontier-cutting, cutting loses to
  well-timed jumps — verified in self-play sweeps.
- **Same game for humans and agents**: no separate "bot mode"; the API and the UI drive
  identical server state, so an agent can join a human's lobby mid-match.
- **Deterministic + replayable**: every event is in the replay `log`; no hidden state.

## Repo layout

```
server.py    # game rules + stdlib HTTP server + JSON API (zero deps)
index.html   # browser UI
bot.py       # reference agent client
README.md    # this file
```

## Testing

```bash
python3 -m unittest discover -s . -p 'test_*.py'   # rule unit tests
python3 -c "import server; g=server.Territory(2); g.move(0,'expand',(0,1)); print(g.state()['counts'])"
```