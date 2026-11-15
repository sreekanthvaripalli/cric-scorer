# Cric-Scorer — Product & Technical Plan

**Goal:** A free, zero-dollar cricket scoring application for gully / club / school cricketers worldwide. Runs on any device with or without a database; optional free cloud deployment. Built strictly on the Laws of Cricket (MCC 2017 Code, 4th Ed. 2026) plus ICC T20 / ODI / Test playing conditions found in the repository `rulebook/` folder.

**License:** MIT (per existing `LICENSE`). Free forever. No ads, no tracking, no paid tiers.

---

## 1. Rules Basis (read from `rulebook/`)

The following source documents were extracted and reviewed:

| File | What it governs |
|------|-----------------|
| `Laws-of-Cricket-2017-Code-4th-Edition-(2026).pdf` | MCC Laws of Cricket — the core scoring authority |
| `t20.pdf` | ICC Men's T20 International Playing Conditions |
| `odi.pdf` | ICC ODI Playing Conditions |
| `test.pdf` | ICC Test Match Playing Conditions |

Key scoring rules encoded from the Laws:

* **Law 2.13 / 2.15 / Law 3** — Umpire signals to scorers; scorers acknowledge each signal; correctness of scores agreed at every interval and at match conclusion.
* **Law 17** — An over = 6 valid balls. No ball and Wide do **not** count as valid balls. A bowler shall not bowl two consecutive overs.
* **Law 18** — Runs scored by running, boundary (4/6), penalty runs; short runs (unintentional vs deliberate with 5-run penalty); crediting runs to striker vs extras; debits to bowler.
* **Law 19** — Boundaries: 6 for Boundary 6, 4 for Boundary 4 (default); greater of boundary allowance vs runs completed + run in progress; overthrow/wilful act rules.
* **Law 20** — Dead ball rules; ball ceasing to be dead.
* **Law 21** — No ball: +1 penalty run (scored as No ball extra, debited to bowler), does not count in over, batter can be out only under Laws 34/37/38; No ball overrides Wide; Free Hit on next delivery (format regulation).
* **Law 22** — Wide: +1 penalty run (scored as Wide extra, debited to bowler), does not count in over; limited dismissals (35/37/38/39).
* **Law 23** — Byes and Leg byes: not debited to bowler; leg byes not awarded if ball neither struck nor an attempt made (with exceptions).
* **Law 16** — Result: win by runs / by wickets / by Penalty runs / Tie / Draw / Match Conceded / Match Awarded; statement of result; correctness of result; mistakes in scoring; result not to be changed once agreed.
* **Law 25** — Batter's innings, runners, retiring.
* **Dismissals (Laws 32–39):** Bowled, Caught, LBW, Run out, Stumped, Hit wicket, Hit the ball twice, Obstructing the field, Timed out, Retired (out / not out).

Format-specific rules (from the playing-condition PDFs):

* **T20:** 20 overs per innings; max 4 overs per bowler; Super Over on tie; Free Hit after a No ball; Powerplay fielding restrictions.
* **ODI:** 50 overs per innings.
* **Test:** Multi-day, effectively unlimited overs; new ball after 80 overs; follow-on; declaration/forfeiture.

---

## 2. Guiding Principles (zero credibility loss)

1. **Source of truth is the ball-by-ball delivery log.** Match totals (runs, wickets, overs) are always recomputed from delivery records — never cached as the single source of truth. Derived totals are materialised only for display and are re-validated on save.
2. **Atomic deliveries.** Each ball is one transaction. Partial updates are rolled back.
3. **Umpire-scorer reconciliation.** The app mimics Law 2.15/3.2: a "confirm scores" step at intervals and match end, with a visible match-checksum so two scorers/umpires can detect drift.
4. **Offline-first.** The app must work fully offline in a browser (PWA) and as a local desktop app. No network required to score a match.
5. **Zero-dollar by design.** Every component has a forever-free tier or needs no server at all.
6. **No silent failures.** Every user action returns success/error; invalid cricket moves are rejected with a clear rule citation (e.g., "No ball does not count toward the 6-ball over").
7. **Export everywhere.** Scorecards export to JSON/CSV/printable PDF so data is never locked in.

