import io
import os
import shutil
import uuid
import secrets
import json
from time import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func, desc, and_, or_
from sqlalchemy.orm import Session

from .database import (
    AnonymousSession, Match, MatchRole, Base, get_session_local, init_db,
    Team, Player, MatchTeamLink, MatchSquad, PlayingXI, Toss, FormatConfig,
    Ball, AuditLog, MVP, DATABASE_URL, Innings, Over, Wicket, ScoreSnapshot,
)
from .websocket_manager import manager
from .scoring.engine import (
    compute_checksum, process_ball, compute_full_scorecard, compute_match_result,
    compute_follow_on, compute_super_over,
)
from .models import (
    AnonymousSessionCreate, AnonymousSessionResponse, MatchCreate,
    MatchResponse, MatchPublicResponse, MatchRoleCreate, MatchRoleResponse,
    ScoringRightRequestCreate, ScoringRightRequestResponse, BallRecord,
    BallRecordRequest, BallRecordResponse, ConfirmScoresRequest, LockMatchRequest,
    MvpAwardRequest, TeamResponse, PlayerResponse, MatchTeamLinkResponse,
    MatchSquadResponse, PlayingXIResponse, TossResponse, FormatConfigResponse,
    TeamData, Player as PlayerRequest, XIEntry, TossCallData, TossFlipData,
    TossResultData, BattingScorecardEntry, BowlingAnalysisEntry, ExtrasSummary,
    FallOfWicketEntry, InningsScorecard, MatchScorecard, MatchResult,
    FollowOnStatus, SuperOverStatus, LockMatchResponse, MVPPointsBreakdown,
    MVPCandidate, MVPResponse,
)

app = FastAPI(title="Cric-Scorer API", version="0.0.1")

# ── Module 9: Rate Limiting Middleware ──
_rate_limit_store: dict = defaultdict(list)
RATE_LIMIT_REQUESTS = 100  # max requests per window
RATE_LIMIT_WINDOW = 60  # seconds


def reset_rate_limits():
    """Clear rate limit store (used in testing)."""
    _rate_limit_store.clear()


