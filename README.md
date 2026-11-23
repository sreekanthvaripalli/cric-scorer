# Cric-Scorer — Offline-First Cricket Scorer for Gully / Club / School Cricket

**Zero-dollar, offline-capable, web-based cricket scoring application.** Built strictly on the [MCC Laws of Cricket (2017 Code, 4th Ed. 2026)](rulebook/) plus ICC T20 / ODI / Test playing conditions. No registration, no passwords, no ads, no tracking, no paid tiers. Runs locally with SQLite and deploys to free cloud tiers.

## 1. What Is This Project?

Cric-Scorer is a ball-by-ball cricket scoring application designed for cricketers who play casual, club, school, or "gully" cricket and cannot afford licensed scoring software.

### Core capabilities
- **Match creation** — anonymous, no authentication required; initiator sets team names, format, custom overs
- **Online toss** — heads/tails call → crypto-safe flip → winner chooses bat/field (mandatory before first ball)
- **Ball-by-ball scoring** — full Laws of Cricket validation (overs, extras, dismissals, strike rotation, max overs per bowler, consecutive-over prevention, boundary greater-of rule, short-run penalties)
- **Live watching** — public read-only scoreboard by Match ID via WebSocket or polling fallback
- **Scoring rights workflow** — request → initiator approve/reject → scorer records deliveries
- **Scorecard & result** — batting, bowling, extras, fall of wickets, match result per Law 16 (win by runs/wickets, tie, draw, conceded, awarded, Super Over, follow-on)
- **MVP determination** — auto-ranked candidates from delivery log; initiator/scorer awards MVP after match completion
- **Export/Import** — JSON, CSV, printable PDF scorecards; restore matches from JSON
- **PWA offline-first** — service worker caches shell; IndexedDB queues deliveries offline; syncs on reconnect
- **Match integrity** — cryptographic checksum after every delivery; undo last delivery; match lock after result confirmation
- **Audit log** — every scoring-rights change, lock/unlock, ownership transfer recorded

---

## 2. Who Is This For? (Audience)

| User | How they use the app |
|------|---------------------|
| **Gully / club / school cricketers** | Score matches on a phone at the ground; no internet needed; works in sunlight with big touch buttons |
| **Match initiator (captain / organiser)** | Creates match, invites scorer(s), approves scoring rights, confirms result, locks match, awards MVP |
| **Scorer** | Taps ball outcomes (0–6, NB, WD, Bye, Wicket, etc.); undoes mistakes; views live scorecard |
| **Watcher / umpire** | Opens a Match ID on any device; read-only live scoreboard; auto-updates via WebSocket or polling |
| **Anyone sharing a match** | Copies the Match ID link; friends/family watch from anywhere on any browser |

---

## 3. Tech Stack (Zero Dollar)

| Layer | Choice | Cost |
|-------|--------|------|
| Runtime | Python 3.10+ | $0 |
| Web framework | FastAPI | $0 |
| ORM / DB | SQLAlchemy + SQLite (default) | $0 |
| Cloud DB (optional) | PostgreSQL via `DATABASE_URL` (Supabase / Neon / Render free tier) | $0 (free tiers) |
| **Frontend** | **React 18+ + Vite** | **$0** |
| PWA | `vite-plugin-pwa` | $0 |
| PDF export | ReportLab | $0 |

---

## 4. How to Run Locally

### Prerequisites
- Python 3.10+
- `pip` available
- Node.js 18+ and `npm` (for React frontend)

### Step 1 — Clone / open the folder
```bash
cd /Users/ai/Documents/sourceCode/cric-scorer
```

### Step 2 — Install Python dependencies
```bash
pip install -r requirements.txt
```

### Step 3 — Install frontend dependencies
```bash
cd frontend
npm install
cd ..
```

### Step 4 — Start the backend server
```bash
python scripts/run_local.py
```
The server starts on **http://localhost:8000**.

### Step 5 — Start the frontend dev server
In a new terminal:
```bash
cd frontend
npm run dev
```
The frontend starts on **http://localhost:5173** (Vite default).

### Step 6 — Build frontend for production
When ready to deploy or test production build:
```bash
cd frontend
npm run build
```
Output goes to `frontend/dist/`. Serve via any static host or the FastAPI static file handler.