---

## 3. Tech Stack (0-dollar investment)

| Layer | Choice | Why | Cost |
|-------|--------|-----|------|
| **Runtime (local)** | Python 3.10+ | Installed on virtually every OS; single-folder run; no DB needed | $0 |
| **Web framework** | FastAPI (or Flask) | Async, automatic OpenAPI docs, easy one-file run, production-grade | $0 |
| **ORM / DB abstraction** | SQLAlchemy 2.0 | Swappable dialect via `DATABASE_URL`; SQLite default | $0 |
| **Database (local/default)** | SQLite | Single file (`cric_scorer.db`), zero config, zero server, runs anywhere | $0 |
| **Database (optional cloud)** | PostgreSQL via `DATABASE_URL` | One env-var switch for cloud deployment | $0 (free tiers) |
| **Frontend** | Single-page PWA (HTML5 + vanilla JS + CSS) | No build step, works offline, installable to phone/desktop home screen, runs in any browser | $0 |
| **Styling** | Plain CSS (no framework CDN) | Works fully offline; no external dependency that can break | $0 |
| **PDF export** | ReportLab (Python) or `jspdf` (JS) | Printable scorecard | $0 |
| **Realtime (optional)** | WebSockets via FastAPI | Second scorer/umpire can follow live on another device on same LAN | $0 |
| **Packaging (desktop)** | PyInstaller or `pipx` + `requirements.txt` | One distributable folder / single executable | $0 |

### Suggested repo layout

```
cric-scorer/
├── rulebook/                 # source PDFs + extracted .txt (read-only reference)
├── app/
│   ├── __init__.py
│   ├── main.py               # FastAPI app + lifespan (DB init)
│   ├── config.py             # settings (DATABASE_URL, secret, formats)
│   ├── database.py           # SQLAlchemy engine/session (SQLite default)
│   ├── models.py             # SQLAlchemy ORM models
│   ├── schemas.py            # Pydantic request/response schemas
│   ├── scoring/              # scoring engine (the error-proof core)
│   │   ├── __init__.py
│   │   ├── engine.py         # process_ball(), validate()
│   │   ├── rules.py          # Laws of Cricket encodings
│   │   ├── extras.py         # no-ball/wide/bye/leg-bye/penalty
│   │   ├── dismissals.py     # all dismissal modes
│   │   ├── result.py         # match-result computation
│   │   └── checksum.py       # match reconciliation checksum
│   ├── api/                  # REST endpoints
│   │   ├── matches.py
│   │   ├── balls.py
│   │   ├── scorecard.py
│   │   └── export.py
│   ├── services/             # export, email, print
│   └── utils.py
├── frontend/
│   ├── index.html            # PWA shell (scoring UI)
│   ├── scorecard.html        # read-only scorecard view
│   ├── css/style.css
│   ├── js/app.js             # offline-first scoring UI
│   ├── js/scorecard.js
│   ├── sw.js                 # service worker (offline cache)
│   └── manifest.json         # PWA install manifest
├── tests/
│   ├── test_scoring_engine.py
│   ├── test_extras.py
│   ├── test_dismissals.py
│   ├── test_result.py
│   └── test_checksum.py
├── scripts/
│   ├── run_local.py          # python scripts/run_local.py  (starts local server)
│   └── export_scorecard.py
├── requirements.txt
├── .env.example              # DATABASE_URL=sqlite:///./cric_scorer.db
├── PLAN.md                   # this file
└── README.md
```

---

## 4. Deployment Platforms (seamless, $0)

### Option A — Run anywhere, no install (recommended for gully cricket)
Unzip the folder, run `python scripts/run_local.py`, open `http://localhost:8000` on phone/laptop over LAN or localhost. Data stored in `cric_scorer.db` next to the app. No internet, no account, no database server.

### Option B — Free cloud hosting (backend + SQLite or free PostgreSQL)

