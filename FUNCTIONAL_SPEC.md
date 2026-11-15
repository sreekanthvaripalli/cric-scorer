# Cric-Scorer — Functional Specification

**Version:** 1.0  
**Status:** Draft — for implementation  
**Source of truth:** `PLAN.md` (product & technical plan), `IMPLEMENTATION_PLAN.md` (task checklist), `rulebook/` (Laws of Cricket + ICC playing conditions)  
**License:** MIT — free forever, zero-dollar investment

---

## 1. Purpose & Scope

**Purpose:** Provide a free, offline-capable, web-based cricket scoring application for gully / club / school cricketers worldwide who cannot afford licensed scoring software.

**Scope (v1):**
- Match creation by an initiator with team names
- Ball-by-ball scoring with full Laws of Cricket validation
- Live watching by match ID (read-only)
- Scoring-rights request → initiator approval → continue scoring
- Online toss (heads/tails) before first ball
- MVP determination at match end
- SQLite default (no database server); optional free PostgreSQL for cloud
- Export/import (JSON/CSV/PDF)
- PWA offline-first frontend

**Out of scope (v1):** DLS (rain) method, computer-vision auto-scoring, career aggregates across matches, paid tiers, ads, user tracking.

---

## 2. Presumptions & Assumptions

The following presumptions are binding for v1 implementation. Any deviation must be flagged as a change request.

| # | Presumption | Rationale / Impact |
|---|-------------|---------------------|
| P1 | **Scorer-operated, not auto-scoring.** One person taps the ball outcome via UI. No computer vision or ball-tracking hardware. | Keeps zero-dollar hardware requirement; works on any phone. |
| P2 | **Initiator creates the match and provides both team names at initiation.** Team names (`team_a_name`, `team_b_name`) are stored in the `Match` record at `POST /matches`. | Enables immediate match identity without a separate team-setup step. |
| P3 | **Only the initiator can score first.** Scoring rights are granted to the initiator by default; others must request and receive approval. | Prevents unauthorized score tampering. |
| P4 | **A scorer must be approved by the initiator before they can record deliveries.** Request → approve/reject workflow enforced by middleware (403 if unauthorized). | Maintains match integrity and initiator control. |
| P5 | **Watchers are read-only.** Anyone with a match ID can view live score via `GET /watch/{id}` or `GET /matches/{id}/public`, but cannot score. | Enables public live watching without authentication. |
| P6 | **Online toss is mandatory before the first ball.** `POST /balls` rejects if toss not completed. Toss uses crypto-safe random flip; initiator calls heads/tails. | Mirrors real cricket toss procedure; determines bat/field. |
| P7 | **MVP is awarded manually after match completion.** System auto-computes candidate rankings from delivery log; initiator/scorer selects final MVP. | Avoids opaque algorithmic decisions; keeps human judgment. |
| P8 | **SQLite is the default database.** Single `cric_scorer.db` file beside the app; no database server required for local use. | Zero-config, runs anywhere. |
| P9 | **`DATABASE_URL` env var switches to PostgreSQL** (Supabase / Neon / Render free tier) for optional cloud deployment. | One-line config change; no code change. |
| P10 | **Ball-by-ball delivery log is the source of truth.** Match totals (runs, wickets, overs) are recomputed from delivery records on every read; stored aggregates are validated against recomputation. | Prevents drift and data corruption. |
| P11 | **Atomic deliveries.** Each ball is one database transaction; partial updates are rolled back. | Guarantees consistency. |
| P12 | **Match checksum after every delivery.** Displayed as "Match integrity hash" so two scorers can compare and detect drift (mirrors Laws 2.15 / 3.2). | Credibility safeguard. |
| P13 | **Undo last delivery is supported** (with confirmation) and rolls back the transaction. | Human error recovery. |
| P14 | **Match lock after result confirmation.** Once locked (Law 16.10), no scoring edits; admin unlock + audit log required. | Prevents post-match tampering. |
| P15 | **Offline-first PWA.** Service worker caches shell; IndexedDB queues deliveries when offline; sync on reconnect. | Works at grounds with no internet. |
| P16 | **No external CDN assets.** All HTML/CSS/JS self-contained; works fully offline after first visit. | No broken dependencies at remote grounds. |
| P17 | **DLS (rain) method is out of scope.** Noted as future integration requiring proprietary DLS software. | Avoids scope creep and licensing issues. |
| P18 | **No authentication anywhere.** Local mode and cloud mode both require no registration. The initiator is identified by their device/session. | Zero-friction adoption |
| P19 | **Free cloud tiers may have sleeping/monthly-hour limits.** Local use never depends on cloud; cloud is optional sharing layer. | Zero-dollar sustainability. |
| P20 | **All scoring rules derive from `rulebook/` PDFs.** MCC Laws of Cricket (2017 Code, 4th Ed. 2026) + ICC T20/ODI/Test playing conditions. | Single rules authority; no ambiguity. |