def get_client_ip(request: Request) -> str:
    """Extract client IP from request, considering proxies."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Allow test client or bypass header
    if request.headers.get("X-Test-Client") == "true":
        return await call_next(request)

    client_ip = get_client_ip(request)
    now = time()
    # Clean old entries
    _rate_limit_store[client_ip] = [t for t in _rate_limit_store[client_ip] if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_limit_store[client_ip]) >= RATE_LIMIT_REQUESTS:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Try again later."},
        )
    _rate_limit_store[client_ip].append(now)
    response = await call_next(request)
    return response


@app.on_event("startup")
def on_startup():
    """Ensure database tables exist on startup."""
    init_db()


def get_db():
    db = get_session_local()
    try:
        yield db
    finally:
        db.close()


async def get_current_session(request: Request, db = Depends(get_db)) -> AnonymousSession:
    session_id = request.cookies.get("session_id")
    if not session_id:
        session_id = str(uuid.uuid4())
        db_session = AnonymousSession(session_id=session_id)
        db.add(db_session)
        db.commit()
        db.refresh(db_session)
    else:
        stmt = select(AnonymousSession).where(AnonymousSession.session_id == session_id)
        result = db.execute(stmt)
        db_session = result.scalar_one_or_none()
        if db_session is None:
            db_session = AnonymousSession(session_id=session_id)
            db.add(db_session)
            db.commit()
            db.refresh(db_session)
    return db_session


def audit_log(db, actor_session_id: str, action: str, match_id: int = None, target_id: str = None, details: str = None):
    """Create an audit log entry."""
    entry = AuditLog(
        actor_session_id=actor_session_id,
        action=action,
        match_id=match_id,
        target_id=target_id,
        details=details,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(entry)
    db.commit()
    return entry


# ── Frontend Static Files & Pages ──
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


@app.get("/", response_class=FileResponse)
def root_index():
    return FileResponse(os.path.join(frontend_dir, "index.html"))


@app.get("/index.html", response_class=FileResponse)
def index_page():
    return FileResponse(os.path.join(frontend_dir, "index.html"))


@app.get("/watch/{match_id}", response_class=FileResponse)
def watch_match_page(match_id: int):
    return FileResponse(os.path.join(frontend_dir, "watch.html"))


@app.get("/watch.html", response_class=FileResponse)
def watch_html_page():
    return FileResponse(os.path.join(frontend_dir, "watch.html"))


@app.get("/manifest.json", response_class=FileResponse)
def manifest_json():
    return FileResponse(os.path.join(frontend_dir, "manifest.json"))


@app.get("/sw.js", response_class=FileResponse)
def service_worker():
    return FileResponse(os.path.join(frontend_dir, "sw.js"), media_type="application/javascript")


@app.get("/css/{file_name}")
def css_route(file_name: str):
    fpath = os.path.join(frontend_dir, "css", file_name)
    if os.path.exists(fpath):
        return FileResponse(fpath, media_type="text/css")
    raise HTTPException(status_code=404, detail="File not found")


@app.get("/js/{file_name}")
def js_route(file_name: str):
    fpath = os.path.join(frontend_dir, "js", file_name)
    if os.path.exists(fpath):
        return FileResponse(fpath, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="File not found")


# ── Module 13: MVP Points Algorithm ──

def _get_player_name_map(db, match_id: int):
    squads = db.query(MatchSquad).filter(MatchSquad.match_id == match_id).all()
    result = {}
    for squad in squads:
        player = db.query(Player).filter(Player.id == squad.player_id).first()
        if player:
            result[player.id] = (player.name, player.team_id)
    return result


def calculate_mvp_points(db, match_id: int):
    balls = db.query(Ball).filter(Ball.match_id == match_id).all()
    player_map = _get_player_name_map(db, match_id)
    stats = {}

    def get_or_create(pid):
        if pid not in stats:
            name, team_id = player_map.get(pid, (f"Player {pid}", 0))
            stats[pid] = {
                "player_id": pid, "name": name, "team_id": team_id,
                "runs": 0, "balls_faced": 0, "fours": 0, "sixes": 0,
                "wickets": 0, "catches": 0, "run_outs": 0,
                "balls_bowled": 0, "runs_conceded": 0, "extras_conceded": 0,
            }
        return stats[pid]

    for b in balls:
        s = get_or_create(b.striker_id)
        s["runs"] += b.runs_batter
        if b.is_valid_ball:
            s["balls_faced"] += 1
        if b.boundary_type == "4":
            s["fours"] += 1
        elif b.boundary_type == "6":
            s["sixes"] += 1

        bl = get_or_create(b.bowler_id)
        if b.is_valid_ball:
            bl["balls_bowled"] += 1
        bl["runs_conceded"] += b.runs_batter + (b.runs_extras if b.extra_type in ('nb', 'wd') else 0)
        bl["extras_conceded"] += b.runs_extras

        if b.is_wicket:
            if b.dismissal_mode in ('bowled', 'caught', 'lbw', 'stumped', 'hit_wicket'):
                bl["wickets"] += 1
            if b.fielder_id:
                f = get_or_create(b.fielder_id)
                if b.dismissal_mode == "run_out":
                    f["run_outs"] += 1
                else:
                    f["catches"] += 1

    candidates = []
    for pid, data in stats.items():
        breakdown = MVPPointsBreakdown(
            player_id=pid, name=data["name"], team_id=data["team_id"],
            runs=data["runs"], wickets=data["wickets"], fours=data["fours"],
            sixes=data["sixes"], catches=data["catches"], run_outs=data["run_outs"],
            balls_faced=data["balls_faced"],
        )
        if data["balls_faced"] > 0:
            breakdown.strike_rate = round((data["runs"] / data["balls_faced"]) * 100, 2)
        if data["balls_bowled"] > 0:
            whole = data["balls_bowled"] // 6
            remainder = data["balls_bowled"] % 6
            breakdown.overs_bowled = float(f"{whole}.{remainder}") if remainder > 0 else float(whole)
            valid_runs = data["runs_conceded"] - data["extras_conceded"]
            if breakdown.overs_bowled > 0:
                breakdown.economy_rate = round(valid_runs / breakdown.overs_bowled, 2)

        breakdown.points_runs = data["runs"]
        breakdown.points_wickets = data["wickets"] * 10
        breakdown.points_catches = data["catches"] * 5
        breakdown.points_run_outs = data["run_outs"] * 5
        if data["balls_faced"] >= 20 and breakdown.strike_rate > 150:
            breakdown.points_strike_rate = 5
        if breakdown.overs_bowled >= 1.0 and breakdown.economy_rate < 7:
            breakdown.points_economy = 5
        breakdown.total_points = (
            breakdown.points_runs + breakdown.points_wickets
            + breakdown.points_catches + breakdown.points_run_outs
            + breakdown.points_strike_rate + breakdown.points_economy
        )
        candidates.append(
            MVPCandidate(
                player_id=pid, name=data["name"], team_id=data["team_id"],
                team_role="", total_points=breakdown.total_points,
                breakdown=breakdown,
            )
        )
    candidates.sort(key=lambda c: c.total_points, reverse=True)
    return candidates


def _get_winning_team_id(db, match_id: int):
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match or match.status != "completed":
        return None
    squad_map = {}
    squads = db.query(MatchSquad).filter(MatchSquad.match_id == match_id).all()
    for sq in squads:
        squad_map[sq.player_id] = sq.team_id
    links = db.query(MatchTeamLink).filter(MatchTeamLink.match_id == match_id).all()
    team_a_id = team_b_id = None
    for link in links:
        if link.team_role == "team_a":
            team_a_id = link.team_id
        elif link.team_role == "team_b":
            team_b_id = link.team_id
    team_a_runs = team_b_runs = 0
    for b in db.query(Ball).filter(Ball.match_id == match_id).all():
        team_id = squad_map.get(b.striker_id)
        if team_id == team_a_id:
            team_a_runs += b.runs_batter + b.runs_extras + b.penalty_runs
        elif team_id == team_b_id:
            team_b_runs += b.runs_batter + b.runs_extras + b.penalty_runs
    if team_a_runs > team_b_runs:
        return team_a_id
    elif team_b_runs > team_a_runs:
        return team_b_id
    return None


# ── Module 9: Audit Log Endpoint ──

@app.get("/audit-log", response_model=None)
def get_audit_log(
    match_id: int = None,
    limit: int = 100,
    db = Depends(get_db),
    current_session = Depends(get_current_session),
):
    """Retrieve audit log entries. Initiator can view all logs for their matches."""
    stmt = db.query(AuditLog)
    if match_id is not None:
        stmt = stmt.filter(AuditLog.match_id == match_id)
        match = db.query(Match).filter(Match.id == match_id).first()
        if match and match.initiator_session_id != current_session.session_id:
            raise HTTPException(status_code=403, detail="Only the match initiator can view audit logs for this match")
    entries = stmt.order_by(AuditLog.timestamp.desc()).limit(limit).all()
    return [
        {
            "id": e.id,
            "actor_session_id": e.actor_session_id,
            "action": e.action,
            "match_id": e.match_id,
            "target_id": e.target_id,
            "timestamp": e.timestamp.isoformat() if e.timestamp else None,
            "details": e.details,
        }
        for e in entries
    ]


@app.get("/health", status_code=200)
def health():
    return {"status": "ok"}


# ── Module 2: Match Endpoints ──

@app.post("/matches", status_code=201, response_model=None)
def create_match(match_data: MatchCreate, db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    new_match = Match(
        name=f"{match_data.team_a_name} vs {match_data.team_b_name}",
        team_a_name=match_data.team_a_name,
        team_b_name=match_data.team_b_name,
        format=match_data.format,
        overs_per_innings=match_data.overs_per_innings,
        balls_per_over=match_data.balls_per_over,
        status="created",
        initiator_session_id=current_session.session_id,
        checksum=None,
    )
    db.add(new_match)
    db.commit()
    db.refresh(new_match)

    # Initial checksum
    new_match.checksum = compute_checksum(new_match, db)

    # Automatically initialize Team and MatchTeamLink records
    team_a = Team(name=match_data.team_a_name, short_name=match_data.team_a_name[:3].upper())
    team_b = Team(name=match_data.team_b_name, short_name=match_data.team_b_name[:3].upper())
    db.add_all([team_a, team_b])
    db.commit()
    db.refresh(team_a)
    db.refresh(team_b)

    link_a = MatchTeamLink(match_id=new_match.id, team_id=team_a.id, team_role="team_a", is_home=True)
    link_b = MatchTeamLink(match_id=new_match.id, team_id=team_b.id, team_role="team_b", is_home=False)
    db.add_all([link_a, link_b])

    # Assign initiator role with scoring rights
    role = MatchRole(
        match_id=new_match.id,
        session_id=current_session.session_id,
        role="initiator",
        scoring_rights=True,
        approved_by_session_id=None,
        approved_at=None,
        created_at=datetime.now(timezone.utc),
    )
    db.add(role)
    db.commit()

    audit_log(db, current_session.session_id, "match_created", new_match.id, str(new_match.id), '{"team_a": "%s", "team_b": "%s"}' % (match_data.team_a_name, match_data.team_b_name))
    return MatchResponse(
        id=new_match.id,
        name=new_match.name,
        team_a_name=new_match.team_a_name,
        team_b_name=new_match.team_b_name,
        format=new_match.format,
        overs_per_innings=new_match.overs_per_innings,
        balls_per_over=new_match.balls_per_over,
        status=new_match.status,
        initiator_session_id=new_match.initiator_session_id,
        checksum=new_match.checksum,
        created_at=new_match.created_at,
        updated_at=new_match.updated_at,
        locked_at=str(new_match.locked_at) if new_match.locked_at else None,
    )


@app.get("/matches/{match_id}", response_model=None)
def get_match(match_id: int, db = Depends(get_db)):
    """Get match details by ID."""
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return MatchResponse(
        id=match.id,
        name=match.name,
        team_a_name=match.team_a_name,
        team_b_name=match.team_b_name,
        format=match.format,
        overs_per_innings=match.overs_per_innings,
        balls_per_over=match.balls_per_over,
        status=match.status,
        initiator_session_id=match.initiator_session_id,
        checksum=match.checksum,
        created_at=match.created_at,
        updated_at=match.updated_at,
        locked_at=str(match.locked_at) if match.locked_at else None,
    )


@app.get("/matches", response_model=None)
def list_matches(db = Depends(get_db)):
    """List all matches in the system."""
    matches = db.query(Match).order_by(Match.created_at.desc()).all()
    return [
        MatchResponse(
            id=m.id,
            name=m.name,
            team_a_name=m.team_a_name,
            team_b_name=m.team_b_name,
            format=m.format,
            overs_per_innings=m.overs_per_innings,
            balls_per_over=m.balls_per_over,
            status=m.status,
            initiator_session_id=m.initiator_session_id,
            checksum=m.checksum,
            created_at=m.created_at,
            updated_at=m.updated_at,
            locked_at=str(m.locked_at) if m.locked_at else None,
        )
        for m in matches
    ]


@app.delete("/matches/{match_id}", status_code=204)
def delete_match(match_id: int, db = Depends(get_db), current_session = Depends(get_current_session)):
    """Delete a match and its linked records."""
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    db.query(Ball).filter(Ball.match_id == match_id).delete()
    db.query(MatchRole).filter(MatchRole.match_id == match_id).delete()
    db.query(Toss).filter(Toss.match_id == match_id).delete()
    db.query(MatchTeamLink).filter(MatchTeamLink.match_id == match_id).delete()
    db.query(MatchSquad).filter(MatchSquad.match_id == match_id).delete()
    db.query(PlayingXI).filter(PlayingXI.match_id == match_id).delete()
    db.query(MVP).filter(MVP.match_id == match_id).delete()
    db.query(AuditLog).filter(AuditLog.match_id == match_id).delete()
    db.delete(match)
    db.commit()
    return None


@app.get("/matches/{match_id}/public", response_model=None)
def match_public(match_id: int, db = Depends(get_db)) -> dict:
    """Public match summary - no auth required."""
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    balls = db.query(Ball).filter(Ball.match_id == match_id).all()
    runs = sum(b.runs_batter + b.runs_extras + b.penalty_runs for b in balls)
    wickets = sum(1 for b in balls if b.is_wicket)
    valid_balls = sum(1 for b in balls if b.is_valid_ball)
    b_per_o = match.balls_per_over or 6
    overs_val = float(f"{valid_balls // b_per_o}.{valid_balls % b_per_o}")
    score_str = f"{runs}/{wickets}"

    return MatchPublicResponse(
        match_id=match.id,
        team_a_name=match.team_a_name,
        team_b_name=match.team_b_name,
        format=match.format,
        overs_per_innings=match.overs_per_innings,
        current_score=score_str,
        current_overs=overs_val,
        wickets=wickets,
        status=match.status,
        last_updated=match.updated_at or match.created_at,
    )


@app.post("/matches/{match_id}/request-scoring", status_code=201, response_model=None)
def request_scoring(match_id: int, request_data: ScoringRightRequestCreate, db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.initiator_session_id == current_session.session_id:
        raise HTTPException(status_code=400, detail="You are the initiator; you already have scoring rights")
    stmt_role = select(MatchRole).where(MatchRole.match_id == match_id, MatchRole.session_id == current_session.session_id)
    result = db.execute(stmt_role)
    existing_role = result.scalar_one_or_none()
    if existing_role and existing_role.role == "scorer":
        raise HTTPException(status_code=400, detail="You already have scoring rights")
    if existing_role:
        existing_role.role = "requester"
        existing_role.scoring_rights = False
        existing_role.approved_at = None
        db.commit()
        db.refresh(existing_role)
        request_row = existing_role
    else:
        request_row = MatchRole(
            match_id=match_id,
            session_id=current_session.session_id,
            role="requester",
            scoring_rights=False,
            approved_by_session_id=None,
            approved_at=None,
            created_at=datetime.now(timezone.utc),
        )
        db.add(request_row)
        db.commit()
        db.refresh(request_row)

    if request_data.device_name:
        current_session.device_name = request_data.device_name
        db.commit()

    audit_log(db, current_session.session_id, "scoring_rights_requested", match_id, str(request_row.id), '{"device_name": "%s"}' % (request_data.device_name or ""))
    return ScoringRightRequestResponse(
        id=request_row.id,
        match_id=match_id,
        requestor_session_id=current_session.session_id,
        device_name=request_data.device_name,
        status="pending",
        requested_at=request_row.created_at,
        approved_at=None,
    )


@app.post("/matches/{match_id}/scoring-requests/{request_id}/approve", response_model=None)
def approve_scoring_request(match_id: int, request_id: int, db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.initiator_session_id != current_session.session_id:
        raise HTTPException(status_code=403, detail="Only the match initiator can approve scoring requests")
    stmt_role = select(MatchRole).where(MatchRole.match_id == match_id, MatchRole.id == request_id, MatchRole.role == "requester")
    result = db.execute(stmt_role)
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="No pending scoring request found with that ID")
    role.role = "scorer"
    role.scoring_rights = True
    role.approved_by_session_id = current_session.session_id
    role.approved_at = datetime.now(timezone.utc)
    db.commit()
    audit_log(db, current_session.session_id, "scoring_rights_granted", match_id, role.session_id, '{"granted_to": "%s"}' % role.session_id)
    return {"message": "Scoring rights approved", "request_id": request_id, "granted_to_session": role.session_id, "role": role.role, "scoring_rights": role.scoring_rights}


@app.post("/matches/{match_id}/scoring-requests/{request_id}/reject", response_model=None)
def reject_scoring_request(match_id: int, request_id: int, db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.initiator_session_id != current_session.session_id:
        raise HTTPException(status_code=403, detail="Only the match initiator can reject scoring requests")
    stmt_role = select(MatchRole).where(MatchRole.match_id == match_id, MatchRole.id == request_id, MatchRole.role == "requester")
    result = db.execute(stmt_role)
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="No pending scoring request found with that ID")
    role.role = "watcher"
    role.scoring_rights = False
    db.commit()
    audit_log(db, current_session.session_id, "scoring_rights_rejected", match_id, role.session_id, '{"rejected_session": "%s"}' % role.session_id)
    return {"message": "Scoring request rejected", "request_id": request_id}


@app.post("/matches/{match_id}/scoring-rights/revoke", response_model=None)
def revoke_scoring_rights(match_id: int, scorer_session_id: str, db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.initiator_session_id != current_session.session_id:
        raise HTTPException(status_code=403, detail="Only the match initiator can revoke scoring rights")
    if match.status == "locked":
        raise HTTPException(status_code=400, detail="Cannot revoke scoring rights on a locked match")
    stmt_role = select(MatchRole).where(MatchRole.match_id == match_id, MatchRole.session_id == scorer_session_id)
    result = db.execute(stmt_role)
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="No role found for that session on this match")
    role.scoring_rights = False
    role.role = "watcher"
    db.commit()
    audit_log(db, current_session.session_id, "scoring_rights_revoked", match_id, scorer_session_id, '{"revoked_session": "%s"}' % scorer_session_id)
    return {"message": "Scoring rights revoked", "session_id": scorer_session_id}


@app.post("/matches/{match_id}/transfer-ownership", response_model=None)
def transfer_ownership(match_id: int, new_initiator_session_id: str, db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.initiator_session_id != current_session.session_id:
        raise HTTPException(status_code=403, detail="Only the match initiator can transfer ownership")
    if match.status == "locked":
        raise HTTPException(status_code=400, detail="Cannot transfer ownership of a locked match")
    stmt_role = select(MatchRole).where(MatchRole.match_id == match_id, MatchRole.session_id == new_initiator_session_id, MatchRole.role == "scorer", MatchRole.scoring_rights == True)
    result = db.execute(stmt_role)
    new_initiator_role = result.scalar_one_or_none()
    if not new_initiator_role:
        raise HTTPException(status_code=400, detail="Target session must be an approved scorer before ownership can be transferred")
    stmt_old_role = select(MatchRole).where(MatchRole.match_id == match_id, MatchRole.session_id == current_session.session_id)
    result = db.execute(stmt_old_role)
    old_initiator_role = result.scalar_one_or_none()
    match.initiator_session_id = new_initiator_session_id
    new_initiator_role.role = "initiator"
    if old_initiator_role:
        old_initiator_role.role = "scorer"
    db.commit()
    audit_log(db, current_session.session_id, "ownership_transferred", match_id, new_initiator_session_id, '{"new_initiator": "%s"}' % new_initiator_session_id)
    return {"message": "Ownership transferred successfully", "new_initiator_session_id": new_initiator_session_id}


@app.get("/matches/{match_id}/scoring-requests", response_model=None)
def list_scoring_requests(match_id: int, db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.initiator_session_id != current_session.session_id:
        raise HTTPException(status_code=403, detail="Only the match initiator can view scoring requests")
    stmt_role = select(MatchRole).where(MatchRole.match_id == match_id, MatchRole.role == "requester")
    result = db.execute(stmt_role)
    requester_roles = result.scalars().all()
    requests = []
    for role in requester_roles:
        s_obj = db.query(AnonymousSession).filter(AnonymousSession.session_id == role.session_id).first()
        dev_name = s_obj.device_name if s_obj else None
        requests.append(ScoringRightRequestResponse(
            id=role.id,
            match_id=role.match_id,
            requestor_session_id=role.session_id,
            device_name=dev_name,
            status="pending",
            requested_at=role.created_at,
            approved_at=None,
        ))
    return requests


# ── Module 4: Scoring Endpoints ──

@app.post("/matches/{match_id}/balls", response_model=None)
def record_ball(match_id: int, ball_data: BallRecordRequest, db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    """Record one delivery atomically with full validation."""
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    stmt_role = select(MatchRole).where(MatchRole.match_id == match_id, MatchRole.session_id == current_session.session_id)
    result = db.execute(stmt_role)
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=403, detail="Session not registered for this match")
    if role.role not in ("initiator", "scorer") or not role.scoring_rights:
        raise HTTPException(status_code=403, detail="Scoring rights required to record deliveries. Request approval from the initiator")

    # Module 12: Toss must be completed before first ball
    toss = db.query(Toss).filter(Toss.match_id == match_id).first()
    if not toss or not toss.coin_result:
        raise HTTPException(
            status_code=403,
            detail="Online toss has not been completed. Call heads/tails first (POST /matches/{id}/toss/call), then flip the coin (POST /matches/{id}/toss/flip)",
        )

    innings_id = 1
    try:
        # FR-8.6: Auto-backup before major mutation
        db_path = _get_db_path()
        if db_path:
            _backup_db(db_path)

        response = process_ball(db, match, ball_data, role, innings_id, True)
        audit_log(
            db,
            current_session.session_id,
            "ball_recorded",
            match_id,
            str(response.ball.ball_id),
            f'{{"runs_batter": {ball_data.runs_batter}, "runs_extras": {ball_data.runs_extras}, "is_wicket": {ball_data.is_wicket}}}',
        )

        # Broadcast live update
        live_payload = {
            "type": "ball_recorded",
            "match": {
                "id": match.id,
                "name": match.name,
                "team_a_name": match.team_a_name,
                "team_b_name": match.team_b_name,
                "format": match.format,
                "overs_per_innings": match.overs_per_innings,
                "status": match.status,
            },
            "ball": {
                "ball_id": response.ball.ball_id,
                "over_number": response.ball.over_number,
                "ball_number": response.ball.ball_number,
                "runs_batter": response.ball.runs_batter,
                "runs_extras": response.ball.runs_extras,
                "extra_type": response.ball.extra_type,
                "is_wicket": response.ball.is_wicket,
                "dismissal_mode": response.ball.dismissal_mode,
                "boundary_type": response.ball.boundary_type,
                "current_score": response.current_score,
                "current_overs": response.current_overs,
                "wickets": response.wickets,
                "striker_id": response.striker,
                "non_striker_id": response.non_striker,
                "bowler_id": response.bowler,
                "checksum": response.checksum,
            },
        }
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(manager.broadcast(match_id, live_payload))
        except Exception:
            pass

        return response.model_dump()
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/matches/{match_id}/balls/{ball_id}/undo", response_model=None)
def undo_ball(match_id: int, ball_id: int, db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    """Rollback the specified delivery and restore previous state."""
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    stmt_role = select(MatchRole).where(MatchRole.match_id == match_id, MatchRole.session_id == current_session.session_id)
    result = db.execute(stmt_role)
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=403, detail="Session not registered for this match")
    if role.role != "initiator" and not role.scoring_rights:
        raise HTTPException(status_code=403, detail="Scoring rights required to undo")

    ball = db.query(Ball).filter(Ball.id == ball_id, Ball.match_id == match_id).first()
    if not ball:
        raise HTTPException(status_code=404, detail="Ball not found")

    db.delete(ball)
    db.commit()

    match.checksum = compute_checksum(match, db)
    match.updated_at = datetime.now(timezone.utc)
    db.commit()
    audit_log(db, current_session.session_id, "ball_undone", match_id, str(ball_id), None)

    # Broadcast undo
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(manager.broadcast(match_id, {"type": "undo", "ball_id": ball_id, "checksum": match.checksum}))
    except Exception:
        pass

    return {"message": "Delivery undone", "match_id": match_id, "checksum": match.checksum}


@app.get("/matches/{match_id}/checksum", response_model=None)
def get_match_checksum(match_id: int, db = Depends(get_db)) -> dict:
    """Get the current checksum of the match (Laws 2.15 / 3.2)."""
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    checksum = compute_checksum(match, db)
    return {"match_id": match_id, "checksum": checksum, "computed_at": datetime.now(timezone.utc)}


@app.post("/matches/{match_id}/undo", response_model=None)
def undo_last_ball(match_id: int, db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    """Undo the last ball recorded for this match."""
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    stmt_role = select(MatchRole).where(MatchRole.match_id == match_id, MatchRole.session_id == current_session.session_id)
    result = db.execute(stmt_role)
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=403, detail="Session not registered for this match")
    if role.role != "initiator" and not role.scoring_rights:
        raise HTTPException(status_code=403, detail="Scoring rights required to undo deliveries.")

    last_ball = db.query(Ball).filter(Ball.match_id == match_id).order_by(Ball.id.desc()).first()
    if not last_ball:
        raise HTTPException(status_code=404, detail="No deliveries to undo")

    ball_id = last_ball.id
    db.delete(last_ball)
    db.commit()

    match.checksum = compute_checksum(match, db)
    match.updated_at = datetime.now(timezone.utc)
    db.commit()
    audit_log(db, current_session.session_id, "ball_undone", match_id, str(ball_id), "last_ball_undone")

    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(manager.broadcast(match_id, {"type": "undo", "ball_id": ball_id, "checksum": match.checksum}))
    except Exception:
        pass

    return {"message": "Delivery undone", "match_id": match_id, "checksum": match.checksum, "ball_id": ball_id}


# ── Module 3: Squads, Playing XI & Teams ──

@app.post("/matches/{match_id}/squad", status_code=201, response_model=None)
def add_players_to_squad(match_id: int, squad_data: List[PlayerRequest], db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    for player_data in squad_data:
        player = Player(
            match_id=match_id,
            team_id=player_data.team_id,
            name=player_data.name,
            role=player_data.role,
            jersey_number=player_data.jersey_number,
            is_substitute=player_data.is_substitute,
        )
        db.add(player)
        db.commit()
        db.refresh(player)
        squad = MatchSquad(
            match_id=match_id,
            player_id=player.id,
            team_id=player.team_id,
            is_substitute=player_data.is_substitute,
        )
        db.add(squad)
        db.commit()
    return {"message": f"Added {len(squad_data)} players to squad", "match_id": match_id}


@app.post("/matches/{match_id}/playing-xi", status_code=201, response_model=None)
def set_playing_xi(match_id: int, xi_data: List[XIEntry], db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    stmt = select(PlayingXI).where(PlayingXI.match_id == match_id)
    result = db.execute(stmt)
    existing_xi = result.scalars().all()
    for xi in existing_xi:
        db.delete(xi)
    db.commit()
    for xi_entry in xi_data:
        xi = PlayingXI(
            match_id=match_id,
            player_id=xi_entry.player_id,
            team_id=xi_entry.team_id,
            is_captain=xi_entry.is_captain,
            is_wicketkeeper=xi_entry.is_wicketkeeper,
        )
        db.add(xi)
        db.commit()
    return {"message": f"Set playing XI for {len(xi_data)} players", "match_id": match_id}


@app.get("/formats", response_model=None)
def list_formats(db: Session = Depends(get_db)):
    stmt = select(FormatConfig).order_by(FormatConfig.overs_per_innings)
    result = db.execute(stmt)
    formats = result.scalars().all()
    return formats


@app.get("/formats/{format_id}", response_model=None)
def get_format(format_id: int, db = Depends(get_db)) -> dict:
    stmt = select(FormatConfig).where(FormatConfig.id == format_id)
    result = db.execute(stmt)
    fmt = result.scalar_one_or_none()
    if not fmt:
        raise HTTPException(status_code=404, detail="Format not found")
    return fmt


@app.post("/matches/{match_id}/teams", status_code=201, response_model=None)
def create_match_teams(match_id: int, team_data: TeamData, db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    """Create/edit two teams for the match."""
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    team_a = Team(name=team_data.team_a_name, short_name=team_data.team_a_short)
    db.add(team_a)
    db.commit()
    db.refresh(team_a)
    team_b = Team(name=team_data.team_b_name, short_name=team_data.team_b_short)
    db.add(team_b)
    db.commit()
    db.refresh(team_b)
    link_a = MatchTeamLink(match_id=match_id, team_id=team_a.id, team_role="team_a", is_home=True)
    db.add(link_a)
    link_b = MatchTeamLink(match_id=match_id, team_id=team_b.id, team_role="team_b", is_home=False)
    db.add(link_b)
    db.commit()
    return MatchTeamLinkResponse(id=link_a.id, match_id=match_id, team_id=team_a.id, team_role="team_a", team_name=team_a.name, short_name=team_a.short_name, is_home=True, created_at=link_a.created_at)


# ── Module 12: Online Toss (Heads / Tails) ──

@app.post("/matches/{match_id}/toss/call", status_code=201, response_model=None)
def call_toss(match_id: int, toss_call: TossCallData, db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    """Initiator calls heads or tails before the coin flip (Phase 1)."""
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.initiator_session_id != current_session.session_id:
        raise HTTPException(status_code=403, detail="Only the match initiator can call the toss")
    existing = db.query(Toss).filter(Toss.match_id == match_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Toss has already been initiated for this match")
    toss = Toss(match_id=match_id, initiator_call=toss_call.call, called_by_session_id=current_session.session_id)
    db.add(toss)
    db.commit()
    db.refresh(toss)
    return TossResponse(id=toss.id, match_id=match_id, initiator_call=toss.initiator_call, coin_result=None, winner_team_id=None, toss_decision=None, called_by_session_id=toss.called_by_session_id, created_at=toss.created_at)


@app.post("/matches/{match_id}/toss/flip", status_code=201, response_model=None)
def flip_coin(match_id: int, toss_flip: TossFlipData, db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    """System randomly determines heads/tails and sets winner team."""
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    toss = db.query(Toss).filter(Toss.match_id == match_id).first()
    if not toss:
        raise HTTPException(status_code=400, detail="Toss call must be made before flipping the coin")

    call = toss.initiator_call.lower()
    coin_result = secrets.choice(["heads", "tails"])
    is_match = (call == coin_result)

    link_a = db.query(MatchTeamLink).filter(MatchTeamLink.match_id == match_id, MatchTeamLink.team_role == "team_a").first()
    link_b = db.query(MatchTeamLink).filter(MatchTeamLink.match_id == match_id, MatchTeamLink.team_role == "team_b").first()
    team_a_id = link_a.team_id if link_a else 1
    team_b_id = link_b.team_id if link_b else 2
    winner_team_id = team_a_id if is_match else team_b_id

    toss.coin_result = coin_result
    toss.winner_team_id = winner_team_id
    db.commit()
    db.refresh(toss)
    return TossResponse(id=toss.id, match_id=match_id, initiator_call=toss.initiator_call, coin_result=toss.coin_result, winner_team_id=toss.winner_team_id, toss_decision=toss.toss_decision, called_by_session_id=toss.called_by_session_id, created_at=toss.created_at)


@app.get("/matches/{match_id}/toss", response_model=None)
def get_toss(match_id: int, db = Depends(get_db)) -> dict:
    """Public endpoint to view the online toss outcome."""
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    toss = db.query(Toss).filter(Toss.match_id == match_id).first()
    if not toss:
        return {
            "match_id": match_id,
            "status": "pending",
            "initiator_call": None,
            "coin_result": None,
            "winner_team_id": None,
            "toss_decision": None,
            "called_by_session_id": None,
        }
    return TossResponse(id=toss.id, match_id=match_id, initiator_call=toss.initiator_call, coin_result=toss.coin_result, winner_team_id=toss.winner_team_id, toss_decision=toss.toss_decision, called_by_session_id=toss.called_by_session_id, created_at=toss.created_at)


@app.post("/matches/{match_id}/toss/flip/result", status_code=201, response_model=None)
def record_toss_decision(match_id: int, toss_result: TossResultData, db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    """Record the winning team's decision (bat or field)."""
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    toss = db.query(Toss).filter(Toss.match_id == match_id).first()
    if not toss:
        raise HTTPException(status_code=400, detail="No toss found for this match")
    if not toss.coin_result:
        raise HTTPException(status_code=400, detail="Toss must be flipped before recording decision")
    decision = toss_result.toss_decision.lower()
    if decision not in ['bat', 'field']:
        raise HTTPException(status_code=400, detail='toss_decision must be "bat" or "field"')
    toss.toss_decision = decision
    db.commit()
    db.refresh(toss)
    if match.status == 'created':
        match.status = 'in_progress'
        match.updated_at = datetime.now(timezone.utc)
        db.commit()

    # FR-5.1: Broadcast toss completion
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(manager.broadcast(match_id, {"type": "toss_complete", "match_id": match_id, "status": match.status}))
    except Exception:
        pass

    return TossResponse(id=toss.id, match_id=match_id, initiator_call=toss.initiator_call, coin_result=toss.coin_result, winner_team_id=toss.winner_team_id, toss_decision=toss.toss_decision, called_by_session_id=toss.called_by_session_id, created_at=toss.created_at)