| Platform | Free tier | Best for | Notes |
|----------|-----------|----------|-------|
| **Render** | Free web service (spins down after inactivity) | Simple web URL | Prefer the free PostgreSQL add-on; otherwise export after each match |
| **Koyeb** | Free tier (Nano instances) | Always-ish free | Supports Docker or nixpacks |
| **Fly.io** | Small free allowance | Global edge | Good free allowance; requires credit card for verification |
| **PythonAnywhere** | Free tier (beginner) | Python apps | Easy, no Docker needed; free subdomain |
| **Oracle Cloud Always Free** | Always Free (ARM instances, DB) | Most generous | Always free, more setup |
| **Supabase** | Free PostgreSQL + Auth | Managed free DB | Use as the optional `DATABASE_URL` |
| **Neon** | Free serverless PostgreSQL | Managed free DB | Branching, generous free tier |

### Option C — Static frontend only
The frontend is pure HTML/JS/CSS; it can be hosted on **GitHub Pages, Netlify, Vercel, or Cloudflare Pages** for free and pointed at a backend API (or run fully offline using IndexedDB fallback).

**Recommended zero-dollar path:** Develop locally with SQLite (no deploy needed). If sharing matches online, deploy backend to **Render** or **PythonAnywhere** with **Supabase/Neon** free PostgreSQL, and frontend on **GitHub Pages**.

---

## 5. Module Breakdown (with detailed tasks)

### Module 1 — Match Setup & Configuration
Tasks:
- 1.1 Create match: match name, venue, date, format (T20 / ODI / Test / Custom), overs per innings, balls per over (default 6), number of innings (1 or 2), toss winner, toss decision (bat / field).
- 1.2 Team management: create / edit teams, team name, 11-player squad + substitutes, player roles (batter / bowler / all-rounder / wicketkeeper), jersey numbers.
- 1.3 Playing XI selection per innings (from squad).
- 1.4 Officials: umpire(s), scorer(s), match referee (optional).
- 1.5 Format-specific config: powerplay overs, max overs per bowler, free-hit rule, Super Over, follow-on threshold, new-ball interval (Test: 80 overs), DLS availability (noted as out of scope for v1).
- 1.6 Ground config: boundary type (4 / 6 default), custom boundary allowances.
- 1.7 Save / load match; resume a saved match mid-innings.
- 1.8 Validate: exactly 2 teams, 11 players each (or custom for gully), toss set before first ball.

### Module 2 — Ball-by-Ball Scoring Engine (CORE)
Tasks:
- 2.1 Delivery entry UI: select striker, non-striker, bowler; outcome (0,1,2,3,4,5,6 runs), extras, wicket, dismissal.
- 2.2 Record one delivery atomically; update striker / non-striker ends per cricket law (ends swap after odd runs, after a wicket per Law 18.11 / 18.12).
- 2.3 Over management: count only valid balls toward 6; No ball and Wide add an extra delivery; auto-call "Over" after 6 valid balls; switch ends.
- 2.4 Bowler tracking: overs bowled (cricket notation, e.g., 10.3), maidens, runs conceded, wickets, wides / no-balls conceded; enforce max-overs-per-bowler per format; prevent two consecutive overs by same bowler (Law 17.6).
- 2.5 Batter tracking: runs, balls faced, fours, sixes, strike rate, dismissal, how out, fielder, bowler.
- 2.6 Fall of wickets: wicket number, batter out, batter not out, runs at fall, over, partnership.
- 2.7 Strike rotation & "who faces next" after dismissal / over per Laws 18.11–18.13.
- 2.8 Innings completion: all out, overs completed, declaration / forfeiture (Test), target reached.

### Module 3 — Extras & Penalty Handling
Tasks:
- 3.1 No ball: +1 penalty run (No ball extra, debited to bowler); additional runs credited per Law 21.15 (striker if bat, else byes / leg byes); does not count in over; triggers Free Hit if format enables.
- 3.2 Wide: +1 penalty run (Wide extra, debited to bowler); runs as wides; does not count in over; limited dismissals only (Law 22.9).
- 3.3 No ball overrides Wide (Law 21.12).
- 3.4 Byes: runs not off bat, not debited to bowler (Law 23.1).
- 3.5 Leg byes: conditions per Law 23.2 / 23.3 (attempt to play or ball striking person); not debited to bowler.
- 3.6 Penalty runs (5-run): awarded to batting or fielding side per Laws 18.6, 28.3, 41, 42; displayed separately; do not count toward batter / bowler.
- 3.7 Short runs: unintentional (disallow run, signal) vs deliberate (disallow all runs, 5-run penalty to fielding side, Law 18.4 / 18.5).
- 3.8 Boundary 4 / 6: greater-of rule per Law 19.7; overthrow / wilful act per Law 19.8.