---

## 3. User Roles (completely anonymous — no registration)

| Role | How identified | Capabilities |
|------|---------------|-------------|
| **Initiator** | Device/session that created the match (browser session cookie or device token stored locally) | Creates match with team names; starts toss; approves/rejects scoring requests; scores; revokes scoring rights; transfers ownership; locks match; awards MVP |
| **Scorer (approved)** | Anonymous session/device approved by initiator | Records deliveries; undoes own deliveries; views scorecard; cannot lock match or manage rights |
| **Watcher** | No ID needed — enters match ID | Read-only live scoreboard; auto-updates; no scoring buttons; no auth required |
| **Requester** | Anonymous session/device | Sends scoring-rights request; waits for approval; then scores |


---

## 4. Functional Requirements

### 4.1 Match Initiation (with team names)

| ID | Requirement |
|----|-------------|
| FR-1.1 | `POST /matches` accepts `team_a_name`, `team_b_name`, format, **overs_per_innings (initiator decides, custom allowed, not limited to standard T20/ODI/Test)**, balls_per_over, etc.; **no authentication required** — the creating device's session becomes the initiator with scoring rights |
| FR-1.2 | Match record stores both team names **and initiator-chosen overs_per_innings** at creation |
| FR-1.3 | Match ID is returned and shareable (watchers use it to join) |
| FR-1.4 | Match status: `created` → `in_progress` (after toss) → `completed` → `locked` |
| FR-1.5 | Custom overs validation: `overs_per_innings` must be a positive integer; max overs per bowler derived from custom overs (e.g., overs ÷ 5 rounded down) unless initiator specifies otherwise |

### 4.2 Users & Scoring Rights (anonymous sessions)

| ID | Requirement |
|----|-------------|
| FR-2.1 | **AnonymousSession model**: id, session_id (UUID), device_name (optional, user-set nickname), created_at, last_seen_at | No passwords, no usernames, no accounts |
| FR-2.2 | **MatchRole model**: match_id, session_id, role (`initiator`/`scorer`/`watcher`), scoring_rights (bool), approved_by_session_id, approved_at, created_at | Links anonymous session to match |
| FR-2.3 | `POST /matches` — **no authentication required**. Any device can create a match with `team_a_name`, `team_b_name`, format, `overs_per_innings` (initiator decides, custom allowed). The creating device's session becomes the initiator with scoring rights | Match created anonymously |
| FR-2.4 | `POST /matches/{id}/request-scoring` — anonymous session requests scoring rights; request includes requestor `session_id`, optional `device_name`, request timestamp | Request recorded with session identity |
| FR-2.5 | `GET /matches/{id}/scoring-requests` — initiator only; lists pending requests with requestor info (`session_id`, `device_name`, timestamp) so the initiator knows exactly who is asking | Initiator can see who is requesting |
| FR-2.6 | `POST /matches/{id}/scoring-requests/{request_id}/approve` — initiator only; grant scoring_rights=true, role=scorer, set approved_by_session_id/approved_at | Requestor session can now score |
| FR-2.7 | `POST /matches/{id}/scoring-requests/{request_id}/reject` — initiator only; delete pending request | Request removed |
| FR-2.8 | `POST /matches/{id}/scoring-rights/revoke` — initiator only; revoke a scorer's rights (not allowed if match locked) | Rights revoked |
| FR-2.9 | `POST /matches/{id}/transfer-ownership` — initiator only; assign initiator role to another approved session | New session owns match |
| FR-2.10 | Middleware: `POST /balls`, `POST /undo`, match settings require `scoring_rights=true` or role=initiator, verified by session cookie/device token | Unauthorised scoring returns 403 |
| FR-2.11 | Custom overs validation: `overs_per_innings` must be a positive integer; max overs per bowler derived from custom overs (e.g., overs ÷ 5 rounded down) unless initiator specifies otherwise | Invalid overs rejected with clear error message |

### 4.2.1 How the Initiator Identifies the Requestor

When any anonymous user wants to score for a match, they must send a scoring-rights request. The initiator identifies the requestor through the following chain:

