# Live updates investigation and release — 19 October 2026

The online server was lightly loaded, with no unfinished sessions. WebSocket
connections were supported by the deployed Nginx/Gunicorn configuration. The
existing Classic gameplay handlers already emitted committed balances to the
actor, victim and session leaderboard; they did not wait for periodic polling.

Two avoidable waits were found:

- Enrollment notified existing clients only after the redirected player page
  connected and bootstrapped all problems. The HTTP enrollment route now emits
  the roster immediately after commit. The lobby requests only admission and
  round status, without rendering questions or creating per-problem state.
- Push Store submitted an HTTP form and redirected. It now uses the established
  admin connection and an acknowledgment. The existing CSRF-protected HTTP path
  remains available if the live connection is unavailable. Only admins can use
  the new socket event, and its session must exist and be Classic.

Hub, Classic lobby/game, admin supervision and store pages now prefer WebSockets
with an explicit polling fallback compatible with bundled Socket.IO 4.7.5.
Reconnecting admin watchers receive the current roster, leaderboard and summary.
Question content and leaderboard players are eager-loaded in the affected paths
to reduce repeated database queries. No gameplay rewards or economy rules changed.

## Validation and limits

- 22 targeted Python tests passed locally and in server staging, including two
  players receiving store updates, mining broadcasts, an actor/victim steal with
  matching balances, immediate enrollment notification, a lightweight lobby,
  admin reconnection and rejection of player attempts to push the store.
- The existing 12-check admin live supervision suite passed. JavaScript checks
  verified WebSocket-first setup and fallback without a tight retry loop.
- Before the socket store follow-up, five HTTP pushes to two public WebSocket
  receivers took 237–2,513 ms, median 1,696.5 ms. Nginx upstream processing took
  about 7 ms. Receiver differences were at most 0.3 ms on that sample.
- Ten public socket pushes from this laptop took 453–2,889 ms, median 886.2 ms;
  maximum difference between receivers was 10.5 ms. These are separate samples
  on a variable network, not a controlled proof of a particular speedup.
- A subsequent 10-packet laptop ping measured 169–784 ms, average 314 ms, with
  no loss in that short sample. Earlier live event round trips were 149–205 ms
  at the median across three probes. High bandwidth does not eliminate latency
  variation along this path.
- From the server through its public TLS/WebSocket endpoint, 12 store pushes
  took 4.53–9.20 ms, median 4.84 ms. Three broadcasts to **30 actual WebSocket
  connections** all arrived within 10.89–12.51 ms; receiver spread was
  5.46–7.20 ms. This verifies server broadcast capacity with near-server test
  connections. It is not a full classroom gameplay or simultaneous-wallet-write
  stress test across different devices/networks.

The remaining laptop-to-server variability is not explained by store handler
processing. A closer hosting region or improved network route may reduce it;
neither infrastructure nor the user's network configuration was changed.

## Deployment and recovery

The initial seven-file release and final eight-file follow-up used checksum
baselines, staging tests, fresh game/exam backups, and a no-unfinished-session
guard before restart. All 47 table counts were preserved. No schema migration,
account change, test session, or gameplay result was written online. Public
measurements re-sent unchanged store content on finished session #4.

Final rollback source and verification:
`/var/backups/korephysics-game/realtime-20261019-052518/`.
Initial release backup:
`/var/backups/korephysics-game/realtime-20261019-051628/`.
Local measurement scripts and reports are under `instance/`, including
`measure_online_store.py`, `measure_server_store.py`,
`online-realtime-measurements.json` and
`online-realtime-measurements-websocket.json`.

Local play was refreshed without resetting progress and restarted. All 1,449
online application/migration files checked by content refresh matched local
source. Existing browser pages need reloading to load the new connection setup.

Protocol references: [Socket.IO client options](https://socket.io/docs/v4/client-options/)
and [Flask-SocketIO deployment](https://flask-socketio.readthedocs.io/en/stable/deployment.html).