### Module 4 — Dismissals (all modes)
Tasks:
- 4.1 Bowled (Law 32)
- 4.2 Caught (Law 33) — credit fielder; bowler credited if caught by bowler
- 4.3 LBW (Law 36) — credit bowler
- 4.4 Run out (Law 38) — credit fielder(s); no bowler credit
- 4.5 Stumped (Law 39) — credit bowler + wicketkeeper
- 4.6 Hit wicket (Law 35) — credit bowler
- 4.7 Hit the ball twice (Law 34)
- 4.8 Obstructing the field (Law 37)
- 4.9 Timed out (Law 40)
- 4.10 Retired out / retired not out (Law 25.4)
- 4.11 Dismissal restrictions: not out from No ball except 34 / 37 / 38 (Law 21.17); not out from Wide except 35 / 37 / 38 / 39 (Law 22.9); end-swap rules per dismissal type (Law 18.11 / 18.12).

### Module 5 — Innings & Match Result
Tasks:
- 5.1 Innings state machine: not started / in progress / paused / completed / declared / forfeited.
- 5.2 Target chasing: second innings target = first innings total + 1.
- 5.3 Result computation per Law 16: win by runs / by wickets / by Penalty runs / Tie / Draw / No Result / Conceded / Awarded.
- 5.4 Winning-hit / extras rule (Law 16.6): boundary allowance credited fully when chasing.
- 5.5 Super Over procedure (T20 tie-breaker).
- 5.6 Follow-on enforcement (Test).
- 5.7 Match conclusion & "correctness of scores" confirmation (Law 16.8 / Law 3.2) — lock match after confirmation.
- 5.8 Mistakes-in-scoring correction procedure before lock (Law 16.9).

### Module 6 — Scorecard & Statistics
Tasks:
- 6.1 Batting scorecard: batter, runs, balls, 4s, 6s, SR, dismissal, bowler / fielder.
- 6.2 Bowling analysis: overs, maidens, runs, wickets, wides, no-balls, economy.
- 6.3 Extras summary: no-balls, wides, byes, leg byes, penalty runs (total extras).
- 6.4 Fall of wickets table.
- 6.5 Match summary: toss, result, margin, player of the match (manual), officials.
- 6.6 Partnerships and wagon-wheel placeholder (optional Phase 2).

### Module 7 — Data Persistence & Sync
Tasks:
- 7.1 SQLAlchemy models + migrations (Alembic optional; simple `create_all` for v1).
- 7.2 SQLite default (single file beside the app).
- 7.3 `DATABASE_URL` env var to switch to PostgreSQL (Supabase / Neon / Render) for cloud deployment.
- 7.4 Export: match to JSON, scorecard to CSV, scorecard to printable PDF.
- 7.5 Import: JSON match restore (for moving matches between devices).
- 7.6 Backup: local auto-backup copy before major operations.

### Module 8 — Offline-First PWA Frontend
Tasks:
- 8.1 `manifest.json` for "Install to home screen" on Android / iOS / desktop.
- 8.2 `sw.js` service worker: cache shell (HTML / CSS / JS), offline scoring queue, sync when online.
- 8.3 IndexedDB fallback queue for deliveries when offline; flush to server / DB on reconnect.
- 8.4 Responsive touch-friendly UI for scoring by ball (big buttons for 0–6, extras, wicket).
- 8.5 Dark mode optional; works on small phone screens in sunlight (high-contrast option).
- 8.6 No external CDN assets (fully offline capable).