1. **No registration needed** — Anyone can open the app and request scoring rights. There are no usernames or passwords.

2. **Request carries session identity** — `POST /matches/{id}/request-scoring` includes the requestor's anonymous `session_id` (generated by their browser/device) and an optional `device_name` (a nickname they can type, e.g., "Rahul's phone") plus a request timestamp.

3. **Initiator views pending requests** — `GET /matches/{id}/scoring-requests` returns a list of all pending requests, each showing:
   - Requestor `session_id`
   - Requestor `device_name` (optional nickname, e.g., "Rahul's phone")
   - Request timestamp
   - Match ID they want to score for

4. **Initiator decides** — The initiator reviews who is asking (e.g., "Rahul's phone wants to score") and clicks Approve or Reject per request.

5. **Approval grants rights** — On approve, `scoring_rights=true` and role=`scorer` are set for that specific `session_id` on that match. That session can then record deliveries.

6. **Audit trail** — Every request, approval, and rejection is written to the `AuditLog` table with `actor_session_id`, `action`, `match_id`, `target_id`, timestamp, and details — so there is always a record of who requested and who approved.

---

### 4.3 Online Toss (Heads / Tails)

| ID | Requirement |
|----|-------------|
| FR-3.1 | Toss model: id, match_id, initiator_call, coin_result, winner_team_id, called_by_user_id, created_at |
| FR-3.2 | `POST /matches/{id}/toss/call` — initiator calls heads/tails before flip |
| FR-3.3 | `POST /matches/{id}/toss/flip` — crypto-safe random determines heads/tails; winner team set based on call vs result |
| FR-3.4 | `GET /matches/{id}/toss` — public, returns call, result, winner, bat/field decision |
| FR-3.5 | Toss must complete before first ball; `POST /balls` rejects if toss not done |

### 4.4 Ball-by-Ball Scoring (Laws of Cricket)

| ID | Requirement | Laws Reference |
|----|-------------|----------------|
| FR-4.1 | Ball model stores all delivery attributes (batter runs, extras, wicket, dismissal, fielder, boundary, free_hit, valid_ball, etc.) | — |
| FR-4.2 | Over counts only valid balls toward 6; No ball & Wide do not count | Law 17.3 |
| FR-4.3 | No consecutive overs by same bowler | Law 17.6 |
| FR-4.4 | Max overs per bowler per format (T20: 4, ODI: 10, Test: unlimited) | Format conditions |
| FR-4.5 | No ball: +1 penalty (No ball extra, debited to bowler), not in over, sets free_hit_next, overrides Wide | Laws 21.14–21.17 |
| FR-4.6 | Wide: +1 penalty (Wide extra, debited to bowler), not in over; limited dismissals (35/37/38/39) | Laws 22.6–22.9 |
| FR-4.7 | No ball overrides Wide | Law 21.12 |
| FR-4.8 | Byes not debited to bowler; Leg byes per conditions | Law 23 |
| FR-4.9 | Penalty runs (5-run) separate column; not debited to batter/bowler | Law 18.6 |
| FR-4.10 | Short runs: unintentional vs deliberate (5-run penalty to fielding side) | Laws 18.4/18.5 |
| FR-4.11 | Boundary 4/6: greater-of rule (allowance vs runs completed + run in progress) | Law 19.7 |
| FR-4.12 | All 10 dismissal modes with legality validation vs No ball/Wide/free-hit context | Laws 32–40 |
| FR-4.13 | Strike rotation per Laws 18.11/18.12/18.13 | Laws 18.11–18.13 |
| FR-4.14 | `POST /balls` atomic; invalid moves rejected with Law citation | — |
| FR-4.15 | `POST /balls/{id}/undo` rollback | — |
| FR-4.16 | Checksum recomputed after every delivery | Laws 2.15 / 3.2 |


### 4.5 Live Watching by Match ID

| ID | Requirement |
|----|-------------|
| FR-5.1 | `WS /ws/match/{id}` broadcasts match state JSON on every change |
| FR-5.2 | `GET /watch/{id}` — read-only HTML watcher page, no scoring buttons |
| FR-5.3 | `GET /matches/{id}/public` — public JSON summary (no auth) |
| FR-5.4 | Polling fallback `GET /matches/{id}/live` |
| FR-5.5 | Reconnection sends full current match state |

### 4.6 Scorecard & Result