# ── Module 5: Live Broadcasting & Polling ──

@app.get("/matches/{match_id}/live", response_model=None)
def get_match_live(match_id: int, db = Depends(get_db)) -> dict:
    """Polling fallback for live match updates."""
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    all_balls = db.query(Ball).filter(Ball.match_id == match_id).order_by(Ball.id.asc()).all()
    runs_by_innings = {1: 0, 2: 0}
    wickets_by_innings = {1: 0, 2: 0}
    valid_by_innings = {1: 0, 2: 0}

    for ball in all_balls:
        inn = ball.innings_id if ball.innings_id in (1, 2) else 1
        runs_by_innings[inn] += ball.runs_batter + ball.runs_extras + ball.penalty_runs
        if ball.is_wicket:
            wickets_by_innings[inn] += 1
        if ball.is_valid_ball:
            valid_by_innings[inn] += 1

    b_per_o = match.balls_per_over or 6
    o1 = float(f"{valid_by_innings[1] // b_per_o}.{valid_by_innings[1] % b_per_o}")
    o2 = float(f"{valid_by_innings[2] // b_per_o}.{valid_by_innings[2] % b_per_o}")

    # Last 10 balls for the feed
    last_10 = all_balls[-10:] if len(all_balls) > 10 else all_balls

    return {
        "match": {
            "id": match.id,
            "name": match.name,
            "team_a_name": match.team_a_name,
            "team_b_name": match.team_b_name,
            "format": match.format,
            "overs_per_innings": match.overs_per_innings,
            "status": match.status,
            "updated_at": match.updated_at.isoformat() if match.updated_at else None,
        },
        "score": {
            "innings_1": {"runs": runs_by_innings[1], "wickets": wickets_by_innings[1], "overs": o1},
            "innings_2": {"runs": runs_by_innings[2], "wickets": wickets_by_innings[2], "overs": o2},
        },
        "balls": [
            {
                "id": b.id,
                "over_number": b.over_number,
                "ball_number": b.ball_number,
                "striker_id": b.striker_id,
                "bowler_id": b.bowler_id,
                "runs_batter": b.runs_batter,
                "runs_extras": b.runs_extras,
                "extra_type": b.extra_type,
                "is_wicket": b.is_wicket,
                "dismissal_mode": b.dismissal_mode,
                "boundary_type": b.boundary_type,
            }
            for b in last_10
        ],
    }