### Module 9 — Integrity, Audit & Anti-Error (CREDIBILITY)
Tasks:
- 9.1 Match checksum computed after every delivery; displayed as "Match integrity hash" so two scorers can compare.
- 9.2 Recompute all totals from delivery log on every scorecard load; assert stored vs computed.
- 9.3 Validation errors with Law citations (e.g., "Rejected: No ball does not count as a valid ball — Law 17.3").
- 9.4 Undo last delivery (with re-confirmation) — rolls back the transaction.
- 9.5 "Confirm scores at interval / end of match" step (Law 3.2 / Law 2.15) before result is finalised.
- 9.6 Lock match after result confirmed; edits require admin unlock + audit log.
- 9.7 Unit test suite targeting 100% of scoring edge cases (no-ball + wicket + run out combinations, wide + boundary, short run + boundary, etc.).

### Module 10 — Administration & Settings
Tasks:
- 10.1 App settings: default format, boundary allowances, locale.
- 10.2 User roles (viewer, scorer, admin) for cloud deployment; local mode = no auth.
- 10.3 Match list / archive; delete match (soft delete with audit).
- 10.4 Reset app / clear local data.

---

## 6. Data Model (key entities)

```
Match            id, name, venue, date, format, overs_per_innings, balls_per_over,
                 innings_count, toss_winner_team_id, toss_decision, status,
                 created_at, updated_at, locked_at, checksum
Team             id, name, short_name
Player           id, team_id, name, role, jersey_number
PlayingXI        match_id, team_id, player_id, batting_order, is_keeper, is_captain
Innings          id, match_id, innings_number, batting_team_id, bowling_team_id,
                 target_runs, status, total_runs, total_wickets, overs_bowled,
                 result, result_margin
Over             id, innings_id, over_number, bowler_id, end, balls_valid, completed_at
Ball (delivery)  id, innings_id, over_number, ball_number, striker_id, non_striker_id,
                 bowler_id, runs_batter, runs_extras, extra_type (nb/wd/bye/legbye/penalty),
                 penalty_runs, is_wicket, dismissal_mode, fielder_id, bowler_credit,
                 short_runs, boundary_type (4/6), is_free_hit, is_valid_ball (for over count),
                 created_at
Wicket           id, ball_id, dismissal_mode, batter_out_id, fielder_id, bowler_credit_id,
                 not_out_batter_id, runs_at_fall, over_at_fall
ScoreSnapshot    id, match_id, generated_at, payload_json, checksum
```

**Invariant:** `Innings.total_runs`, `total_wickets`, `overs_bowled` are recomputed from `Ball` rows on read; stored copies are validated against recomputation.

---

## 7. Scoring Engine — State Machine (error-proof core)

For every delivery, the engine runs this ordered validation → mutation sequence:

1. **Validate match / innings state** (must be in progress; match not locked).
2. **Validate bowler** (not banned, not bowling consecutive overs, within max overs).
3. **Validate batsman / striker** (not out, not retired out, is at crease).
4. **Classify delivery:**
   - No ball? → +1 penalty (No ball extra), debit bowler, does NOT count in over, set `free_hit_next = true`, override any Wide.
   - Else Wide? → +1 penalty (Wide extra), debit bowler, does not count in over.
   - Else valid ball → counts toward the 6-ball over.
5. **Apply runs:** bat runs (0–6), boundary (apply Law 19.7 greater-of), byes / leg byes (not to bowler), penalty runs (separate column).
6. **Apply wicket (if any):** validate dismissal mode legality given no-ball / wide / free-hit context; credit bowler / fielder per Laws 32–39; apply end-change rules (Law 18.11 / 18.12); mark batter out; check all-out.
7. **Update strike:** swap ends on odd runs; after wicket per law; after over, swap ends & change bowler.
8. **Over completion:** when `valid_balls == 6` → call Over, rotate striker / non-striker ends, select new bowler (not same as previous).
9. **Innings completion:** all out / overs done / target reached / declaration → compute result if match over.
10. **Commit atomically**; recompute checksum; persist.

Rejected deliveries return a structured error citing the Law, so the scorer never records an illegal cricket state.

---