### Database note
`scripts/run_local.py` uses **in-memory SQLite** by default (`sqlite:///:memory:`). All match data is lost when the server stops or reloads — this is fine for throwaway testing, but **not for real matches you want to keep**.

To use persistent local storage instead, edit `scripts/run_local.py` and remove/comment the line:
```python
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
```
Then the app will fall back to file-based SQLite (`cric_scorer.db`) and your matches will persist across restarts.

### Step 7 — Use the app
1. Open **http://localhost:5173** (React frontend)
2. **Create a match** — enter team names, format (T20/ODI/Test/Custom), overs per innings
3. **Copy the Match ID** and share it with your scorer or watchers
4. **Toss** — initiator calls heads/tails → flip → winner chooses bat/field
5. **Scoring rights** — non-initiators request scoring rights; initiator approves/rejects
6. **Score** — tap 0–6, NB, WD, Bye, Wicket, Undo, Over Complete
7. **Watch** — open another device/browser with the Match ID for read-only live scoreboard
8. **Finish** → Confirm scores → Lock match → Award MVP → Export scorecard (JSON/CSV/PDF)

### Health check
```bash
curl http://localhost:8000/health
# → {"status": "ok"}
```

---

## 5. How to Deploy to Cloud (Free Tiers)

Cric-Scorer is designed so **local use never depends on the cloud**. Cloud is an optional sharing layer.

### ⚠️ Database: Do NOT use in-memory SQLite in deployment

The `scripts/run_local.py` script uses an **in-memory SQLite** database (`sqlite:///:memory:`) for local throwaway testing only. **This must never be used in a deployment environment** because:
- All match data is lost when the server process stops
- All match data is lost on code reload
- Each server instance gets an isolated database (no sharing across workers)

For any cloud deployment, set `DATABASE_URL` to a persistent database server:

```bash
# PostgreSQL (recommended for free-tier cloud deployment)
export DATABASE_URL=postgresql://user:pass@host:port/dbname

# Or file-based SQLite for single-device local production use
export DATABASE_URL=sqlite:///./cric_scorer.db
```

### Option A — Render (recommended free web service)

Deploy the FastAPI backend on Render, and the React frontend on Vercel or Netlify.

**Backend (Render):**
1. Push repo to GitHub
2. Create a **Web Service** on Render, connect the repo
3. Add environment variable: `DATABASE_URL` (free PostgreSQL add-on URL)
4. Build command: `pip install -r requirements.txt`
5. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
6. Your backend URL: `https://your-app.onrender.com`

**Frontend (Vercel or Netlify):**
1. Push `frontend/` folder to GitHub
2. Connect to Vercel/Netlify
3. Build command: `cd frontend && npm install && npm run build`
4. Publish directory: `frontend/dist`
5. Set environment variable: `VITE_API_BASE_URL=https://your-app.onrender.com`
6. Your frontend URL: `https://your-app.vercel.app`

**CORS:** Add your frontend URL to FastAPI CORS middleware in `app/main.py`.

### Option B — PythonAnywhere (beginner-friendly Python hosting)

1. Upload repo to PythonAnywhere
2. Set `DATABASE_URL` in environment variables (SQLite path or free PostgreSQL)
3. Configure WSGI to serve `app.main:app`
4. Access via your free `username.pythonanywhere.com` subdomain
5. Serve React `dist/` files as static files or host separately on Vercel/Netlify

### Option C — Supabase / Neon (free managed PostgreSQL)

