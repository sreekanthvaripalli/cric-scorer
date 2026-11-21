# Cric-Scorer — Implementation Tasks (Checklist)

**Purpose:** Mark tasks `[x]` as you complete them.  
**Scope:** Zero-dollar, offline-first cricket scorer with match initiation, live watching by match ID, initiator-approved scoring rights, online toss, and MVP determination.  
**Rules basis:** MCC Laws of Cricket (2017 Code, 4th Ed. 2026) + ICC T20/ODI/Test playing conditions from rulebook/.

**Related files:** PLAN.md (product & technical plan), FUNCTIONAL_SPEC.md (binding functional spec), IMPLEMENTATION_PLAN.md (original table-format task list).

**Tip:** To mark a task done, change - [ ] to - [x].

---

## Module 1 — Project scaffolding & local runnable skeleton

**Dependencies:** None  
**Deliverable:** Runnable local API skeleton

- [x] 1.1 Create directory structure: app/, app/scoring/, app/api/, frontend/, frontend/js, frontend/css, tests/, scripts/  
  > Done when: Folders exist in repo
- [x] 1.2 requirements.txt: fastapi, uvicorn, sqlalchemy, pydantic, python-multipart, pytest, httpx, alembic  
  > Done when: pip install -r requirements.txt succeeds
- [x] 1.3 .env.example: DATABASE_URL=sqlite:///./cric_scorer.db, SECRET_KEY=dev-change-me, WS_PING_INTERVAL=20  
  > Done when: File present
- [x] 1.4 scripts/run_local.py: init DB tables, start uvicorn app.main:app --reload --port 8000  
  > Done when: python scripts/run_local.py starts server
- [x] 1.5 GET /health returning {"status":"ok"}  
  > Done when: curl localhost:8000/health -> 200

---


## Module 2 — Anonymous matches, ownership & scoring-rights workflow

**Dependencies:** Module 1
**Deliverable:** Anonymous match creation, request/approve/reject scoring rights, authorised scoring enforcement (no registration)

- [x] 2.1 AnonymousSession model: id, session_id (UUID), device_name (optional nickname), created_at, last_seen_at
  > Done when: SQLAlchemy model + migration; no passwords, no usernames
- [x] 2.2 Match model: id, name, venue, date, format (T20/ODI/Test/Custom), overs_per_innings (initiator decides, not limited to standard formats), balls_per_over, status (created/in_progress/completed/locked), initiator_session_id, checksum, created_at, updated_at, locked_at, team_a_name, team_b_name
  > Done when: Model + migration with custom overs_per_innings field
- [x] 2.3 MatchRole model: match_id, session_id, role (initiator/scorer/watcher), scoring_rights (bool), approved_by_session_id, approved_at, created_at
  > Done when: Model + migration
- [x] 2.4 POST /matches — no authentication required. Any device creates match with team_a_name, team_b_name, format, overs_per_innings, auto-assigned role=initiator, scoring_rights=true for the creating session
  > Done when: Match created anonymously with initiator rights and both team names stored
- [x] 2.5 GET /matches/{id}/public — public, no auth. Returns teams, current score, overs, wickets, status, match_id, overs_per_innings
  > Done when: Anyone with match ID can view summary including custom overs
- [x] 2.6 POST /matches/{id}/request-scoring — anonymous session requests scoring rights; creates a pending request row with requestor session_id, optional device_name, request timestamp
  > Done when: Request recorded with session identity
- [x] 2.7 GET /matches/{id}/scoring-requests — initiator only; lists pending requests with requestor info (session_id, device_name, request timestamp)
  > Done when: Initiator can see who is requesting and when
- [x] 2.8 POST /matches/{id}/scoring-requests/{request_id}/approve — initiator only; grant scoring_rights=true, role=scorer, set approved_by_session_id/approved_at
  > Done when: Requestor session can now score
- [x] 2.9 POST /matches/{id}/scoring-requests/{request_id}/reject — initiator only; delete pending request
  > Done when: Request removed
