# Cric-Scorer — Implementation Task List

**Purpose:** Precise, module‑wise task list you can check off as you implement.  
**Scope:** Zero‑dollar, offline‑first cricket scorer with match initiation, live watching by match ID, and initiator‑approved scoring rights.  
**Rules basis:** MCC Laws of Cricket (2017 Code, 4th Ed. 2026) + ICC T20/ODI/Test playing conditions from `rulebook/`.

---

## Module 1 — Project scaffolding & local runnable skeleton

| # | Task | Definition of done |
|---|------|---------------------|
| 1.1 | Create directory structure: `app/`, `app/scoring/`, `app/api/`, `frontend/`, `frontend/js`, `frontend/css`, `tests/`, `scripts/` | Folders exist in repo |
| 1.2 | `requirements.txt`: `fastapi`, `uvicorn`, `sqlalchemy`, `pydantic`, `python-multipart`, `pytest`, `httpx`, `alembic` | `pip install -r requirements.txt` succeeds |
| 1.3 | `.env.example`: `DATABASE_URL=sqlite:///./cric_scorer.db`, `SECRET_KEY=dev-change-me`, `WS_PING_INTERVAL=20` | File present |
| 1.4 | `scripts/run_local.py`: init DB tables, start `uvicorn app.main:app --reload --port 8000` | `python scripts/run_local.py` starts server |
| 1.5 | `GET /health` returning `{"status":"ok"}` | `curl localhost:8000/health` → 200 |

**Dependencies:** None  
**Deliverable:** Runnable local API skeleton

---

## Module 2 — Users, matches, ownership & scoring‑rights workflow

| # | Task | Definition of done |
|---|------|---------------------|
| 2.1 | **User model**: id, username, display_name, password_hash (optional), created_at | SQLAlchemy model + migration |
| 2.2 | **Match model**: id, name, venue, date, format (`T20/ODI/Test/Custom`), overs_per_innings, balls_per_over, status (`created`/`in_progress`/`completed`/`locked`), initiator_user_id, checksum, created_at, updated_at, locked_at | Model + migration |
| 2.3 | **MatchRole model**: match_id, user_id, role (`initiator`/`scorer`/`watcher`), scoring_rights (bool), approved_by, approved_at, created_at | Model + migration |
| 2.4 | `POST /matches` — authenticated user creates match **with team names** (team_a_name, team_b_name), auto‑assigned role=initiator, scoring_rights=true | Returns match with initiator rights and both team names stored |
| 2.5 | `GET /matches/{id}/public` — **public, no auth**. Returns teams, current score, overs, wickets, status, match_id | Anyone with match ID can view summary |
| 2.6 | `POST /matches/{id}/request-scoring` — authenticated user requests scoring rights; creates a pending request row | Request recorded |
| 2.7 | `GET /matches/{id}/scoring-requests` — initiator only; lists pending requests with requestor info | Initiator can see requests |
| 2.8 | `POST /matches/{id}/scoring-requests/{request_id}/approve` — initiator only; grant scoring_rights=true, role=scorer, set approved_by/approved_at | Requestor can now score |
| 2.9 | `POST /matches/{id}/scoring-requests/{request_id}/reject` — initiator only; delete pending request | Request removed |
| 2.10 | `POST /matches/{id}/scoring-rights/revoke` — initiator only; revoke a scorer’s rights (not allowed if match locked) | Rights revoked |
| 2.11 | `POST /matches/{id}/transfer-ownership` — initiator only; assign initiator role to another approved scorer | New initiator owns match |
| 2.12 | Middleware: `POST /balls`, `POST /undo`, match settings require `scoring_rights=true` or role=initiator | Unauthorised scoring returns 403 |

**Dependencies:** Module 1  
**Deliverable:** Match creation, request/approve/reject scoring rights, authorised scoring enforcement

---

## Module 3 — Teams, players, squads & toss

| # | Task | Definition of done |
|---|------|---------------------|
| 3.1 | **Team model**: id, name, short_name | Model + migration |
| 3.2 | **Player model**: id, team_id, name, role (`batter`/`bowler`/`all-rounder`/`wicketkeeper`), jersey_number | Model + migration |
| 3.3 | `POST /matches/{id}/teams` — create/edit two teams for the match | Two teams linked to match |
| 3.4 | `POST /matches/{id}/squad` — add players to a team’s squad (11 + substitutes) | Squad stored |
| 3.5 | `POST /matches/{id}/playing-xi` — select Playing XI per innings from squad, mark captain & wicketkeeper | XI stored |
| 3.6 | `POST /matches/{id}/toss` — record toss_winner_team_id, toss_decision (`bat`/`field`); must happen before first ball | Toss locked before innings start |
| 3.7 | Format defaults: T20 (20 overs, max 4 overs/bowler, free hit after NB), ODI (50 overs), Test (unlimited, new ball 80 overs, follow-on) | Config applied by format |