1. Create a free PostgreSQL database on [Supabase](https://supabase.com) or [Neon](https://neon.tech)
2. Copy the connection string
3. Set `DATABASE_URL=<connection_string>` as an environment variable
4. Deploy the FastAPI backend to any host (Render, Koyeb, Fly.io, Oracle Cloud Always Free)
5. Deploy React frontend (`dist/`) to GitHub Pages, Netlify, Vercel, or Cloudflare Pages pointing at the backend API

### Recommended zero-dollar path
> **Develop locally with SQLite** (no deploy needed for solo/ground use).  
> **If sharing matches online:** deploy backend to Render/PythonAnywhere + Supabase/Neon free PostgreSQL, React frontend on Vercel/Netlify.

---

## 6. Project Structure (React Migration)

```
cric-scorer/
├── app/
│   ├── main.py              # FastAPI app + all route handlers
│   ├── models.py            # Pydantic request/response schemas
│   ├── database.py          # SQLAlchemy engine, session, ORM models
│   ├── websocket_manager.py # WebSocket connection manager
│   ├── scoring/
│   │   └── engine.py        # Core scoring state machine & Laws of Cricket validation
│   └── test.txt, test2.txt  # orphan files (safe to ignore)
├── frontend/
│   ├── index.html           # Vite entry point
│   ├── manifest.json        # PWA install manifest
│   ├── vite.config.js       # Vite config + PWA plugin
│   ├── package.json         # Frontend dependencies
│   ├── dist/                # Build output (gitignored)
│   └── src/
│       ├── main.jsx         # React app entry
│       ├── App.jsx          # Router + layout
│       ├── components/
│       │   ├── MatchCreate.jsx
│       │   ├── ScorerKeypad.jsx
│       │   ├── TossWidget.jsx
│       │   ├── WatcherPage.jsx
│       │   ├── Scorecard.jsx
│       │   └── MVPDisplay.jsx
│       ├── pages/
│       │   ├── HomePage.jsx        # Create match form
│       │   ├── MatchPage.jsx       # Match detail + scoring
│       │   └── WatchPage.jsx       # Read-only watcher
│       ├── hooks/
│       │   ├── useMatch.js
│       │   ├── useScoring.js
│       │   └── useWebSocket.js
│       ├── services/
│       │   └── api.js      # fetch wrappers for all API endpoints
│       ├── store/          # State management (Zustand or Context)
│       └── utils/          # Helper functions
├── scripts/
│   └── run_local.py         # Local launcher (port 8000, init_db)
├── rulebook/                # MCC Laws + ICC playing conditions PDFs
├── tests/
│   ├── conftest.py          # Pytest fixtures
│   ├── test_scoring_engine.py # 217 unit tests (dismissals, extras, overs, etc.)
│   └── test_api_integration.py # API integration tests
├── alembic/                 # DB migrations
├── requirements.txt         # Python dependencies
├── FUNCTIONAL_SPEC.md       # Binding functional specification (source of truth)
├── PLAN.md                  # Product & technical plan
├── IMPLEMENTATION_PLAN.md   # Granular task checklist (13 modules)
├── IMPLEMENTATION_TASKS.md  # Checklist format task list
├── .env.example             # Environment variables template
├── cric_scorer.db           # SQLite database (created on first run)
└── README.md                # This file

---


---

## 7. Functional Requirements Coverage (FUNCTIONAL_SPEC.md)

| Area | FR IDs | Status |
|------|--------|--------|
| Match initiation | FR-1.1 → FR-1.5 | ✅ Implemented |
| Users & scoring rights | FR-2.1 → FR-2.11 | ✅ Implemented |
| Online toss | FR-3.1 → FR-3.5 | ✅ Implemented |
| Ball-by-ball scoring | FR-4.1 → FR-4.16 | ✅ Implemented |
| Live watching | FR-5.1 → FR-5.5 | ✅ Implemented |
| Scorecard & result | FR-6.1 → FR-6.9 | ✅ Implemented |
| MVP determination | FR-7.1 → FR-7.5 | ✅ Implemented |
| Persistence & export | FR-8.1 → FR-8.6 | ✅ Implemented |
| PWA frontend | FR-9.1 → FR-9.8 | ✅ Implemented |
| Audit & security | FR-10.1 → FR-10.5 | ✅ Implemented |

---

## 8. API Endpoints (Quick Reference)

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| GET | `/health` | No | Health check |
| POST | `/matches` | No | Create match (initiator gets scoring rights) |
| GET | `/matches/{id}` | Yes | Match detail |
| GET | `/matches/{id}/public` | No | Public match summary |
| GET | `/matches` | No | List matches |
| POST | `/matches/{id}/toss/call` | Yes (initiator) | Call heads/tails |
| POST | `/matches/{id}/toss/flip` | Yes (initiator) | Flip coin, determine winner |
| GET | `/matches/{id}/toss` | No | Toss result |
| POST | `/matches/{id}/request-scoring` | Yes | Request scoring rights |
| GET | `/matches/{id}/scoring-requests` | Yes (initiator) | List pending requests |
| POST | `/matches/{id}/scoring-requests/{id}/approve\|reject` | Yes (initiator) | Approve/reject request |
| POST | `/matches/{id}/scoring-rights/revoke` | Yes (initiator) | Revoke scorer rights |
| POST | `/matches/{id}/transfer-ownership` | Yes (initiator) | Transfer match ownership |
| POST | `/matches/{id}/balls` | Yes (scoring rights) | Record a delivery |
| POST | `/matches/{id}/balls/{id}/undo` | Yes (scoring rights) | Undo last delivery |
| POST | `/matches/{id}/undo` | Yes (scoring rights) | Undo last delivery (alternate) |
| GET | `/matches/{id}/scorecard` | Yes | Full scorecard (recomputed from delivery log) |
| GET | `/matches/{id}/checksum` | Yes | Integrity hash |
| POST | `/matches/{id}/confirm` | Yes (initiator) | Confirm correctness of scores |
| POST | `/matches/{id}/lock` | Yes (initiator) | Lock match result |
| POST | `/matches/{id}/unlock` | Yes (initiator) | Unlock match (FR-10.2) |
| GET | `/matches/{id}/mvp/candidates` | Yes | Ranked MVP candidates |
| POST | `/matches/{id}/mvp/award` | Yes (scorer/initiator) | Award MVP (match must be completed/locked) |
| GET | `/matches/{id}/mvp` | No | View awarded MVP |
| GET | `/matches/{id}/export/json\|csv\|pdf` | Yes | Export match |
| POST | `/import/json` | Yes | Import match from JSON |
| WS | `/ws/match/{id}` | Yes | Live broadcast |
| GET | `/watch/{id}` | No | Read-only watcher HTML page |
| GET | `/index.html` | No | Scorer + match page |

---

## 9. Testing

The project includes **217 passing unit and integration tests**.

### Run all tests
```bash
pip install -r requirements.txt
python -m pytest tests/ -v
```

### Test coverage areas
- Valid runs 0–6; invalid runs rejected
- All 10 dismissal modes × (normal / No ball / Wide / free-hit) matrix with Laws 21.17 / 22.9 validation
- Extra types: NB, WD, Bye, Leg bye, Penalty
- Short runs (unintentional vs deliberate 5-run penalty)
- Boundary greater-of rule (Law 19.7)
- Over counting: NB/WD don't count; 6 valid balls complete an over
- Max overs per bowler (T20: 4, ODI: 10, Test: unlimited, Custom: overs ÷ 5)
- Consecutive-over prevention (Law 17.6)
- Strike rotation on odd runs / after wicket / after over
- Match status transitions: created → in_progress → completed → locked
- Checksum recomputed after every delivery
- Scoring rights enforcement (403 for unauthorised)
- Rate limiting (429 after threshold)
- Offline PWA assets load correctly

### Laws of Cricket covered
- **Law 17** — Over = 6 valid balls; NB/WD don't count; no consecutive overs by same bowler
- **Law 18** — Runs, byes, leg-byes, penalty runs, short runs (unintentional vs deliberate 5-run penalty)
- **Law 19** — Boundary 4/6 greater-of rule
- **Law 21** — No ball (+1 penalty, not in over, sets free hit, limited dismissals)

---

## 10. Module 11 — Deployment Checklist

The following items from **Module 11** (Deployment, $0 platforms) must be completed for a production-ready release:

### [ ] 11.1 — Verify `scripts/run_local.py` on Windows/macOS/Linux
- [ ] Test `python scripts/run_local.py` starts the server on each OS
- [ ] Confirm port 8000 is used (not 8080)
- [ ] Confirm `init_db()` runs on startup
- [ ] Confirm `GET /health` returns `{"status":"ok"}`

### [ ] 11.2 — Render deploy
- [ ] Push repo to GitHub
- [ ] Create Render Web Service
- [ ] Set `DATABASE_URL` (SQLite path or free PostgreSQL add-on)
- [ ] Set build command: `pip install -r requirements.txt`
- [ ] Set start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- [ ] Verify live URL works end-to-end (create match → score → watch → export)

### [ ] 11.3 — PythonAnywhere deploy
- [ ] Upload repo to PythonAnywhere
- [ ] Set `DATABASE_URL` environment variable
- [ ] Configure WSGI for `app.main:app`
- [ ] Verify free subdomain works

### [ ] 11.4 — Supabase / Neon free PostgreSQL
- [ ] Create free PostgreSQL database
- [ ] Copy connection string
- [ ] Set `DATABASE_URL=<connection_string>` in deployment env
- [ ] Verify cloud DB connects and stores match data

### [ ] 11.5 — Optional static frontend (GitHub Pages / Netlify / Vercel)
- [ ] Host `frontend/` as static site
- [ ] Point API calls at deployed backend URL
- [ ] Verify PWA install works


---

## 12. Contributing

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Implement changes following the Laws of Cricket in `rulebook/`
4. Add unit tests in `tests/test_scoring_engine.py`
5. Run `python -m pytest tests/ -v` (all 217+ tests must pass)
6. Submit a pull request

---

## 13. License

MIT License. Free forever. No ads, no tracking, no paid tiers.

---

**Built for gully cricket, by cricketers.** 🏏
### [ ] 11.6 — README documentation (this file)
- [ ] Step-by-step local run instructions ✅ (Section 4)
- [ ] Cloud deploy instructions ✅ (Section 5)
- [ ] Module 11 deployment checklist ✅ (this section)

---

## 11. Known Implementation Gaps (Tracked in FUNCTIONAL_SPEC.md §11)

See `FUNCTIONAL_SPEC.md` Section 11 for the full tracking table. Items still open:

| FR | Requirement | Gap |
|----|-------------|-----|
| FR-4.10 | Deliberate short-run 5-run penalty | Engine logic implemented; no dedicated UI checkbox yet |
| FR-6.5 | Draw / Conceded / Awarded result types | Model columns exist; `compute_match_result` returns manually-set results; no API endpoint to set them yet |
| — | `ScoreSnapshot` table | Exists in schema but not yet populated (point-in-time audit snapshots) |
- **Law 22** — Wide (+1 penalty, not in over, limited dismissals)
- **Law 23** — Byes / leg-byes not debited to bowler
- **Law 32–40** — All 10 dismissal modes with legality validation vs NB/WD/free-hit
- **Law 16** — Match result: win by runs/wickets, tie, draw, conceded, awarded, Super Over, follow-on
- **Law 2.15 / 3.2** — Match checksum for scorer-umpire reconciliation
- **Law 16.6** — Winning-hit rule
### Option A — Render (recommended free web service)
1. Push code to GitHub
2. Create a **Web Service** on Render, connect the repo
3. Add environment variable: `DATABASE_URL=sqlite:///./cric_scorer.db` (or free PostgreSQL add-on URL)
4. Build command: `pip install -r requirements.txt`
5. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
6. Your match URLs are now shareable: `https://your-app.onrender.com`

### Option B — PythonAnywhere (beginner-friendly Python hosting)
1. Upload the repo to PythonAnywhere
2. Set `DATABASE_URL` in environment variables (SQLite path or free PostgreSQL)
3. Configure WSGI to serve `app.main:app`
4. Access via your free `username.pythonanywhere.com` subdomain

### Option C — Supabase / Neon (free managed PostgreSQL)
1. Create a free PostgreSQL database on [Supabase](https://supabase.com) or [Neon](https://neon.tech)
2. Copy the connection string
3. Set `DATABASE_URL=<connection_string>` as an environment variable
4. Deploy the backend to any host (Render, Koyeb, Fly.io, Oracle Cloud Always Free)
5. The frontend (pure HTML/JS/CSS) can be hosted on GitHub Pages, Netlify, Vercel, or Cloudflare Pages pointing at the backend API

### Recommended zero-dollar path
> **Develop locally with SQLite** (no deploy needed for solo/ground use).  
> **If sharing matches online:** deploy backend to Render/PythonAnywhere + Supabase/Neon free PostgreSQL, frontend on GitHub Pages.
| Realtime | FastAPI WebSockets | $0 |
| Tests | pytest | $0 |