- [x] 2.10 POST /matches/{id}/scoring-rights/revoke — initiator only; revoke a scorer's rights (not allowed if match locked)
  > Done when: Rights revoked
- [x] 2.11 POST /matches/{id}/transfer-ownership — initiator only; assign initiator role to another approved session
  > Done when: New session owns match
- [x] 2.12 Middleware: POST /balls, POST /undo, match settings require scoring_rights=true or role=initiator, verified by session cookie/device token
  > Done when: Unauthorised scoring returns 403
- [x] 2.13 Custom overs validation: validate overs_per_innings is positive integer, balls_per_over is 6 (default) or configurable, enforce max overs per bowler derived from custom overs (e.g., custom overs / 5 rounded down for T20-style, or initiator-specified)
  > Done when: Invalid overs rejected with clear error message

---

## Module 3 — Teams, players, squads & format config

**Dependencies:** Module 2
**Deliverable:** Teams, players, XI, toss, format config

- [x] 3.1 Team model: id, match_id, name, short_name
  > Done when: Model + migration
- [x] 3.2 Player model: id, team_id, name, role (batter/bowler/all-rounder/wicketkeeper), jersey_number
  > Done when: Model + migration
- [x] 3.3 POST /matches/{id}/teams — create/edit two teams for the match
  > Done when: Two teams linked to match
- [x] 3.4 POST /matches/{id}/squad — add players to a team's squad (11 + substitutes)
  > Done when: Squad stored
- [x] 3.5 POST /matches/{id}/playing-xi — select Playing XI per innings from squad, mark captain & wicketkeeper
  > Done when: XI stored
- [x] 3.6 POST /matches/{id}/toss — record toss_winner_team_id, toss_decision (bat/field); must happen before first ball
  > Done when: Toss locked before innings start
- [x] 3.7 Format presets: T20 (20 overs, max 4 overs/bowler, free hit after NB), ODI (50 overs), Test (unlimited, new ball 80 overs, follow-on). Custom: initiator sets overs_per_innings freely; max overs per bowler calculated as overs_per_innings / 5 (rounded down) unless initiator specifies otherwise.
  > Done when: Config applied by format, custom overs validated

---

## Module 12 — Online Toss (Heads / Tails)

**Dependencies:** Modules 1, 2, 3
**Deliverable:** Online toss with heads/tails, winner determined, bat/field choice locked before scoring

- [x] 12.1 Toss model: id, match_id, initiator_call (heads/tails), coin_result (heads/tails), winner_team_id, called_by_session_id, created_at
  > Done when: Model + migration
- [x] 12.2 POST /matches/{id}/toss/call — initiator calls heads or tails before coin flip
  > Done when: Call recorded, match status updated
- [x] 12.3 POST /matches/{id}/toss/flip — system randomly determines heads/tails (crypto-safe random), sets winner team based on call vs result
  > Done when: Result stored, winner team determined
- [x] 12.4 GET /matches/{id}/toss — public, returns toss call, result, winner, decision (bat/field)
  > Done when: Anyone can view toss outcome
- [x] 12.5 Toss must be completed before first ball is recorded; POST /balls rejects if toss not done
  > Done when: Toss enforced before scoring
- [x] 12.6 UI: initiator sees "Call Heads or Tails" button; after flip, shows winner and option to choose bat/field
  > Done when: Toss UI in PWA

---

## Module 4 — Ball-by-ball scoring engine (validated core)

**Dependencies:** Modules 1-3
**Deliverable:** Fully validated scoring engine with ~100% edge-case coverage

- [x] 4.1 Ball model: id, innings_id, over_number, ball_number, striker_id, non_striker_id, bowler_id, runs_batter, runs_extras, extra_type (nb/wd/bye/legbye/penalty), penalty_runs, is_wicket, dismissal_mode, fielder_id, short_runs, boundary_type (4/6), is_free_hit, is_valid_ball, created_at
  > Done when: Model + migration
- [x] 4.2 Over state machine: count only valid balls toward 6; No ball & Wide do not count; auto-call Over after 6 valid balls; switch ends
  > Done when: Over completes correctly