## 8. API Endpoints (server mode; local mode uses the same endpoints internally)

- `POST /matches` — create match
- `GET /matches` — list matches
- `GET /matches/{id}` — match detail
- `POST /matches/{id}/balls` — record a delivery (validated by the state machine)
- `POST /matches/{id}/balls/{ball_id}/undo` — undo last delivery
- `GET /matches/{id}/scorecard` — full scorecard (recomputed from delivery log)
- `GET /matches/{id}/checksum` — integrity hash for umpire-scorer reconciliation
- `POST /matches/{id}/confirm` — confirm correctness of scores (Law 3.2)
- `POST /matches/{id}/lock` — lock result (Law 16.10)
- `GET /matches/{id}/export/pdf` — printable PDF scorecard
- `GET /matches/{id}/export/json` — match JSON
- `POST /import/json` — restore a match from JSON

---

## 9. QA, Testing & Integrity (zero credibility loss)

Test phases (each must pass before release):

- **Phase 1 — Unit tests:** every dismissal mode × (normal / no-ball / wide / free-hit) matrix; extra types; short-run rules; boundary greater-of; over-counting with no-balls / wides; max-overs-per-bowler; consecutive-over prevention. Target: ≥200 test cases, 100% engine coverage.
- **Phase 2 — Scenario tests:** recreate famous match situations (tie, Super Over, win by 0 wickets, boundary after winning hit, short run on boundary, deliberate short-run penalty).
- **Phase 3 — Reconciliation test:** two "scorers" enter the same match; compare checksums at every interval and at end (mirrors Law 3.2).
- **Phase 4 — Offline / PWA test:** score entirely offline, close browser, reopen, data intact; sync on reconnect.
- **Phase 5 — Export test:** PDF scorecard opens and prints; JSON round-trip import preserves every delivery.
- **Phase 6 — Deployment test:** deploy to Render / PythonAnywhere + Supabase free tier end-to-end.

Any detected scoring bug = release blocker.

---

## 10. Roadmap

| Phase | Focus | Deliverable |
|-------|-------|-------------|
| **P0** | Core engine + local run | Ball-by-ball scoring, overs, extras, dismissals, result, SQLite, basic HTML UI, unit tests |
| **P1** | Polish & export | Scorecard PDF / CSV, JSON import / export, undo, checksum, PWA offline |
| **P2** | Format packs | T20 (4 overs / bowler, Free Hit, Super Over), ODI (50 overs), Test (declaration, follow-on, new ball) |
| **P3** | Cloud deploy | Render / PythonAnywhere + Supabase / Neon free PostgreSQL, optional auth, live follow |
| **P4** | Extras | Player stats across matches, leaderboards, wagon wheel, match sharing link |

---

## 11. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Scoring error → loss of credibility | Recompute-from-delivery-log invariant; unit-test matrix; checksum; Law citations on every rejection |
| Data loss (local SQLite file deleted) | Auto-backup before mutations; JSON export encouraged after every match |
| Cloud free-tier spins down / DB limits | Use SQLite for primary local use; cloud treated as optional sharing layer; export always available |
| No internet at ground | PWA + service worker + IndexedDB queue; fully offline scoring |
| Browser storage cleared | Prompt user to export / download JSON after match; never sole copy in browser |

---

## 12. Assumptions & Limitations

- v1 is scorer-operated (one person taps the ball outcome), not computer-vision or auto-scoring.
- DLS (rain) method is **out of scope** for v1; noted as a future integration (requires proprietary DLS software).
- Player performance stats are per-match; career aggregates are Phase 4.
- Free cloud tiers may have sleeping / monthly-hour limits; the app is designed so local use never depends on them.

---

## Next Steps to Start Building

1. Confirm the tech stack choice (FastAPI + SQLite + vanilla-JS PWA is the recommended $0 stack).
2. Create `requirements.txt`, `app/config.py`, `app/database.py`.
3. Implement `app/scoring/engine.py` with the state machine above and the test matrix.
4. Build the frontend `frontend/index.html` + `js/app.js`.
5. Write the first unit tests against Laws 17, 18, 21, 22, 23.