**Dependencies:** Module 2  
**Deliverable:** Teams, players, XI, toss, format config

---

## Module 4 — Ball‑by‑ball scoring engine (validated core)

| # | Task | Definition of done |
|---|------|---------------------|
| 4.1 | **Ball model**: id, innings_id, over_number, ball_number, striker_id, non_striker_id, bowler_id, runs_batter, runs_extras, extra_type (`nb`/`wd`/`bye`/`legbye`/`penalty`), penalty_runs, is_wicket, dismissal_mode, fielder_id, short_runs, boundary_type (`4`/`6`), is_free_hit, is_valid_ball, created_at | Model + migration |
| 4.2 | Over state machine: count only valid balls toward 6; No ball & Wide do **not** count; auto‑call “Over” after 6 valid balls; switch ends | Over completes correctly |
| 4.3 | Validate bowler: not bowling consecutive overs (Law 17.6), within max overs per format | Illegal bowler rejected |
| 4.4 | Validate striker: not out, not retired out, at crease | Invalid striker rejected |
| 4.5 | Runs: 0–6 bat runs; boundary 4/6 with Law 19.7 greater‑of; byes/leg byes not debited to bowler; penalty runs separate column | Runs per Laws 18/19/23 |
| 4.6 | Extras: No ball = +1 penalty (No ball extra, debited to bowler, not in over, sets free_hit_next, overrides Wide); Wide = +1 penalty (Wide extra, debited to bowler, not in over); No ball overrides Wide (Law 21.12) | Extras correct |
| 4.7 | Dismissals: all 10 modes (Bowled, Caught, LBW, Run out, Stumped, Hit wicket, Hit ball twice, Obstructing field, Timed out, Retired); validate legality vs No ball / Wide / free‑hit context (Laws 21.17, 22.9); credit bowler/fielder per Laws 32–39; end‑swap per Laws 18.11/18.12 | Dismissals correct |
| 4.8 | Strike rotation: swap ends on odd runs; after wicket per Law; after over swap ends & new bowler (not same as previous) | Strike logic correct |
| 4.9 | Innings completion: all out / overs completed / target reached / declaration (Test) | Innings ends correctly |
| 4.10 | `POST /matches/{id}/balls` — record one delivery atomically; recompute checksum; reject invalid with Law citation | Delivery endpoint works |
| 4.11 | `POST /matches/{id}/balls/{ball_id}/undo` — rollback last delivery, restore previous state | Undo works |
| 4.12 | Match checksum recomputed after every delivery; exposed via `GET /matches/{id}/checksum` | Checksum endpoint works |

**Dependencies:** Modules 1–3  
**Deliverable:** Fully validated scoring engine with ~100% edge‑case coverage

---

## Module 5 — Live score broadcasting & public watch by match ID

| # | Task | Definition of done |
|---|------|---------------------|
| 5.1 | WebSocket endpoint `WS /ws/match/{id}` — scorers and watchers connect; server broadcasts match state JSON on every change | WS connection works |
| 5.2 | On new delivery / undo / result change, broadcast full payload to all connected clients for that `match_id` | Real‑time push works |
| 5.3 | `GET /watch/{id}` — read‑only HTML watcher page: scoreboard, overs, wickets, recent balls, no scoring buttons; connects to WS and auto‑updates | Public watcher page loads by match ID |
| 5.4 | Fallback poll endpoint `GET /matches/{id}/live` for clients without WS support | Polling returns current state |
| 5.5 | Reconnection: on WS reconnect, server sends current full match state so client catches up | No data loss on reconnect |
| 5.6 | Presence (optional): show count of current watchers/scorers on watcher page | Presence displayed |

**Dependencies:** Modules 2–4  
**Deliverable:** Live watch by match ID; real‑time score updates

---

## Module 6 — Scorecard, statistics & match result