- [x] 4.3 Validate bowler: not bowling consecutive overs (Law 17.6), within max overs per format
  > Done when: Illegal bowler rejected
- [x] 4.4 Validate striker: not out, not retired out, at crease
  > Done when: Invalid striker rejected
- [x] 4.5 Runs: 0-6 bat runs; boundary 4/6 with Law 19.7 greater-of; byes/leg byes not debited to bowler; penalty runs separate column
  > Done when: Runs per Laws 18/19/23
- [x] 4.6 Extras: No ball = +1 penalty (No ball extra, debited to bowler, not in over, sets free_hit_next, overrides Wide); Wide = +1 penalty (Wide extra, debited to bowler, not in over); No ball overrides Wide (Law 21.12)
  > Done when: Extras correct
- [x] 4.7 Dismissals: all 10 modes (Bowled, Caught, LBW, Run out, Stumped, Hit wicket, Hit ball twice, Obstructing field, Timed out, Retired); validate legality vs No ball / Wide / free-hit context (Laws 21.17, 22.9); credit bowler/fielder per Laws 32-39; end-swap per Laws 18.11/18.12
  > Done when: Dismissals correct
- [x] 4.8 Strike rotation: swap ends on odd runs; after wicket per Law; after over swap ends & new bowler (not same as previous)
  > Done when: Strike logic correct
- [x] 4.9 Innings completion: all out / overs completed / target reached / declaration (Test)
  > Done when: Innings ends correctly
- [x] 4.10 POST /matches/{id}/balls — record one delivery atomically; recompute checksum; reject invalid with Law citation
  > Done when: Delivery endpoint works
- [x] 4.11 POST /matches/{id}/balls/{ball_id}/undo — rollback last delivery, restore previous state
  > Done when: Undo works
- [x] 4.12 Match checksum recomputed after every delivery; exposed via GET /matches/{id}/checksum
  > Done when: Checksum endpoint works

---

## Module 5 — Live score broadcasting & public watch by match ID

**Dependencies:** Modules 2-4
**Deliverable:** Live watch by match ID; real-time score updates

- [x] 5.1 WebSocket endpoint WS /ws/match/{id} — scorers and watchers connect; server broadcasts match state JSON on every change
  > Done when: WS connection works
- [x] 5.2 On new delivery / undo / result change, broadcast full payload to all connected clients for that match_id
  > Done when: Real-time push works
- [x] 5.3 GET /watch/{id} — read-only HTML watcher page: scoreboard, overs, wickets, recent balls, no scoring buttons; connects to WS and auto-updates
  > Done when: Public watcher page loads by match ID
- [x] 5.4 Fallback poll endpoint GET /matches/{id}/live for clients without WS support
  > Done when: Polling returns current state
- [x] 5.5 Reconnection: on WS reconnect, server sends current full match state so client catches up
  > Done when: No data loss on reconnect
- [x] 5.6 Presence (optional): show count of current watchers/scorers on watcher page
  > Done when: Presence displayed

---

## Module 6 — Scorecard, statistics & match result

**Dependencies:** Module 4
**Deliverable:** Full scorecard + legally correct match result

- [x] 6.1 Batting scorecard per innings: batter, runs, balls, 4s, 6s, SR, dismissal, bowler/fielder
  > Done when: Scorecard renders
- [x] 6.2 Bowling analysis: overs (cricket notation, e.g. 10.3), maidens, runs, wickets, wides, no-balls, economy
  > Done when: Bowling figures correct
- [x] 6.3 Extras summary: no-balls, wides, byes, leg byes, penalty runs (total extras)
  > Done when: Extras total matches delivery log
- [x] 6.4 Fall of wickets table: wicket, batter out, not out batter, runs at fall, over, partnership
  > Done when: FoW correct
- [x] 6.5 Result computation per Law 16: win by runs / by wickets / by Penalty runs / Tie / Draw / Conceded / Awarded
  > Done when: Result logic correct