@app.websocket("/ws/match/{match_id}")
async def websocket_endpoint(websocket, match_id: int):
    """WebSocket endpoint for live score broadcasting."""
    await manager.connect(websocket, match_id)
    try:
        db = get_session_local()
        try:
            match = db.query(Match).filter(Match.id == match_id).first()
            if match:
                balls = db.query(Ball).filter(Ball.match_id == match_id).all()
                runs = sum(b.runs_batter + b.runs_extras + b.penalty_runs for b in balls)
                wickets = sum(1 for b in balls if b.is_wicket)
                v_balls = sum(1 for b in balls if b.is_valid_ball)
                b_per_o = match.balls_per_over or 6
                overs = float(f"{v_balls // b_per_o}.{v_balls % b_per_o}")
                initial_state = {
                    "type": "initial_state",
                    "match": {
                        "id": match.id,
                        "name": match.name,
                        "team_a_name": match.team_a_name,
                        "team_b_name": match.team_b_name,
                        "format": match.format,
                        "overs_per_innings": match.overs_per_innings,
                        "status": match.status,
                    },
                    "score": {
                        "runs": runs,
                        "wickets": wickets,
                        "overs": overs,
                        "checksum": match.checksum,
                    },
                }
                await websocket.send_json(initial_state)
        finally:
            db.close()

        while True:
            data = await websocket.receive_text()
            # Heartbeat ping/pong
            if data == "ping":
                await websocket.send_text("pong")
    except Exception:
        pass
    finally:
        manager.disconnect(websocket, match_id)