| # | Task | Definition of done |
|---|------|---------------------|
| 6.1 | Batting scorecard per innings: batter, runs, balls, 4s, 6s, SR, dismissal, bowler/fielder | Scorecard renders |
| 6.2 | Bowling analysis: overs (cricket notation, e.g. 10.3), maidens, runs, wickets, wides, no‑balls, economy | Bowling figures correct |
| 6.3 | Extras summary: no‑balls, wides, byes, leg byes, penalty runs (total extras) | Extras total matches delivery log |
| 6.4 | Fall of wickets table: wicket, batter out, not out batter, runs at fall, over, partnership | FoW correct |
| 6.5 | Result computation per Law 16: win by runs / by wickets / by Penalty runs / Tie / Draw / Conceded / Awarded | Result logic correct |
| 6.6 | Winning‑hit / extras rule (Law 16.6) for chasing side | Boundary credit on winning hit |
| 6.7 | Super Over procedure (T20 tie‑breaker) | Super Over flow works |
| 6.8 | Follow‑on enforcement (Test) | Follow‑on offered correctly |
| 6.9 | Match conclusion: “Confirm correctness of scores” step (Law 3.2 / 16.8) → lock match (Law 16.10) | Match can be locked |

**Dependencies:** Module 4  
**Deliverable:** Full scorecard + legally correct match result

---

## Module 7 — Persistence, export & import

| # | Task | Definition of done |
|---|------|---------------------|
| 7.1 | SQLAlchemy models + Alembic migrations (or `create_all` for v1) | `db upgrade` works |
| 7.2 | SQLite default (`cric_scorer.db` beside app); `DATABASE_URL` env var switches to PostgreSQL | Local DB file created automatically |
| 7.3 | `GET /matches/{id}/export/json` — full match JSON | JSON downloadable |
| 7.4 | `GET /matches/{id}/export/csv` — scorecard CSV | CSV downloadable |
| 7.5 | `GET /matches/{id}/export/pdf` — printable PDF scorecard (ReportLab or `jspdf`) | PDF opens/prints |
| 7.6 | `POST /import/json` — restore a match from JSON (move matches between devices) | Import round‑trip preserves all deliveries |
| 7.7 | Auto‑backup copy before major mutations (undo, result lock) | `.bak` file created |

**Dependencies:** Modules 1–4  
**Deliverable:** SQLite persistence + export/import

---

## Module 8 — Offline‑first PWA frontend

| # | Task | Definition of done |
|---|------|---------------------|
| 8.1 | `manifest.json` — “Install to home screen” on Android/iOS/desktop | PWA installable |
| 8.2 | `sw.js` — service worker caches shell (HTML/CSS/JS), offline scoring queue, sync on reconnect | Works offline after first visit |
| 8.3 | Initiator dashboard: create match → shows Match ID + share link + scoring UI | Initiator can start match |
| 8.4 | Scorer UI: big touch buttons (0–6, NB, WD, Bye, Leg bye, Wicket), bowler/striker selection, undo, over complete | Touch‑friendly scoring |
| 8.5 | Watcher UI: enter Match ID → live read‑only scoreboard; auto‑updates via WS or polling | Watch by ID works |
| 8.6 | Request scoring UI: “Request scoring rights” button; initiator sees approve/reject list | Request/approve flow in UI |
| 8.7 | IndexedDB fallback queue for deliveries when offline; flush to server/DB on reconnect | Offline scoring syncs later |
| 8.8 | No external CDN assets; high‑contrast sunlight‑friendly CSS | Fully offline capable |

**Dependencies:** Modules 2–5  
**Deliverable:** Installable PWA scorer + watcher, offline capable

---

## Module 9 — Authorization, audit & security

| # | Task | Definition of done |
|---|------|---------------------|
| 9.1 | Middleware: `scoring_rights=true` required for `POST /balls`, `POST /undo`, match settings | 403 on unauthorised scoring |
| 9.2 | Initiator‑only endpoints: approve/reject requests, revoke rights, transfer ownership, lock match | 403 if non‑initiator calls |
| 9.3 | Match lock: once locked (result confirmed), no scoring edits; admin unlock + audit log required | Locked match cannot be scored |
| 9.4 | Audit log table: actor_user_id, action, match_id, target_id, timestamp, details | Every rights change logged |
| 9.5 | Simple rate limiting on WS connections (per IP) | WS abuse limited |
| 9.6 | Local mode = no auth required (single device); cloud mode = token‑based auth | Auth optional for local |

**Dependencies:** Module 2  
**Deliverable:** Secure scoring‑rights model with audit trail

---

## Module 10 — Testing & QA (zero credibility loss)

| # | Task | Definition of done |
|---|------|---------------------|
| 10.1 | Unit tests: dismissal mode × (normal / No ball / Wide / free‑hit) matrix; extras types; short‑run rules; boundary greater‑of; over‑counting with NB/WD; max overs/bowler; consecutive‑over prevention | ≥200 test cases |
| 10.2 | Integration test: full flow — create match → request scoring → initiator approves → score live → watcher sees updates → result → lock | End‑to‑end passes |
| 10.3 | Live sync test: two WS clients, broadcast consistency after each delivery | No drift |
| 10.4 | Offline test: score entirely offline, close browser, reopen, data intact, sync on reconnect | Offline round‑trip works |
| 10.5 | Export/import round‑trip: JSON preserves every delivery exactly | Import matches export |
| 10.6 | Coverage target: 100% of scoring engine lines; any scoring bug = release blocker | Coverage report green |

