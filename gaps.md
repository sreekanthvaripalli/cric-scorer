I have completed a comprehensive audit of the project repository, reading its directory structure, files, backend code, frontend assets, database migrations, and test suites, and cross-referencing every component against [FUNCTIONAL_SPEC.md](file:///Users/ai/Documents/sourceCode/cric-scorer/FUNCTIONAL_SPEC.md).

---

### Executive Summary

| Overall Compliance Status | **Non-Compliant / Incomplete** |
| :--- | :--- |
| **Modules Planned** | 13 Modules (Checklist marked 100% complete in `IMPLEMENTATION_TASKS.md`) |
| **Actual Status** | **Critical gaps, syntax errors, and runtime defects across backend, frontend, scoring engine, and tests.** |
| **Runnable State** | The backend starts, but multiple critical routes crash with `NameError` or `AttributeError`. Frontend JS files contain syntax errors, DOM mismatches, and are not served by FastAPI. |

While the project has scaffolded models and routes, **the implementation does not correctly satisfy the Functional Specification**. Several features return hardcoded mock values, omit core Laws of Cricket (Laws 17, 18, 19, 21, 22, 23, 32–40), lack specified data models, and fail integration tests.

---

### 1. Project Folder Structure & File Inventory

```
cric-scorer/
├── app/
│   ├── api/                          # [EMPTY] Intended for modular routers; all routes are in main.py
│   ├── database.py                   # SQLAlchemy Base, connection engine, models & scoped session
│   ├── main.py                       # FastAPI application & all route handlers (1,418 lines)
│   ├── models.py                     # Pydantic request & response schemas
│   ├── websocket_manager.py          # WebSocket ConnectionManager for live broadcasting
│   ├── scoring/
│   │   ├── __init__.py
│   │   └── engine.py                 # Core scoring state machine & scorecard calculations
│   ├── test.txt, test2.txt           # [ORPHAN] 0-byte and dummy leftover files
├── frontend/
│   ├── index.html                    # Match & Toss UI (missing match creation & scorer keypad)
│   ├── watch.html                    # Public watcher template (links to unmounted /static/ assets)
│   ├── manifest.json                 # PWA manifest (references non-existent /icons/icon-*.png)
│   ├── sw.js                         # Service Worker shell caching & offline sync logic
│   ├── css/
│   │   ├── global.css                # Base theme & layout styles
│   │   ├── live.css                  # Watcher & scorecard styles
│   │   └── toss.css                  # Toss coin flip & call styles
│   └── js/
│       ├── live.js                   # [SYNTAX ERROR] Live watch controller with dangling code
│       ├── scorer.js                 # [SYNTAX ERROR & BROKEN DOM] Scorer touch controller
│       ├── toss.js                   # Three-phase toss flow handler
│       └── watch.js                  # [SYNTAX ERROR] Unescaped quote syntax errors
├── alembic/
│   ├── env.py, alembic.ini           # Alembic configuration
│   └── versions/
│       ├── d51b8285cf56_initial_migration_with_all_tables.py
│       └── 13ml13mvp_add_mvp_model.py
├── tests/
│   ├── conftest.py                   # Pytest fixtures (DB override incomplete)
│   ├── test_scoring_engine.py        # 217 unit tests (hangs on 9999 overs loop, duplicated tests)
│   └── test_api_integration.py       # API integration tests (fails on 429 rate limit & missing tables)
├── scripts/
│   └── run_local.py                  # Local launch script (runs port 8080 instead of 8000, omits init_db)
├── rulebook/                         # Source PDFs and txt files for MCC Laws and ICC playing conditions
├── requirements.txt                  # Python dependencies
├── FUNCTIONAL_SPEC.md                # Binding functional specification (source of truth)
├── IMPLEMENTATION_PLAN.md            # Modular architecture definition
├── IMPLEMENTATION_TASKS.md           # Implementation task checklist
└── README.md                         # [INCOMPLETE] Missing local run and deployment docs
```

---

### 2. Detailed Compliance Audit against Functional Specification

#### Section 4.1 — Match Initiation (FR-1.1 to FR-1.5)
- **Status:** **Partial / Defective**
- **Findings:**
  1. **Custom Overs Restriction:** FR-1.1 and FR-1.5 mandate custom overs to be any positive integer (e.g. 1-over Super Over or 2-over club match). However, [app/models.py#L37-L39](file:///Users/ai/Documents/sourceCode/cric-scorer/app/models.py#L37-L39) enforces `overs_per_innings = Field(20, ge=5, le=500)`, causing valid small overs matches to be rejected with a 422 error.
  2. **Missing Teams Initialization:** When a match is initiated with `team_a_name` and `team_b_name`, no corresponding entries in `teams` or `match_team_links` are created, causing subsequent scorecard/result endpoints that look up `MatchTeamLink` to fail or fallback to hardcoded IDs `1` and `2`.
  3. **Missing Detail Route:** `GET /matches/{id}` (FR-1.3, Section 8) is defined in the specification table but completely absent from [app/main.py](file:///Users/ai/Documents/sourceCode/cric-scorer/app/main.py).

#### Section 4.2 — Users & Scoring Rights (FR-2.1 to FR-2.11)
- **Status:** **Partial**
- **Findings:**
  1. **Pending Requests Missing Device Name:** In `GET /matches/{match_id}/scoring-requests` ([app/main.py#L431](file:///Users/ai/Documents/sourceCode/cric-scorer/app/main.py#L431)), `device_name` is hardcoded to `None` instead of querying the `AnonymousSession.device_name` requested per FR-2.5.
  2. **MatchRole Creation Constraint:** In [app/database.py#L136](file:///Users/ai/Documents/sourceCode/cric-scorer/app/database.py#L136), `MatchRole.created_at` has `nullable=False` without a column default. In some handlers ([app/main.py#L312](file:///Users/ai/Documents/sourceCode/cric-scorer/app/main.py#L312)), `created_at` was omitted, causing database insertion constraints to fail.

#### Section 4.3 — Online Toss (FR-3.1 to FR-3.5)
- **Status:** **Partial**
- **Findings:**
  1. **Hardcoded Team IDs on Flip:** In `POST /matches/{id}/toss/flip` ([app/main.py#L676](file:///Users/ai/Documents/sourceCode/cric-scorer/app/main.py#L676)), the winner team is hardcoded to `1 if is_match else 2`. If auto-increment team IDs are anything other than 1 and 2, this breaks team linkage.
  2. **Non-Standard Status Transition:** Line 725 sets `match.status = 'toss_complete'`, whereas FR-1.4 specifies the sequence `created → in_progress (after toss) → completed → locked`.

#### Section 4.4 — Ball-by-Ball Scoring Engine (FR-4.1 to FR-4.16)
- **Status:** **Non-Compliant / Critical Errors**
- **Findings:**
  1. **Severe Bowler Validation Bug:** In [app/scoring/engine.py#L75-L88](file:///Users/ai/Documents/sourceCode/cric-scorer/app/scoring/engine.py#L75-L88), the engine checks consecutive overs and max overs using `request.striker_id` instead of `request.bowler_id`:
     ```python
     last_bowler_ball = db.query(Ball).filter(Ball.bowler_id == request.striker_id)...
     current_overs_bowled = _get_bowler_overs_bowled(db, request.striker_id, match.id)
     ```
     This causes the engine to evaluate whether the *batter* bowled the previous over and rejects valid deliveries whenever a batter's ID matches a previous bowler.
  2. **Mocked Response Data:** In [app/scoring/engine.py#L166-L168](file:///Users/ai/Documents/sourceCode/cric-scorer/app/scoring/engine.py#L166-L168), `process_ball` returns **hardcoded mock values**:
     ```python
     current_score='15/2',
     current_overs=0.0,
     wickets=2,
     ```
     Every delivery response returns score `15/2` regardless of what was scored.
  3. **Absence of Dismissal Legality Rules (FR-4.12, Laws 21.17, 22.9, 32–40):** `process_ball` performs zero legality validation on dismissals. It allows Bowled, Caught, LBW, Stumped, and Hit Wicket on No-balls, Wides, and Free-hits without checking the Laws.
  4. **Strike Rotation Omitted (FR-4.13, Laws 18.11–18.13):** The engine does not swap strikers on odd runs or at the end of an over.
  5. **Boundary Greater-Of Rule Omitted (FR-4.11, Law 19.7):** The engine does not enforce the greater-of rule between completed runs and boundary allowances.
  6. **Static Integrity Checksum (FR-4.16, P12):** [app/scoring/engine.py#L21-L23](file:///Users/ai/Documents/sourceCode/cric-scorer/app/scoring/engine.py#L21-L23) hashes only `[match.id, match.status, match.balls_per_over, match.overs_per_innings]`. The checksum never changes when deliveries are recorded or undone, rendering the match integrity checksum useless.
  7. **Runtime Crash on `POST /balls`:** In [app/main.py#L474](file:///Users/ai/Documents/sourceCode/cric-scorer/app/main.py#L474), the route executes:
     ```python
     str(response.get("ball_id", "")), '{"delivery_type": "%s"}' % ball_data.delivery_type
     ```
     `response` is a Pydantic `BallsResponse` (not a dict, causing `AttributeError: 'BallsResponse' object has no attribute 'get'`), and `ball_data` has no `delivery_type` attribute. Every ball recorded triggers a 400 rollback error.

#### Section 4.5 — Live Score Broadcasting (FR-5.1 to FR-5.5)
- **Status:** **Non-Compliant**
- **Findings:**
  1. **Broadcast Never Triggered (FR-5.1, FR-5.2):** `manager.broadcast` is only called once when a client connects to the WebSocket ([app/main.py#L830](file:///Users/ai/Documents/sourceCode/cric-scorer/app/main.py#L830)). It is **never called** when a ball is bowled, undone, or when match status changes.
  2. **Hardcoded Public Match Summary (FR-5.3):** In [app/main.py#L287](file:///Users/ai/Documents/sourceCode/cric-scorer/app/main.py#L287), `GET /matches/{id}/public` hardcodes:
     ```python
     current_score="0/0", current_overs=0.0, wickets=0
     ```
  3. **Broken Polling Fallback (FR-5.4):** In [app/main.py#L747-L759](file:///Users/ai/Documents/sourceCode/cric-scorer/app/main.py#L747-L759), `GET /matches/{id}/live` computes total match score by summing only the **last 10 balls**, discarding the rest of the innings.
  4. **Missing HTML Watch Route (FR-5.2):** `GET /watch/{id}` is not routed in FastAPI.

#### Section 4.6 — Scorecard & Results (FR-6.1 to FR-6.9)
- **Status:** **Non-Compliant**
- **Findings:**
  1. **Invalid Bowling Analysis Overs Math:** In [app/scoring/engine.py#L281](file:///Users/ai/Documents/sourceCode/cric-scorer/app/scoring/engine.py#L281):
     ```python
     entry["overs_count"] += b.ball_number / 6.0
     ```
     This adds `ball_number / 6.0` on every delivery, accumulating `(1+2+3+4+5+6)/6 = 3.5` overs for a single 6-ball over.
  2. **Illegal Bowler Debits (Law 23 & Law 18.6):** Line 282 debits byes, leg-byes, and penalties to the bowler's runs conceded.
  3. **Illegal Wicket Credits (Law 38):** Line 283 credits run-outs to the bowler.
  4. **Invalid Match Result Overs:** In [app/scoring/engine.py#L393-L396](file:///Users/ai/Documents/sourceCode/cric-scorer/app/scoring/engine.py#L393-L396), team overs are calculated as the *average* of ball coordinates across deliveries instead of counting completed overs and balls.
  5. **Crash on Follow-on Calculation:** [app/scoring/engine.py#L509](file:///Users/ai/Documents/sourceCode/cric-scorer/app/scoring/engine.py#L509) accesses `match.follow_on_threshold`. That field only exists on `FormatConfig`, causing an `AttributeError`.
  6. **Missing Endpoint:** `POST /matches/{id}/confirm` (FR-6.9, Section 8) is missing from [app/main.py](file:///Users/ai/Documents/sourceCode/cric-scorer/app/main.py).

#### Section 4.7 — MVP Determination (FR-7.1 to FR-7.5)
- **Status:** **Broken at Runtime**
- **Findings:**
  1. In [app/main.py#L1232](file:///Users/ai/Documents/sourceCode/cric-scorer/app/main.py#L1232), `get_mvp_candidates` executes `squad_map[sq.player_id] = sq.team_role`.
  2. `MatchSquad` has no `team_role` column (`team_role` belongs to `MatchTeamLink`). Calling `GET /matches/{id}/mvp/candidates` raises an unhandled `AttributeError`.

#### Section 4.8 — Persistence, Export & Import (FR-8.1 to FR-8.6)
- **Status:** **Broken at Runtime**
- **Findings:**
  1. **Missing Name Imports in `main.py`:**
     - `StreamingResponse` ([app/main.py#L1081, #L1172](file:///Users/ai/Documents/sourceCode/cric-scorer/app/main.py#L1081)) is not imported from `fastapi.responses`.
     - `io` ([app/main.py#L1009, #L1172](file:///Users/ai/Documents/sourceCode/cric-scorer/app/main.py#L1009)) is not imported.
     - `os` and `shutil` ([app/main.py#L1194-L1197](file:///Users/ai/Documents/sourceCode/cric-scorer/app/main.py#L1194-L1197)) are not imported.
     - `compute_checksum` ([app/main.py#L508, #L528](file:///Users/ai/Documents/sourceCode/cric-scorer/app/main.py#L508)) is not imported from `app.scoring.engine`.
     - Calling `/export/pdf`, `/export/csv`, `/undo`, or `_backup_db` crashes with `NameError`.
  2. **Import Crash:** In [app/main.py#L974](file:///Users/ai/Documents/sourceCode/cric-scorer/app/main.py#L974), `import_match_json` instantiates `Player(match_id=..., is_substitute=...)`. `Player` does not have those arguments, causing a `TypeError`.

#### Section 4.9 — PWA Frontend (FR-9.1 to FR-9.8)
- **Status:** **Non-Functional**
- **Findings:**
  1. **FastAPI Does Not Mount Static Files:** No `app.mount("/static", ...)` or root static file handler exists in [app/main.py](file:///Users/ai/Documents/sourceCode/cric-scorer/app/main.py). Requests to `/index.html`, `/watch.html`, `/manifest.json`, `/sw.js`, `/css/*`, and `/js/*` return 404.
  2. **JavaScript Syntax Errors:**
     - [frontend/js/live.js#L227-L230](file:///Users/ai/Documents/sourceCode/cric-scorer/frontend/js/live.js#L227-L230): Dangling code after module closing (`})(); fallbackToPolling(); } }`) prevents parsing.
     - [frontend/js/scorer.js#L1](file:///Users/ai/Documents/sourceCode/cric-scorer/frontend/js/scorer.js#L1): Starts with `/"` instead of `/**`, causing an `Invalid regular expression` syntax error.
     - [frontend/js/watch.js#L91, #L95, #L98, #L101-106](file:///Users/ai/Documents/sourceCode/cric-scorer/frontend/js/watch.js#L91): Unescaped double quotes inside double-quoted string literals (`"Runs: <span class="ball-runes">..."`) prevent script evaluation.
  3. **Broken Scorer Keypad:** [frontend/index.html](file:///Users/ai/Documents/sourceCode/cric-scorer/frontend/index.html) does not include the scoring buttons (`#btn-0` to `#btn-6`, `#btn-nb`, `#btn-undo`, etc.) or link `scorer.js`. [frontend/js/scorer.js](file:///Users/ai/Documents/sourceCode/cric-scorer/frontend/js/scorer.js) immediately throws `TypeError: Cannot read properties of null` upon loading.
  4. **Mismatched Scorer Payload:** [frontend/js/scorer.js#L98](file:///Users/ai/Documents/sourceCode/cric-scorer/frontend/js/scorer.js#L98) posts `{ delivery_type: "..." }`, while the backend requires `bowler_id`, `striker_id`, `non_striker_id`, `over_number`, and `ball_number`.
  5. **Missing PWA Icons:** [frontend/manifest.json](file:///Users/ai/Documents/sourceCode/cric-scorer/frontend/manifest.json) references `/icons/icon-192.png` and `/icons/icon-512.png`, which do not exist in the repository.

#### Section 6 — Data Model Summary
- **Status:** **Divergent from Specification**
- **Findings:**
  The following tables defined in Section 6 are completely missing:
  - **`Innings` Table:** Missing. The app stores an integer `innings_id` on `Ball`, but has no table tracking target runs, status, batting team ID, bowling team ID, total runs, total wickets, or result margins.
  - **`Over` Table:** Missing (`id, innings_id, over_number, bowler_id, end, balls_valid, completed_at`).
  - **`Wicket` Table:** Missing (`id, ball_id, dismissal_mode, batter_out_id, fielder_id, bowler_credit_id, not_out_batter_id, runs_at_fall, over_at_fall`).
  - **`ScoreSnapshot` Table:** Missing (`id, match_id, generated_at, payload_json, checksum`).
  - **`Match` Table:** Omitted `innings_count`, `toss_winner_team_id`, and `toss_decision` from the `Match` model.

#### Section 4.10 / Module 10 — Testing & QA
- **Status:** **Failing Test Suite**
- **Findings:**
  1. **Database Session Fixture Disconnect:** [tests/conftest.py](file:///Users/ai/Documents/sourceCode/cric-scorer/tests/conftest.py) defines an in-memory `test_engine` but fails to override FastAPI's `get_db` dependency. Requests hitting FastAPI endpoints query uninitialized databases or fail with `OperationalError: no such table: matches/anonymous_sessions`.
  2. **Rate Limiter Test Poisoning:** `test_rate_limit_enforcement` sends 110 requests, exhausting the IP rate limit for `testclient` and causing all subsequent integration tests to fail with `429 Too Many Requests`.
  3. **Test Suite Hang:** In [tests/test_scoring_engine.py#L325](file:///Users/ai/Documents/sourceCode/cric-scorer/tests/test_scoring_engine.py#L325), `test_max_overs_per_bowler[Test-9999]` attempts to create and commit `9,999 * 6 = 59,994` deliveries sequentially inside a single test, hanging pytest.
  4. **Duplicated Tests:** [tests/test_scoring_engine.py#L653-L715](file:///Users/ai/Documents/sourceCode/cric-scorer/tests/test_scoring_engine.py#L653-L715) contains 5 identical duplicate definitions of `test_scoring_rights_required`.

---

### 3. Summary of Discrepancies Matrix

| Component | Functional Spec Requirement | Current Implementation | Verdict |
| :--- | :--- | :--- | :--- |
| **Data Models** | `Innings`, `Over`, `Wicket`, `ScoreSnapshot` tables | Only `Match`, `Ball`, `Toss`, `Player`, `Team`, `MatchRole`, `MVP`, `AuditLog` | **Non-compliant** |
| **Scoring Engine** | Validate consecutive overs & max overs by bowler | Validates `striker_id` instead of `bowler_id` | **Critical Bug** |
| **Delivery Response** | Current score recomputed dynamically from deliveries | Hardcodes `current_score='15/2', wickets=2` | **Critical Bug** |
| **Dismissal Rules** | Laws 21.17, 22.9, 32–40 (legality on NB/WD/Free-hit) | Zero legality validation in `process_ball` | **Non-compliant** |
| **Bowling Analysis** | Cricket overs notation, maidens, economy, extras | `overs += ball_num/6` (3.5 ov/over), debits byes/runouts to bowler | **Critical Bug** |
| **Public Live Score** | Match summary via `GET /matches/{id}/public` | Hardcodes `"0/0", overs=0.0, wickets=0` | **Non-compliant** |
| **Live Broadcast** | WS broadcast on ball, undo, and result change | Broadcast only called once on WS connect | **Non-compliant** |
| **Export Endpoints** | PDF and CSV export | Missing `StreamingResponse` and `io` imports (`NameError`) | **Runtime Crash** |
| **Frontend UI** | Scorer keypad (0-6, NB, WD, Wicket), PWA Shell | Missing HTML keypad, unmounted static files, 3 JS files with syntax errors | **Non-compliant** |
| **Test Suite** | Passing unit & integration tests | 11 failed tests, 1 error, and 1 infinite loop | **Failing** |

---

### 4. Recommended Next Steps

1. **Resolve Critical Backend Imports & Exceptions:**
   - Add missing imports to [app/main.py](file:///Users/ai/Documents/sourceCode/cric-scorer/app/main.py): `from fastapi.responses import StreamingResponse`, `import io, os, shutil`, and `from app.scoring.engine import compute_checksum`.
   - Fix the `response.get` and `ball_data.delivery_type` attribute errors in `record_ball`.
   - Fix `MatchSquad.team_role` in `get_mvp_candidates`.
   - Fix `Player` keyword arguments in `import_match_json`.
2. **Correct Scoring Engine Rules (`engine.py`):**
   - Change `request.striker_id` checks to `request.bowler_id` for consecutive overs and max overs.
   - Implement dynamic recomputation of innings score, overs, and wickets in `_build_response` instead of hardcoding `'15/2'`.
   - Add dismissal legality checks against No-balls, Wides, and Free-hits.
   - Implement correct overs computation for bowling analysis and match results.
   - Expand `compute_checksum` to hash all delivery IDs and running totals.
3. **Mount and Repair Frontend:**
   - Mount static directories in [app/main.py](file:///Users/ai/Documents/sourceCode/cric-scorer/app/main.py) (`app.mount("/static", StaticFiles(...))` and serve `index.html` / `watch.html`).
   - Fix syntax errors in [frontend/js/live.js](file:///Users/ai/Documents/sourceCode/cric-scorer/frontend/js/live.js), [frontend/js/scorer.js](file:///Users/ai/Documents/sourceCode/cric-scorer/frontend/js/scorer.js), and [frontend/js/watch.js](file:///Users/ai/Documents/sourceCode/cric-scorer/frontend/js/watch.js).
   - Add the scorer keypad HTML into [frontend/index.html](file:///Users/ai/Documents/sourceCode/cric-scorer/frontend/index.html) and align the JSON payload sent by `scorer.js` with `BallRecordRequest`.
4. **Fix Test Suite (`conftest.py` & `test_*.py`):**
   - Override `get_db` dependency in [tests/conftest.py](file:///Users/ai/Documents/sourceCode/cric-scorer/tests/conftest.py) so endpoints use the test database session.
   - Replace the 9,999 overs loop in `test_max_overs_per_bowler` with a reasonable Test format limit.
   - Reset `_rate_limit_store` between tests to avoid cascading 429 errors.