- [x] 6.6 Winning-hit / extras rule (Law 16.6) for chasing side
  > Done when: Boundary credit on winning hit
- [x] 6.7 Super Over procedure (T20 tie-breaker)
  > Done when: Super Over flow works
- [x] 6.8 Follow-on enforcement (Test)
  > Done when: Follow-on offered correctly
- [x] 6.9 Match conclusion: Confirm correctness of scores step (Law 3.2 / 16.8) -> lock match (Law 16.10)
  > Done when: Match can be locked

---

## Module 7 — Persistence, export & import

**Dependencies:** Modules 1-4
**Deliverable:** SQLite persistence + export/import

- [x] 7.1 SQLAlchemy models + Alembic migrations (or create_all for v1)
  > Done when: db upgrade works
- [x] 7.2 SQLite default (cric_scorer.db beside app); DATABASE_URL env var switches to PostgreSQL
  > Done when: Local DB file created automatically
- [x] 7.3 GET /matches/{id}/export/json — full match JSON
  > Done when: JSON downloadable
- [x] 7.4 GET /matches/{id}/export/csv — scorecard CSV
  > Done when: CSV downloadable
- [x] 7.5 GET /matches/{id}/export/pdf — printable PDF scorecard (ReportLab or jspdf)
  > Done when: PDF opens/prints
- [x] 7.6 POST /import/json — restore a match from JSON (move matches between devices)
  > Done when: Import round-trip preserves all deliveries
- [x] 7.7 Auto-backup copy before major mutations (undo, result lock)
  > Done when: .bak file created

---

## Module 8 — Offline-first PWA frontend

**Dependencies:** Modules 2-5
**Deliverable:** Installable PWA scorer + watcher, offline capable

- [x] 8.1 manifest.json — Install to home screen on Android/iOS/desktop
  > Done when: PWA installable
- [x] 8.2 sw.js — service worker caches shell (HTML/CSS/JS), offline scoring queue, sync on reconnect
  > Done when: Works offline after first visit
- [x] 8.3 Initiator dashboard: create match -> shows Match ID + share link + scoring UI
  > Done when: Initiator can start match
- [x] 8.4 Scorer UI: big touch buttons (0-6, NB, WD, Bye, Leg bye, Wicket), bowler/striker selection, undo, over complete
  > Done when: Touch-friendly scoring
- [x] 8.5 Watcher UI: enter Match ID -> live read-only scoreboard; auto-updates via WS or polling
  > Done when: Watch by ID works
- [x] 8.6 Request scoring UI: Request scoring rights button; initiator sees approve/reject list
  > Done when: Request/approve flow in UI
- [x] 8.7 IndexedDB fallback queue for deliveries when offline; flush to server/DB on reconnect
  > Done when: Offline scoring syncs later
- [x] 8.8 No external CDN assets; high-contrast sunlight-friendly CSS
  > Done when: Fully offline capable

---

## Module 9 — Authorization, audit & security

**Dependencies:** Module 2
**Deliverable:** Secure scoring-rights model with audit trail

- [x] 9.1 Middleware: scoring_rights=true required for POST /balls, POST /undo, match settings
  > Done when: 403 on unauthorised scoring
- [x] 9.2 Initiator-only endpoints: approve/reject requests, revoke rights, transfer ownership, lock match
  > Done when: 403 if non-initiator calls
- [x] 9.3 Match lock: once locked (result confirmed), no scoring edits; admin unlock + audit log required
  > Done when: Locked match cannot be scored
- [x] 9.4 Audit log table: actor_session_id, action, match_id, target_id, timestamp, details
  > Done when: Every rights change logged
- [x] 9.5 Simple rate limiting on WS connections (per IP)
  > Done when: WS abuse limited
- [x] 9.6 Local mode = no auth required (single device); cloud mode = token-based auth (optional)
  > Done when: Auth optional for local

---

## Module 13 — Most Valuable Player (MVP) Determination

**Dependencies:** Modules 2, 4, 6
**Deliverable:** Auto-ranked MVP candidates + initiator-awarded MVP displayed on scorecard