| ID | Requirement | Laws Reference |
|----|-------------|----------------|
| FR-6.1 | Batting scorecard: runs, balls, 4s, 6s, SR, dismissal, bowler/fielder | Law 18.10 |
| FR-6.2 | Bowling analysis: overs (cricket notation), maidens, runs, wickets, wides, no-balls, economy | — |
| FR-6.3 | Extras summary: no-balls, wides, byes, leg byes, penalty runs | — |
| FR-6.4 | Fall of wickets table | — |
| FR-6.5 | Result: win by runs / wickets / Penalty runs / Tie / Draw / Conceded / Awarded | Law 16 |
| FR-6.6 | Winning-hit / extras rule (Law 16.6) | Law 16.6 |
| FR-6.7 | Super Over (T20 tie-breaker) | T20 conditions |
| FR-6.8 | Follow-on (Test) | Test conditions |
| FR-6.9 | Match lock after "confirm correctness of scores" | Laws 3.2 / 16.8 / 16.10 |


### 4.7 MVP Determination

| ID | Requirement |
|----|-------------|
| FR-7.1 | MVP model: id, match_id, player_id, points, reason_summary, awarded_by, awarded_at |
| FR-7.2 | Points algorithm: **per-match** runs scored, wickets taken, catches, run-outs, strike-rate, economy rate, bonus for winning match / player of match qualities |
| FR-7.3 | `GET /matches/{id}/mvp/candidates` — ranked list auto-computed from delivery log |
| FR-7.4 | `POST /matches/{id}/mvp/award` — initiator/scorer awards MVP; match must be completed/locked |
| FR-7.5 | `GET /matches/{id}/mvp` — public, returns awarded MVP |

### 4.8 Persistence & Export

| ID | Requirement |
|----|-------------|
| FR-8.1 | SQLite default; `DATABASE_URL` switches to PostgreSQL |
| FR-8.2 | `GET /matches/{id}/export/json` — full match JSON |
| FR-8.3 | `GET /matches/{id}/export/csv` — scorecard CSV |
| FR-8.4 | `GET /matches/{id}/export/pdf` — printable PDF scorecard |
| FR-8.5 | `POST /import/json` — restore match from JSON |
| FR-8.6 | Auto-backup before major mutations |

### 4.9 PWA Frontend

| ID | Requirement |
|----|-------------|
| FR-9.1 | `manifest.json` — installable to home screen |
| FR-9.2 | `sw.js` — service worker, offline queue, sync on reconnect |
| FR-9.3 | Initiator dashboard: create match with team names → shows Match ID + share link |
| FR-9.4 | Scorer UI: touch buttons (0–6, NB, WD, Bye, Leg bye, Wicket), undo, over complete |
| FR-9.5 | Watcher UI: enter Match ID → live read-only scoreboard |
| FR-9.6 | Request/approve scoring rights UI |
| FR-9.7 | IndexedDB fallback for offline scoring |
| FR-9.8 | No external CDN assets |

### 4.10 Audit & Security

| ID | Requirement |
|----|-------------|
| FR-10.1 | Audit log table: actor_user_id, action, match_id, target_id, timestamp, details |
| FR-10.2 | Match lock prevents scoring edits; admin unlock + audit required |
| FR-10.3 | No authentication anywhere — local and cloud modes both work without registration. Session cookie/device token verifies initiator and scorer rights. |
| FR-10.4 | **Auto-close inactive matches:** Matches left `in_progress` status for more than 24 hours are automatically set to `completed` with result `No Result`; an audit log entry is created; the match remains viewable but locked |
| FR-10.5 | **Previous matches preserved** — all matches stored in the default SQLite database (`cric_scorer.db`) are retained indefinitely; users can export/import matches via JSON for backup or transfer |


---

## 5. Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NF-1 | **Zero dollar:** All components have forever-free tier or need no server |
| NF-2 | **Offline capable:** Full scoring without internet; sync on reconnect |
| NF-3 | **Runs anywhere:** Windows/macOS/Linux; single `python scripts/run_local.py` |
| NF-4 | **Credibility:** Checksum per delivery; recompute-from-delivery-log invariant; Law citations on rejections |
| NF-5 | **No silent failures:** Every action returns success/error |
| NF-6 | **Export everywhere:** JSON/CSV/PDF; data never locked in |
| NF-7 | **Atomic:** Each delivery is one transaction |

---

## 6. Data Model Summary