# ── Module 6: Scorecard, Statistics & Match Result ──

@app.get("/matches/{match_id}/scorecard", response_model=None)
def get_match_scorecard(match_id: int, db = Depends(get_db)) -> dict:
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    innings_list = []
    for innings_id in (1, 2):
        balls_count = db.query(Ball).filter(
            Ball.match_id == match_id,
            Ball.innings_id == innings_id,
        ).count()
        if balls_count > 0:
            innings_data = compute_full_scorecard(db, match_id, innings_id)
            innings_list.append(innings_data)

    result_data = None
    if len(innings_list) >= 1:
        result_data = compute_match_result(db, match_id)

    follow_on = None
    if match.format == "Test":
        follow_on = compute_follow_on(db, match_id)

    super_over = None
    if match.format == "T20" and result_data and result_data["result_type"] == "tie":
        super_over = compute_super_over(db, match_id)

    return {
        "match_id": match_id,
        "match_name": match.name,
        "format": match.format,
        "status": match.status,
        "innings": innings_list,
        "result": result_data,
        "follow_on": follow_on,
        "super_over": super_over,
    }


@app.get("/matches/{match_id}/result", response_model=None)
def get_match_result_endpoint(match_id: int, db = Depends(get_db)) -> dict:
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return compute_match_result(db, match_id)