**Dependencies:** All previous modules  
**Deliverable:** Test suite; release‑ready quality

---

## Module 11 — Deployment ($0 platforms)

| # | Task | Definition of done |
|---|------|---------------------|
| 11.1 | Verify `scripts/run_local.py` on Windows/macOS/Linux | Runs everywhere |
| 11.2 | Render deploy: `DATABASE_URL` to free PostgreSQL add‑on; Procfile / start command | Live URL works |
| 11.3 | PythonAnywhere deploy: upload repo, set `DATABASE_URL`, WSGI config | Free subdomain works |
| 11.4 | Supabase / Neon: create free PostgreSQL, paste connection string into `DATABASE_URL` | Cloud DB connected |
| 11.5 | Optional static frontend on GitHub Pages / Netlify / Vercel pointing at backend API | Static hosting works |
| 11.6 | README: step‑by‑step local run + cloud deploy instructions | Docs complete |

**Dependencies:** All modules  
**Deliverable:** Deployed on free tier; local run documented

---

## Module 12 — Online Toss (Heads / Tails)

| # | Task | Definition of done |
|---|------|---------------------|
| 12.1 | **Toss model**: id, match_id, initiator_call (`heads`/`tails`), coin_result (`heads`/`tails`), winner_team_id, called_by_user_id, created_at | Model + migration |
| 12.2 | `POST /matches/{id}/toss/call` — initiator calls heads or tails before coin flip | Call recorded, match status updated |
| 12.3 | `POST /matches/{id}/toss/flip` — system randomly determines heads/tails (crypto‑safe random), sets winner team based on call vs result | Result stored, winner team determined |
| 12.4 | `GET /matches/{id}/toss` — public, returns toss call, result, winner, decision (bat/field) | Anyone can view toss outcome |
| 12.5 | Toss must be completed before first ball is recorded; `POST /balls` rejects if toss not done | Toss enforced before scoring |
| 12.6 | UI: initiator sees "Call Heads or Tails" button; after flip, shows winner and option to choose bat/field | Toss UI in PWA |

**Dependencies:** Modules 1, 2, 3  
**Deliverable:** Online toss with heads/tails, winner determined, bat/field choice locked before scoring

---

## Module 13 — Most Valuable Player (MVP) Determination

| # | Task | Definition of done |
|---|------|---------------------|
| 13.1 | **MVP model**: id, match_id, player_id, points, reason_summary, awarded_by, awarded_at | Model + migration |
| 13.2 | Points algorithm: runs scored, wickets taken, catches, run‑outs, strike‑rate, economy rate, bonus for winning match / player of match qualities | Formula documented and implemented |
| 13.3 | `GET /matches/{id}/mvp/candidates` — returns ranked list of players with points breakdown from delivery log | Candidates auto‑computed from match data |
| 13.4 | `POST /matches/{id}/mvp/award` — initiator or scorer awards MVP to a player; requires match completed/locked | MVP awarded and stored |
| 13.5 | `GET /matches/{id}/mvp` — public, returns awarded MVP player with points and reason | MVP visible on scorecard/watch page |
| 13.6 | UI: MVP section on scorecard showing winner, points, and key stats (runs, wickets, catches, etc.) | MVP displayed in frontend |

**Dependencies:** Modules 2, 4, 6  
**Deliverable:** Auto‑ranked MVP candidates + initiator‑awarded MVP displayed on scorecard

---

## Suggested execution order

1. **Module 1** → skeleton running locally  
2. **Module 2** → matches with team names, ownership, request/approve scoring rights  
3. **Module 3** → teams, players, squads  
4. **Module 12** → online toss (heads/tails) — must complete before first ball  
5. **Module 4** → scoring engine (write unit tests as you go)  
6. **Module 5** → WS live broadcast + public watcher page  
7. **Module 6** → scorecard + result  
8. **Module 7 → persistence + export/import** [x]  
9. **Module 8 → PWA frontend (scorer + watcher UIs)** [x]  
10. **Module 9 → auth + audit** [x]  
11. **Module 13** → MVP determination (after scoring engine & result)  
12. **Module 10** → full QA  
13. **Module 11** → deploy to free cloud  

---

**Related file:** `PLAN.md` in the same repo contains the high‑level product & technical plan (tech stack, data model, scoring state machine, API endpoints, risks). This `IMPLEMENTATION_PLAN.md` is the granular task checklist to execute against.











---