```
Match            id, name, venue, date, format, overs_per_innings, balls_per_over,
                 innings_count, toss_winner_team_id, toss_decision, status,
                 initiator_session_id, checksum, created_at, updated_at, locked_at,
                 team_a_name, team_b_name
AnonymousSession id, session_id (UUID), device_name (optional nickname), created_at, last_seen_at
MatchRole        match_id, session_id, role (initiator/scorer/watcher), scoring_rights,
                 approved_by_session_id, approved_at, created_at
Team             id, match_id, name, short_name
Player           id, team_id, name, role, jersey_number
PlayingXI        match_id, team_id, player_id, batting_order, is_keeper, is_captain
Innings          id, match_id, innings_number, batting_team_id, bowling_team_id,
                 target_runs, status, total_runs, total_wickets, overs_bowled,
                 result, result_margin
Over             id, innings_id, over_number, bowler_id, end, balls_valid, completed_at
Ball             id, innings_id, over_number, ball_number, striker_id, non_striker_id,
                 bowler_id, runs_batter, runs_extras, extra_type, penalty_runs,
                 is_wicket, dismissal_mode, fielder_id, short_runs, boundary_type,
                 is_free_hit, is_valid_ball, created_at
Wicket           id, ball_id, dismissal_mode, batter_out_id, fielder_id, bowler_credit_id,
                 not_out_batter_id, runs_at_fall, over_at_fall
Toss             id, match_id, initiator_call, coin_result, winner_team_id,
                 called_by_user_id, created_at
MVP              id, match_id, player_id, points, reason_summary, awarded_by, awarded_at
AuditLog         id, actor_user_id, action, match_id, target_id, timestamp, details
ScoreSnapshot    id, match_id, generated_at, payload_json, checksum
```

**Invariant:** `Innings.total_runs`, `total_wickets`, `overs_bowled` recomputed from `Ball` rows on read.


---

## 7. Scoring Engine — State Machine (per delivery)

1. Validate match/innings state (in progress; not locked)
2. Validate bowler (not consecutive overs, within max)
3. Validate striker (not out, at crease)
4. Classify delivery: No ball → Wide → valid ball
5. Apply runs (bat, boundary greater-of, byes/leg byes, penalty)
6. Apply wicket (validate legality vs NB/WD/free-hit; credit bowler/fielder; end-swap)
7. Update strike (odd runs, wicket, over)
8. Over completion (6 valid balls → swap ends, new bowler)
9. Innings completion → compute result
10. Commit atomically; recompute checksum; persist

---

## 8. API Endpoints Summary

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| GET | `/health` | No | Health check |
| POST | `/matches` | Yes | Create match with team names |
| GET | `/matches/{id}/public` | No | Public match summary |
| GET | `/matches/{id}` | Yes | Match detail |
| POST | `/matches/{id}/toss/call` | Yes (initiator) | Call heads/tails |
| POST | `/matches/{id}/toss/flip` | Yes (initiator) | Flip coin |
| GET | `/matches/{id}/toss` | No | Toss result |
| POST | `/matches/{id}/request-scoring` | Yes | Request scoring rights |
| GET | `/matches/{id}/scoring-requests` | Yes (initiator) | List requests |
| POST | `/matches/{id}/scoring-requests/{id}/approve\|reject` | Yes (initiator) | Approve/reject |
| POST | `/matches/{id}/balls` | Yes (scoring rights) | Record delivery |
| POST | `/matches/{id}/balls/{id}/undo` | Yes (scoring rights) | Undo delivery |
| GET | `/matches/{id}/scorecard` | Yes | Scorecard |
| GET | `/matches/{id}/checksum` | Yes | Integrity hash |
| POST | `/matches/{id}/confirm` | Yes (initiator) | Confirm scores |
| POST | `/matches/{id}/lock` | Yes (initiator) | Lock match |
| POST | `/matches/{id}/mvp/award` | Yes (scorer/initiator) | Award MVP |
| GET | `/matches/{id}/mvp` | No | View MVP |
| GET | `/matches/{id}/export/\|json\|csv\|pdf` | Yes | Export |
| POST | `/import/json` | Yes | Import |
| WS | `/ws/match/{id}` | Yes | Live broadcast |

---

## 9. Related Files

- `PLAN.md` — Product & technical plan (tech stack, deployment platforms, risks, roadmap)
- `IMPLEMENTATION_PLAN.md` — Granular task checklist (13 modules, definitions of done, execution order)
- `rulebook/` — Source PDFs: MCC Laws of Cricket, ICC T20/ODI/Test conditions

---

## 10. Change Control

Any change to the presumptions in Section 2 requires:
1. Written change request
2. Impact assessment on scoring rules and credibility
3. Update to this FUNCTIONAL_SPEC.md and PLAN.md
4. Test-suite update before implementation

---

*End of Functional Specification.*