@app.get("/matches/{match_id}/follow-on", response_model=None)
def get_follow_on_endpoint(match_id: int, db = Depends(get_db)) -> dict:
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return compute_follow_on(db, match_id)


@app.get("/matches/{match_id}/super-over", response_model=None)
def get_super_over_endpoint(match_id: int, db = Depends(get_db)) -> dict:
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return compute_super_over(db, match_id)


@app.post("/matches/{match_id}/confirm", response_model=None)
def confirm_scores(match_id: int, db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    """Confirm correctness of scores before match conclusion (Laws 3.2 / 16.8)."""
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.initiator_session_id != current_session.session_id:
        raise HTTPException(status_code=403, detail="Only the match initiator can confirm scores")
    # FR-8.6: Auto-backup before major mutation
    db_path = _get_db_path()
    if db_path:
        _backup_db(db_path)
    match.status = "completed"
    match.updated_at = datetime.now(timezone.utc)
    db.commit()
    audit_log(db, current_session.session_id, "scores_confirmed", match_id, str(match_id), "Scores confirmed per Law 3.2 / 16.8")

    # FR-5.1: Broadcast match status change
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(manager.broadcast(match_id, {"type": "match_completed", "match_id": match_id, "status": "completed"}))
    except Exception:
        pass

    return {"message": "Scores confirmed", "match_id": match_id, "status": match.status}


@app.post("/matches/{match_id}/lock", response_model=None)
def lock_match_endpoint(
    match_id: int,
    lock_request: LockMatchRequest,
    db = Depends(get_db),
    current_session = Depends(get_current_session),
) -> dict:
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.initiator_session_id != current_session.session_id:
        raise HTTPException(status_code=403, detail="Only the match initiator can lock the match")
    if not lock_request.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required to lock the match")
    if match.status == "locked":
        raise HTTPException(status_code=400, detail="Match is already locked")
    # FR-8.6: Auto-backup before major mutation
    db_path = _get_db_path()
    if db_path:
        _backup_db(db_path)
    match.status = "locked"
    match.locked_at = datetime.now(timezone.utc)
    match.updated_at = datetime.now(timezone.utc)
    db.commit()
    audit_log(db, current_session.session_id, "match_locked", match_id, None, '{"status": "locked"}')

    # FR-5.1: Broadcast match status change
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(manager.broadcast(match_id, {"type": "match_locked", "match_id": match_id, "status": "locked"}))
    except Exception:
        pass

    return {
        "match_id": match_id,
        "status": match.status,
        "locked_at": str(match.locked_at) if match.locked_at else None,
        "message": "Match locked successfully",
    }


@app.post("/matches/{match_id}/unlock", response_model=None)
def unlock_match_endpoint(
    match_id: int,
    db = Depends(get_db),
    current_session = Depends(get_current_session),
) -> dict:
    """Unlock a match after admin review (FR-10.2). Requires initiator."""
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.initiator_session_id != current_session.session_id:
        raise HTTPException(status_code=403, detail="Only the match initiator can unlock the match")
    if match.status != "locked":
        raise HTTPException(status_code=400, detail="Match is not locked")
    match.status = "completed"
    match.locked_at = None
    match.updated_at = datetime.now(timezone.utc)
    db.commit()
    audit_log(db, current_session.session_id, "match_unlocked", match_id, None, '{"status": "completed"}')

    # FR-5.1: Broadcast match status change
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(manager.broadcast(match_id, {"type": "match_unlocked", "match_id": match_id, "status": "completed"}))
    except Exception:
        pass

    return {
        "match_id": match_id,
        "status": match.status,
        "message": "Match unlocked successfully",
    }


# ── Module 7: Export & Import ──

def _get_db_path():
    url = DATABASE_URL
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "")
    return None


def _backup_db(db_path):
    if not db_path or not os.path.exists(db_path):
        return None
    backup_path = f"{db_path}.bak"
    shutil.copy2(db_path, backup_path)
    return backup_path