- [x] 13.1 MVP model: id, match_id, player_id, points, reason_summary, awarded_by_session_id, awarded_at
  > Done when: Model + migration
- [x] 13.2 Points algorithm: runs scored, wickets taken, catches, run-outs, strike-rate, economy rate, bonus for winning match / player of match qualities
  > Done when: Formula documented and implemented
- [x] 13.3 GET /matches/{id}/mvp/candidates — returns ranked list of players with points breakdown from delivery log
  > Done when: Candidates auto-computed from match data
- [x] 13.4 POST /matches/{id}/mvp/award — initiator or scorer awards MVP to a player; requires match completed/locked
  > Done when: MVP awarded and stored
- [x] 13.5 GET /matches/{id}/mvp — public, returns awarded MVP player with points and reason
  > Done when: MVP visible on scorecard/watch page
- [x] 13.6 UI: MVP section on scorecard **for this match** showing winner, points, and key stats (runs, wickets, catches, etc.)
  > Done when: MVP displayed in frontend; stats are per-match only (career aggregates are Phase 4)

- [x] 9.7 Auto-close inactive matches: Background process/check that sets matches with status `in_progress` for more than 24 hours to `completed` with result `No Result`; creates audit log entry; match remains viewable but locked

---

## Module 10 — Testing & QA (zero credibility loss)

**Dependencies:** All previous modules
**Deliverable:** Test suite; release-ready quality

- [x] 10.1 Unit tests: dismissal mode x (normal / No ball / Wide / free-hit) matrix; extras types; short-run rules; boundary greater-of; over-counting with NB/WD; max overs/bowler; consecutive-over prevention
  > Done when: >=200 test cases
- [x] 10.2 Integration test: full flow - create match -> request scoring -> initiator approves -> score live -> watcher sees updates -> result -> lock
  > Done when: End-to-end passes
- [x] 10.3 Live sync test: two WS clients, broadcast consistency after each delivery
  > Done when: No drift
- [x] 10.4 Offline test: score entirely offline, close browser, reopen, data intact, sync on reconnect
  > Done when: Offline round-trip works
- [x] 10.5 Export/import round-trip: JSON preserves every delivery exactly
  > Done when: Import matches export
- [x] 10.6 Coverage target: 100% of scoring engine lines; any scoring bug = release blocker
  > Done when: Coverage report green

---

## Module 11 — Deployment ($0 platforms)

**Dependencies:** All modules
**Deliverable:** Deployed on free tier; local run documented

- [ ] 11.1 Verify scripts/run_local.py on Windows/macOS/Linux
  > Done when: Runs everywhere
- [ ] 11.2 Render deploy: DATABASE_URL to free PostgreSQL add-on; Procfile / start command
  > Done when: Live URL works
- [ ] 11.3 PythonAnywhere deploy: upload repo, set DATABASE_URL, WSGI config
  > Done when: Free subdomain works
- [ ] 11.4 Supabase / Neon: create free PostgreSQL, paste connection string into DATABASE_URL
  > Done when: Cloud DB connected
- [ ] 11.5 Optional static frontend on GitHub Pages / Netlify / Vercel pointing at backend API
  > Done when: Static hosting works
- [ ] 11.6 README: step-by-step local run + cloud deploy instructions
  > Done when: Docs complete

---

## Suggested execution order

1. Module 1 -> skeleton running locally
2. Module 2 -> matches with team names, ownership, request/approve scoring rights
3. Module 3 -> teams, players, squads
4. Module 12 -> online toss (heads/tails) - must complete before first ball
5. Module 4 -> scoring engine (write unit tests as you go)
6. Module 5 -> WS live broadcast + public watcher page
7. Module 6 -> scorecard + result
8. Module 7 -> persistence + export/import
9. Module 8 -> PWA frontend (scorer + watcher UIs)
10. Module 9 -> auth + audit
11. Module 13 -> MVP determination (after scoring engine & result)
12. Module 10 -> full QA
13. Module 11 -> deploy to free cloud

---