def _match_to_dict(db, match):
    team_links = db.query(MatchTeamLink).filter(MatchTeamLink.match_id == match.id).all()
    teams = [{"team_id": tl.team_id, "team_role": tl.team_role, "is_home": tl.is_home} for tl in team_links]
    players = db.query(Player).all()
    players_list = [{"id": p.id, "team_id": p.team_id, "name": p.name, "role": p.role, "jersey_number": p.jersey_number} for p in players]
    squads = db.query(MatchSquad).filter(MatchSquad.match_id == match.id).all()
    squads_list = [{"id": s.id, "match_id": s.match_id, "player_id": s.player_id, "team_id": s.team_id, "is_substitute": s.is_substitute} for s in squads]
    xis = db.query(PlayingXI).filter(PlayingXI.match_id == match.id).all()
    xis_list = [{"id": xi.id, "match_id": xi.match_id, "player_id": xi.player_id, "team_id": xi.team_id, "is_captain": xi.is_captain, "is_wicketkeeper": xi.is_wicketkeeper} for xi in xis]
    toss = db.query(Toss).filter(Toss.match_id == match.id).first()
    toss_data = None
    if toss:
        toss_data = {"id": toss.id, "match_id": toss.match_id, "initiator_call": toss.initiator_call, "coin_result": toss.coin_result, "winner_team_id": toss.winner_team_id, "toss_decision": toss.toss_decision, "called_by_session_id": toss.called_by_session_id, "created_at": str(toss.created_at) if toss.created_at else None}
    formats = db.query(FormatConfig).all()
    formats_list = [{"id": f.id, "format_name": f.format_name, "overs_per_innings": f.overs_per_innings, "balls_per_over": f.balls_per_over, "max_overs_per_bowler": f.max_overs_per_bowler, "free_hit_after_no_ball": f.free_hit_after_no_ball, "powerplay_max_overs": f.powerplay_max_overs, "new_ball_every_overs": f.new_ball_every_overs, "follow_on_threshold": f.follow_on_threshold} for f in formats]
    balls = db.query(Ball).filter(Ball.match_id == match.id).order_by(Ball.id).all()
    balls_list = [{"id": b.id, "match_id": b.match_id, "innings_id": b.innings_id, "over_number": b.over_number, "ball_number": b.ball_number, "striker_id": b.striker_id, "non_striker_id": b.non_striker_id, "bowler_id": b.bowler_id, "runs_batter": b.runs_batter, "runs_extras": b.runs_extras, "extra_type": b.extra_type, "penalty_runs": b.penalty_runs, "is_wicket": b.is_wicket, "dismissal_mode": b.dismissal_mode, "fielder_id": b.fielder_id, "short_runs": b.short_runs, "boundary_type": b.boundary_type, "is_free_hit": b.is_free_hit, "is_valid_ball": b.is_valid_ball, "is_over_completed": b.is_over_completed, "is_shot_out": b.is_shot_out, "created_at": str(b.created_at) if b.created_at else None} for b in balls]
    return {
        "match": {
            "id": match.id,
            "name": match.name,
            "venue": match.venue,
            "date": str(match.date) if match.date else None,
            "format": match.format,
            "overs_per_innings": match.overs_per_innings,
            "balls_per_over": match.balls_per_over,
            "status": match.status,
            "initiator_session_id": match.initiator_session_id,
            "checksum": match.checksum,
            "created_at": str(match.created_at) if match.created_at else None,
            "updated_at": str(match.updated_at) if match.updated_at else None,
            "locked_at": str(match.locked_at) if match.locked_at else None,
            "team_a_name": match.team_a_name,
            "team_b_name": match.team_b_name,
        },
        "teams": teams,
        "players": players_list,
        "squads": squads_list,
        "playing_xi": xis_list,
        "toss": toss_data,
        "format_configs": formats_list,
        "balls": balls_list,
    }


@app.post("/import/json", response_model=None)
def import_match_json(import_data: dict, db = Depends(get_db), current_session = Depends(get_current_session)):
    match_data = import_data.get("match", {})
    if not match_data:
        raise HTTPException(status_code=400, detail="No match data in import")
    db_path = _get_db_path()
    if db_path:
        _backup_db(db_path)
    new_match = Match(
        name=match_data.get("name", f"Imported Match {datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"),
        team_a_name=match_data.get("team_a_name", "Team A"),
        team_b_name=match_data.get("team_b_name", "Team B"),
        format=match_data.get("format", "Custom"),
        overs_per_innings=match_data.get("overs_per_innings", 20),
        balls_per_over=match_data.get("balls_per_over", 6),
        status="created",
        initiator_session_id=current_session.session_id,
        checksum=None,
    )
    db.add(new_match)
    db.commit()
    db.refresh(new_match)

    role = MatchRole(
        match_id=new_match.id,
        session_id=current_session.session_id,
        role="initiator",
        scoring_rights=True,
        approved_by_session_id=None,
        approved_at=None,
        created_at=datetime.now(timezone.utc),
    )
    db.add(role)
    db.commit()

    audit_log(db, current_session.session_id, "match_imported", new_match.id, str(new_match.id), '{"name": "%s"}' % match_data.get("name", "Imported"))

    teams_data = import_data.get("teams", [])
    for t in teams_data:
        link = MatchTeamLink(match_id=new_match.id, team_id=t.get("team_id"), team_role=t.get("team_role", "team_a"), is_home=t.get("is_home", False))
        db.add(link)

    players_data = import_data.get("players", [])
    player_id_map = {}
    for p in players_data:
        old_id = p.get("id")
        new_player = Player(
            match_id=new_match.id,
            team_id=p.get("team_id") or 1,
            name=p.get("name", "Unknown"),
            role=p.get("role", "all-rounder"),
            jersey_number=p.get("jersey_number"),
            is_substitute=p.get("is_substitute", False),
        )
        db.add(new_player)
        db.flush()
        if old_id:
            player_id_map[old_id] = new_player.id

    squads_data = import_data.get("squads", [])
    for s in squads_data:
        squad = MatchSquad(
            match_id=new_match.id,
            player_id=player_id_map.get(s.get("player_id"), s.get("player_id")),
            team_id=s.get("team_id") or 1,
            is_substitute=s.get("is_substitute", False),
        )
        db.add(squad)

    xis_data = import_data.get("playing_xi", [])
    for xi in xis_data:
        xi_entry = PlayingXI(
            match_id=new_match.id,
            player_id=player_id_map.get(xi.get("player_id"), xi.get("player_id")),
            team_id=xi.get("team_id") or 1,
            is_captain=xi.get("is_captain", False),
            is_wicketkeeper=xi.get("is_wicketkeeper", False),
        )
        db.add(xi_entry)

    toss_data = import_data.get("toss")
    if toss_data:
        toss = Toss(
            match_id=new_match.id,
            initiator_call=toss_data.get("initiator_call"),
            coin_result=toss_data.get("coin_result"),
            winner_team_id=toss_data.get("winner_team_id"),
            toss_decision=toss_data.get("toss_decision"),
            called_by_session_id=toss_data.get("called_by_session_id"),
        )
        db.add(toss)

    balls_data = import_data.get("balls", [])
    for b in balls_data:
        ball = Ball(
            match_id=new_match.id,
            innings_id=b.get("innings_id", 1),
            over_number=b.get("over_number", 1),
            ball_number=b.get("ball_number", 1),
            striker_id=player_id_map.get(b.get("striker_id"), b.get("striker_id")),
            non_striker_id=player_id_map.get(b.get("non_striker_id"), b.get("non_striker_id")),
            bowler_id=player_id_map.get(b.get("bowler_id"), b.get("bowler_id")),
            runs_batter=b.get("runs_batter", 0),
            runs_extras=b.get("runs_extras", 0),
            extra_type=b.get("extra_type"),
            penalty_runs=b.get("penalty_runs", 0),
            is_wicket=b.get("is_wicket", False),
            dismissal_mode=b.get("dismissal_mode"),
            fielder_id=player_id_map.get(b.get("fielder_id"), b.get("fielder_id")) if b.get("fielder_id") else None,
            short_runs=b.get("short_runs", 0),
            boundary_type=b.get("boundary_type"),
            is_free_hit=b.get("is_free_hit", False),
            is_valid_ball=b.get("is_valid_ball", True),
            is_over_completed=b.get("is_over_completed", False),
            is_shot_out=b.get("is_shot_out", False),
        )
        db.add(ball)

    db.commit()
    new_match.checksum = compute_checksum(new_match, db)
    db.commit()
    db.refresh(new_match)
    return {"match_id": new_match.id, "message": "Match imported successfully", "imported_balls": len(balls_data)}


@app.get("/matches/{match_id}/export/pdf", response_model=None)
def export_match_pdf(match_id: int, db = Depends(get_db)):
    """Export scorecard as a formatted PDF."""
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors

    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("Cric-Scorer - Match Scorecard", styles["Title"]))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f"<b>Match:</b> {match.team_a_name} vs {match.team_b_name}", styles["Normal"]))
    elements.append(Paragraph(f"<b>Format:</b> {match.format} | <b>Overs:</b> {match.overs_per_innings}", styles["Normal"]))
    elements.append(Paragraph(f"<b>Status:</b> {match.status}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    for innings_id in (1, 2):
        sc = compute_full_scorecard(db, match_id, innings_id)
        if sc["batting"]:
            elements.append(Paragraph(f"<b>Innings {innings_id} - Batting</b>", styles["Heading2"]))
            b_data = [["Batter", "Runs", "Balls", "4s", "6s", "SR", "Dismissal"]]
            for b in sc["batting"]:
                b_data.append([b["name"], str(b["runs"]), str(b["balls"]), str(b["fours"]), str(b["sixes"]), str(b["strike_rate"]), b["dismissal_mode"] or "not out"])
            t = Table(b_data)
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.navy),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ]))
            elements.append(t)
            elements.append(Spacer(1, 12))

    doc.build(elements)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="match_{match_id}_scorecard.pdf"'},
    )


@app.get("/matches/{match_id}/export/json", response_model=None)
def export_match_json(match_id: int, db = Depends(get_db)):
    """Export full match data as JSON."""
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return _match_to_dict(db, match)


@app.get("/matches/{match_id}/export/csv", response_model=None)
def export_match_csv(match_id: int, db = Depends(get_db)):
    """Export match scorecard as CSV."""
    import csv
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Match", f"{match.team_a_name} vs {match.team_b_name}"])
    writer.writerow(["Format", match.format])
    writer.writerow(["Overs per Innings", match.overs_per_innings])
    writer.writerow(["Status", match.status])
    writer.writerow([])

    for innings_id in (1, 2):
        sc = compute_full_scorecard(db, match_id, innings_id)
        if sc["batting"]:
            writer.writerow([f"--- Innings {innings_id} Batting ---"])
            writer.writerow(["Batter", "Runs", "Balls", "4s", "6s", "SR", "Dismissal"])
            for b in sc["batting"]:
                writer.writerow([b["name"], b["runs"], b["balls"], b["fours"], b["sixes"], b["strike_rate"], b["dismissal_mode"] or "not out"])
            writer.writerow([])

        if sc["bowling"]:
            writer.writerow([f"--- Innings {innings_id} Bowling ---"])
            writer.writerow(["Bowler", "Overs", "Maidens", "Runs", "Wickets", "Wides", "No-Balls", "Economy"])
            for bw in sc["bowling"]:
                writer.writerow([bw["name"], bw["overs"], bw["maidens"], bw["runs"], bw["wickets"], bw["wides"], bw["no_balls"], bw["economy"]])
            writer.writerow([])

    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="match_{match_id}_scorecard.csv"'},
    )


# ── Module 13: MVP Endpoints ──

@app.get("/matches/{match_id}/mvp/candidates", response_model=None)
def get_mvp_candidates(match_id: int, db = Depends(get_db)):
    """Return ranked list of MVP candidates with points breakdown from delivery log."""
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    candidates = calculate_mvp_points(db, match_id)
    winning_team_id = _get_winning_team_id(db, match_id)
    if winning_team_id:
        for c in candidates:
            if c.team_id == winning_team_id:
                c.breakdown.points_win_bonus = 10
                c.total_points += 10
        candidates.sort(key=lambda c: c.total_points, reverse=True)

    squad_map = {}
    squads = db.query(MatchSquad).filter(MatchSquad.match_id == match_id).all()
    for sq in squads:
        player = db.query(Player).filter(Player.id == sq.player_id).first()
        squad_map[sq.player_id] = player.role if player else ("substitute" if sq.is_substitute else "player")

    xi_map = {}
    xis = db.query(PlayingXI).filter(PlayingXI.match_id == match_id).all()
    for xi in xis:
        xi_map[xi.player_id] = {"is_captain": xi.is_captain, "is_wicketkeeper": xi.is_wicketkeeper}

    for c in candidates:
        c.team_role = squad_map.get(c.player_id, "player")
        if c.player_id in xi_map:
            if xi_map[c.player_id]["is_captain"]:
                c.team_role = "captain (" + c.team_role + ")"
            elif xi_map[c.player_id]["is_wicketkeeper"]:
                c.team_role = "wicketkeeper (" + c.team_role + ")"

    return {
        "match_id": match_id,
        "candidates": [
            {
                "player_id": c.player_id,
                "name": c.name,
                "team_id": c.team_id,
                "team_role": c.team_role,
                "total_points": c.total_points,
                "breakdown": c.breakdown.model_dump(),
            }
            for c in candidates
        ],
    }


@app.post("/matches/{match_id}/mvp/award", response_model=None)
def award_mvp(
    match_id: int,
    award_request: MvpAwardRequest,
    db = Depends(get_db),
    current_session = Depends(get_current_session),
):
    """Award MVP to a player for a match. Initiator or approved scorer can award."""
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    stmt_role = select(MatchRole).where(MatchRole.match_id == match_id, MatchRole.session_id == current_session.session_id)
    result = db.execute(stmt_role)
    role = result.scalar_one_or_none()
    if not role or (role.role != "initiator" and not role.scoring_rights):
        raise HTTPException(status_code=403, detail="Only the initiator or approved scorer can award MVP")

    # FR-7.4: MVP award only allowed after match is completed/locked
    if match.status not in ("completed", "locked"):
        raise HTTPException(status_code=400, detail="MVP can only be awarded after match is completed or locked")

    player = db.query(Player).filter(Player.id == award_request.player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    existing_mvp = db.query(MVP).filter(MVP.match_id == match_id).first()
    if existing_mvp:
        existing_mvp.player_id = award_request.player_id
        existing_mvp.points = award_request.points
        existing_mvp.reason_summary = award_request.reason_summary
        existing_mvp.awarded_by_session_id = current_session.session_id
        existing_mvp.awarded_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(existing_mvp)
        mvp = existing_mvp
    else:
        mvp = MVP(
            match_id=match_id,
            player_id=award_request.player_id,
            points=award_request.points,
            reason_summary=award_request.reason_summary,
            awarded_by_session_id=current_session.session_id,
            awarded_at=datetime.now(timezone.utc),
        )
        db.add(mvp)
        db.commit()
        db.refresh(mvp)

    audit_log(db, current_session.session_id, "mvp_awarded", match_id, str(player.id), f'{{"player_id": {player.id}, "points": {award_request.points}}}')
    return MVPResponse(
        id=mvp.id,
        match_id=mvp.match_id,
        player_id=mvp.player_id,
        points=mvp.points,
        reason_summary=mvp.reason_summary,
        awarded_by_session_id=mvp.awarded_by_session_id,
        awarded_at=mvp.awarded_at,
    )


@app.get("/matches/{match_id}/mvp", response_model=None)
def get_mvp(match_id: int, db = Depends(get_db)):
    """Return awarded MVP for a match (public)."""
    mvp = db.query(MVP).filter(MVP.match_id == match_id).first()
    if not mvp:
        return {"match_id": match_id, "mvp": None}

    player = db.query(Player).filter(Player.id == mvp.player_id).first()
    return {
        "match_id": match_id,
        "mvp": {
            "id": mvp.id,
            "player_id": mvp.player_id,
            "player_name": player.name if player else f"Player {mvp.player_id}",
            "points": mvp.points,
            "reason_summary": mvp.reason_summary,
            "awarded_by_session_id": mvp.awarded_by_session_id,
            "awarded_at": mvp.awarded_at.isoformat() if mvp.awarded_at else None,
        },
    }


# ── Module 9.7: Auto-close Inactive Matches ──

def auto_close_inactive_matches(db, hours: int = 24):
    """Close matches in progress for more than `hours` hours (FR-10.4)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    inactive = (
        db.query(Match)
        .filter(Match.status == "in_progress")
        .filter(Match.updated_at < cutoff)
        .all()
    )
    closed_count = 0
    for match in inactive:
        match.status = "completed"
        match.locked_at = datetime.now(timezone.utc)
        match.updated_at = datetime.now(timezone.utc)
        audit_log(
            db,
            "system",
            "auto_closed_inactive",
            match.id,
            str(match.id),
            '{"reason": "no_activity", "hours": %d}' % hours,
        )
        closed_count += 1
    db.commit()
    return closed_count


@app.post("/matches/auto-close-inactive", response_model=None)
def auto_close_inactive_endpoint(hours: int = 24, db = Depends(get_db)):
    """Trigger auto-close of inactive matches."""
    closed_count = auto_close_inactive_matches(db, hours=hours)
    return {
        "closed": closed_count,
        "message": f"{closed_count} inactive match(es) closed",
    }
