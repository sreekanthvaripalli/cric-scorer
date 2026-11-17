from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from time import time

from .database import AnonymousSession, Match, MatchRole, Base, get_session_local, Team, Player, MatchTeamLink, MatchSquad, PlayingXI, Toss, FormatConfig, Ball, AuditLog
from .websocket_manager import manager
from .models import (
    AnonymousSessionCreate, AnonymousSessionResponse, MatchCreate,
    MatchResponse, MatchPublicResponse, MatchRoleCreate, MatchRoleResponse,
    ScoringRightRequestCreate, ScoringRightRequestResponse, BallRecord,
    BallRecordResponse, ConfirmScoresRequest, LockMatchRequest, MvpAwardRequest,
    TeamResponse, PlayerResponse, MatchTeamLinkResponse, MatchSquadResponse,
    PlayingXIResponse, TossResponse, FormatConfigResponse, TeamData,
    Player as PlayerRequest, XIEntry, TossCallData, TossFlipData, TossResultData,
    BattingScorecardEntry, BowlingAnalysisEntry, ExtrasSummary,
    FallOfWicketEntry, InningsScorecard, MatchScorecard, MatchResult,
    FollowOnStatus, SuperOverStatus, LockMatchResponse,
)

app = FastAPI(title="Cric-Scorer API", version="0.0.1")

# ── Module 9: Rate Limiting Middleware ──
_rate_limit_store: dict = defaultdict(list)
RATE_LIMIT_REQUESTS = 100  # max requests per window
RATE_LIMIT_WINDOW = 60  # seconds


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
    )
    db.add(entry)
    db.commit()
    return entry

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
    # If match_id is specified, only initiator can view
    if match_id is not None:
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


# ---- Module 2: Scorer workflow endpoints ----
@app.post("/matches", status_code=201, response_model=None)
def create_match(match_data: MatchCreate, db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    new_match = Match(name=f"{match_data.team_a_name} vs {match_data.team_b_name}", team_a_name=match_data.team_a_name, team_b_name=match_data.team_b_name, format=match_data.format, overs_per_innings=match_data.overs_per_innings, balls_per_over=match_data.balls_per_over, status="created", initiator_session_id=current_session.session_id, checksum=None)
    db.add(new_match)
    db.commit()
    db.refresh(new_match)
    role = MatchRole(match_id=new_match.id, session_id=current_session.session_id, role="initiator", scoring_rights=True, approved_by_session_id=None, approved_at=None)
    db.add(role)
    db.commit()
    audit_log(db, current_session.session_id, "match_created", new_match.id, str(new_match.id), '{"team_a": "%s", "team_b": "%s"}' % (match_data.team_a_name, match_data.team_b_name))
    return MatchResponse(id=new_match.id, name=new_match.name, team_a_name=new_match.team_a_name, team_b_name=new_match.team_b_name, format=new_match.format, overs_per_innings=new_match.overs_per_innings, balls_per_over=new_match.balls_per_over, status=new_match.status, initiator_session_id=new_match.initiator_session_id, checksum=new_match.checksum, created_at=new_match.created_at, updated_at=new_match.updated_at, locked_at=str(new_match.locked_at) if new_match.locked_at else None)


@app.get("/matches/{match_id}/public", response_model=None)
def match_public(match_id: int, db = Depends(get_db)) -> dict:
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return MatchPublicResponse(match_id=match.id, team_a_name=match.team_a_name, team_b_name=match.team_b_name, format=match.format, overs_per_innings=match.overs_per_innings, current_score="0/0", current_overs=0.0, wickets=0, status=match.status, last_updated=match.updated_at)


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
        request_row = MatchRole(match_id=match_id, session_id=current_session.session_id, role="requester", scoring_rights=False, approved_by_session_id=None, approved_at=None)
        db.add(request_row)
        db.commit()
        db.refresh(request_row)
    audit_log(db, current_session.session_id, "scoring_rights_requested", match_id, str(request_row.id), '{"device_name": "%s"}' % (request_data.device_name or ""))
    return ScoringRightRequestResponse(id=request_row.id, match_id=match_id, requestor_session_id=current_session.session_id, device_name=request_data.device_name, status="pending", requested_at=datetime.now(timezone.utc), approved_at=None)


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
def revoke_scoring_rights(match_id: int, db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.initiator_session_id != current_session.session_id:
        raise HTTPException(status_code=403, detail="Only the match initiator can revoke scoring rights")
    if match.status == "locked":
        raise HTTPException(status_code=400, detail="Cannot revoke scoring rights; match is locked")
    stmt_role = select(MatchRole).where(MatchRole.match_id == match_id, MatchRole.role == "scorer")
    result = db.execute(stmt_role)
    scorer_roles = result.scalars().all()
    if not scorer_roles:
        raise HTTPException(status_code=404, detail="No scorer found with scoring rights")
    for role in scorer_roles:
        role.role = "watcher"
        role.scoring_rights = False
        role.approved_by_session_id = None
        role.approved_at = None
    db.commit()
    audit_log(db, current_session.session_id, "scoring_rights_revoked", match_id, None, '{"revoked_count": %d}' % len(scorer_roles))
    return {"message": "Scoring rights revoked for all scorers", "match_status": match.status}

@app.post("/matches/{match_id}/transfer-ownership", response_model=None)
def transfer_ownership(match_id: int, new_initiator_session_id: str, db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.initiator_session_id != current_session.session_id:
        raise HTTPException(status_code=403, detail="Only the match initiator can transfer ownership")
    stmt_role = select(MatchRole).where(MatchRole.match_id == match_id, MatchRole.session_id == new_initiator_session_id, MatchRole.role == "scorer", MatchRole.scoring_rights == True)
    result = db.execute(stmt)
    new_initiator_role = result.scalar_one_or_none()
    if not new_initiator_role:
        raise HTTPException(status_code=400, detail="Target session must have approved scorer rights to transfer ownership")
    match.initiator_session_id = new_initiator_session_id
    match.updated_at = datetime.now(timezone.utc)
    db.commit()
    stmt_old_role = select(MatchRole).where(MatchRole.match_id == match_id, MatchRole.role == "initiator")
    result = db.execute(stmt_old_role)
    old_initiator_role = result.scalar_one_or_none()
    if old_initiator_role:
        old_initiator_role.role = "watcher"
        old_initiator_role.scoring_rights = False
    db.commit()
    audit_log(db, current_session.session_id, "ownership_transferred", match_id, new_initiator_session_id, '{"from": "%s", "to": "%s"}' % (match.initiator_session_id, new_initiator_session_id))
    return {"message": "Match ownership transferred", "new_initiator": new_initiator_session_id, "match_id": match_id}


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
        requests.append(ScoringRightRequestResponse(id=role.id, match_id=role.match_id, requestor_session_id=role.session_id, device_name=None, status="pending", requested_at=role.created_at, approved_at=None))
    return requests


@app.post("/matches/{match_id}/balls", response_model=None)
def record_ball(match_id: int, ball_data: BallRecordRequest, db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    """Record one delivery atomically.

    Validates all cricketing rules:
    - Runs 0-6, boundary greater-of (Law 19.7)
    - Bowler not consecutive overs (Law 17.6), max overs per format
    - Extras: no ball (+1 penalty, not in over, sets free-hit), wide (+1, not in over), bye/leg-bye, penalty
    - No ball overrides Wide (Law 21.12)
    - Dismissals: all 10 modes with context validation
    - Strike rotation per Laws 18.11/18.12

    Requires scoring_rights=true or role=initiator.
    Toss must be completed before recording balls.
    """
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
    # Get current innings (1 or 2)
    innings_id = 1  # Simplified - would check if first innings complete
    from app.scoring.engine import process_ball
    try:
        response = process_ball(db, match, ball_data, role, innings_id, True)
        audit_log(db, current_session.session_id, "ball_recorded", match_id, str(response.get("ball_id", "")), '{"delivery_type": "%s"}' % ball_data.delivery_type)
        return response
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/matches/{match_id}/balls/{ball_id}/undo", response_model=None)
def undo_ball(match_id: int, ball_id: int, db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    """Rollback the last delivery and restore previous state.

    - Deletes the specified ball record
    - Recomputes checksum
    - Updates match state
    """
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
    # Get the ball to verify ownership
    ball = db.query(Ball).filter(Ball.id == ball_id, Ball.match_id == match_id).first()
    if not ball:
        raise HTTPException(status_code=404, detail="Ball not found")
    # Delete the ball
    db.delete(ball)
    # Recompute checksum
    match.checksum = compute_checksum(match)
    match.updated_at = datetime.now(timezone.utc)
    db.commit()
    audit_log(db, current_session.session_id, "ball_undone", match_id, str(ball_id), None)
    return {"message": "Delivery undone", "match_id": match_id, "checksum": match.checksum}


@app.get("/matches/{match_id}/checksum", response_model=None)
def get_match_checksum(match_id: int, db = Depends(get_db)) -> dict:
    """Get the current checksum of the match.

    The checksum is recomputed after every delivery and provides
    a cryptographic fingerprint of the match state for integrity verification.
    """
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    # Recompute checksum from current state
    checksum = compute_checksum(match)
    return {"match_id": match_id, "checksum": checksum, "computed_at": datetime.now(timezone.utc)}


@app.post("/matches/{match_id}/undo", response_model=None)
def undo_last_ball(match_id: int, db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
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
    if role.role == "initiator":
        has_rights = True
    elif role.scoring_rights:
        has_rights = True
    else:
        has_rights = False
    if not has_rights:
        raise HTTPException(status_code=403, detail="Scoring rights required to undo deliveries. Request approval from the initiator.")
    return {"message": "Last ball undo initiated", "match_id": match_id, "undone_by": current_session.session_id}


@app.post("/matches/{match_id}/squad", status_code=201, response_model=None)
def add_players_to_squad(match_id: int, squad_data: List[PlayerRequest], db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    for player_data in squad_data:
        player = Player(team_id=player_data.team_id, name=player_data.name, role=player_data.role, jersey_number=player_data.jersey_number, is_substitute=player_data.is_substitute)
        db.add(player)
        db.commit()
        db.refresh(player)
        squad = MatchSquad(match_id=match_id, player_id=player.id, team_id=player.team_id, is_substitute=player_data.is_substitute)
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
        xi = PlayingXI(match_id=match_id, player_id=xi_entry.player_id, team_id=xi_entry.team_id, is_captain=xi_entry.is_captain, is_wicketkeeper=xi_entry.is_wicketkeeper)
        db.add(xi)
        db.commit()
    return {"message": f"Set playing XI for {len(xi_data)} players", "match_id": match_id}




@app.get("/formats", response_model=None)
def list_formats():
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


"""Module 3: Teams, players, squads, format config & online toss."""

# ---- Module 3: Teams ----
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


# ---- Module 12: Online Toss (Heads / Tails) ----
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
    import secrets
    call = toss.initiator_call.lower()
    coin_result = secrets.choice(["heads", "tails"])
    is_match = (call == coin_result)
    winner_team_id = 1 if is_match else 2
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
        match.status = 'toss_complete'
        match.updated_at = datetime.now(timezone.utc)
        db.commit()
    return TossResponse(id=toss.id, match_id=match_id, initiator_call=toss.initiator_call, coin_result=toss.coin_result, winner_team_id=toss.winner_team_id, toss_decision=toss.toss_decision, called_by_session_id=toss.called_by_session_id, created_at=toss.created_at)


# ── Module 5: Live Score Broadcasting & Public Watch ─────────────────────────


@app.get("/matches/{match_id}/live", response_model=None)
def get_match_live(match_id: int, db = Depends(get_db)) -> dict:
    """Polling fallback for clients without WebSocket support.

    Returns current match state: score, overs, wickets, last deliveries.
    """
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    # Get the last 10 balls
    balls = db.query(Ball).filter(Ball.match_id == match_id).order_by(Ball.id.desc()).limit(10).all()
    balls.reverse()

    # Compute current score per innings
    runs_by_innings = {1: 0, 2: 0}
    wickets_by_innings = {1: 0, 2: 0}
    for ball in balls:
        if ball.innings_id in runs_by_innings:
            runs_by_innings[ball.innings_id] += ball.runs_batter + ball.runs_extras
        if ball.is_wicket:
            wickets_by_innings[ball.innings_id] += 1

    current_score = f"{runs_by_innings[1]}/{wickets_by_innings[1]}" if runs_by_innings[1] > 0 else "0/0"

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
        "ball": {
            "delivery": [
                {
                    "ball_id": b.ball_id,
                    "over_number": b.over_number,
                    "ball_number": b.ball_number,
                    "striker_id": b.striker_id,
                    "non_striker_id": b.non_striker_id,
                    "bowler_id": b.bowler_id,
                    "runs_batter": b.runs_batter,
                    "runs_extras": b.runs_extras,
                    "extra_type": b.extra_type,
                    "is_wicket": b.is_wicket,
                    "dismissal_mode": b.dismissal_mode,
                    "boundary_type": b.boundary_type,
                }
                for b in balls
            ],
            "overs": round(sum(b.over_number + b.ball_number / 6.0 for b in balls) / max(1, len(balls)), 1),
            "striker_runs": balls[0].runs_batter if balls else 0,
            "non_striker_runs": balls[0].runs_batter if balls else 0,
            "wickets_a": wickets_by_innings[1],
            "wickets_b": wickets_by_innings[2],
        } if balls else None,
        "toss": None,
        "presence": {
            "is_connected": True,
            "connections": manager.get_connection_count(match_id),
        },
    }


@app.websocket("/ws/match/{match_id}")
async def websocket_match(websocket: WebSocket, match_id: int):
    """WebSocket endpoint for live score broadcasting.

    Scorers and watchers connect here. The server broadcasts match state
    (new deliveries, undo, result changes) to all connected clients in real-time.
    """
    await manager.connect(websocket, match_id)

    try:
        # Send initial state to the newly connected client
        initial_state = {
            "match": {
                "id": match_id,
                "name": "Loading...",
                "team_a_name": "Team A",
                "team_b_name": "Team B",
                "format": "Custom",
                "overs_per_innings": 20,
                "status": "in_progress",
            },
            "ball": None,
            "toss": None,
            "presence": {"is_connected": True, "connections": manager.get_connection_count(match_id)},
            "type": "initial_state",
        }
        await manager.broadcast(match_id, initial_state)

        # Keep connection alive - receive messages to detect disconnect
        while True:
            data = await websocket.receive_text()
            # Client heartbeat - ignore content but keep connection alive
    except WebSocketDisconnect:
        manager.disconnect(websocket, match_id)
    except Exception as e:
        print(f"WebSocket error for match {match_id}: {e}")
        manager.disconnect(websocket, match_id)



# ── Module 6: Scorecard, Statistics & Match Result ───────────────────────────


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
    if len(innings_list) == 2:
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
    result_data = compute_match_result(db, match_id)
    return result_data


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
    match.status = "locked"
    match.locked_at = datetime.now(timezone.utc)
    match.updated_at = datetime.now(timezone.utc)
    db.commit()
    audit_log(db, current_session.session_id, "match_locked", match_id, None, '{"status": "locked"}')
    return {
        "match_id": match_id,
        "status": match.status,
        "locked_at": str(match.locked_at) if match.locked_at else None,
        "message": "Match locked successfully",
    }

@app.post("/import/json", response_model=None)
def import_match_json(import_data: dict, db = Depends(get_db), current_session = Depends(get_current_session)):
    match_data = import_data.get("match", {})
    if not match_data:
        raise HTTPException(status_code=400, detail="No match data in import")
    db_path = _get_db_path()
    if db_path:
        _backup_db(db_path)
    new_match = Match(name=match_data.get("name", f"Imported Match {datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"), team_a_name=match_data.get("team_a_name", "Team A"), team_b_name=match_data.get("team_b_name", "Team B"), format=match_data.get("format", "Custom"), overs_per_innings=match_data.get("overs_per_innings", 20), balls_per_over=match_data.get("balls_per_over", 6), status="created", initiator_session_id=current_session.session_id, checksum=None)
    db.add(new_match)
    db.commit()
    db.refresh(new_match)
    role = MatchRole(match_id=new_match.id, session_id=current_session.session_id, role="initiator", scoring_rights=True, approved_by_session_id=None, approved_at=None, created_at=datetime.now(timezone.utc))
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
        new_player = Player(match_id=new_match.id, team_id=p.get("team_id"), name=p.get("name", "Unknown"), role=p.get("role", "all-rounder"), jersey_number=p.get("jersey_number"), is_substitute=p.get("is_substitute", False))
        db.add(new_player)
        db.flush()
        if old_id:
            player_id_map[old_id] = new_player.id
    squads_data = import_data.get("squads", [])
    for s in squads_data:
        squad = MatchSquad(match_id=new_match.id, player_id=player_id_map.get(s.get("player_id", s.get("player_id"))), team_id=s.get("team_id"), is_substitute=s.get("is_substitute", False))
        db.add(squad)
    xis_data = import_data.get("playing_xi", [])
    for xi in xis_data:
        xi_entry = PlayingXI(match_id=new_match.id, player_id=player_id_map.get(xi.get("player_id", xi.get("player_id"))), team_id=xi.get("team_id"), is_captain=xi.get("is_captain", False), is_wicketkeeper=xi.get("is_wicketkeeper", False))
        db.add(xi_entry)
    toss_data = import_data.get("toss")
    if toss_data:
        toss = Toss(match_id=new_match.id, initiator_call=toss_data.get("initiator_call"), coin_result=toss_data.get("coin_result"), winner_team_id=toss_data.get("winner_team_id"), toss_decision=toss_data.get("toss_decision"), called_by_session_id=toss_data.get("called_by_session_id"))
        db.add(toss)
    balls_data = import_data.get("balls", [])
    for b in balls_data:
        ball = Ball(match_id=new_match.id, innings_id=b.get("innings_id", 1), over_number=b.get("over_number", 1), ball_number=b.get("ball_number", 1), striker_id=player_id_map.get(b.get("striker_id"), b.get("striker_id")), non_striker_id=player_id_map.get(b.get("non_striker_id"), b.get("non_striker_id")), bowler_id=player_id_map.get(b.get("bowler_id"), b.get("bowler_id")), runs_batter=b.get("runs_batter", 0), runs_extras=b.get("runs_extras", 0), extra_type=b.get("extra_type"), penalty_runs=b.get("penalty_runs", 0), is_wicket=b.get("is_wicket", False), dismissal_mode=b.get("dismissal_mode"), fielder_id=player_id_map.get(b.get("fielder_id"), b.get("fielder_id")) if b.get("fielder_id") else None, short_runs=b.get("short_runs", 0), boundary_type=b.get("boundary_type"), is_free_hit=b.get("is_free_hit", False), is_valid_ball=b.get("is_valid_ball", True), is_over_completed=b.get("is_over_completed", False), is_shot_out=b.get("is_shot_out", False))
        db.add(ball)
    db.commit()
    db.refresh(new_match)
    return {"match_id": new_match.id, "message": "Match imported successfully", "imported_balls": len(balls_data)}
@app.get("/matches/{match_id}/export/pdf", response_model=None)
def export_match_pdf(match_id: int, db = Depends(get_db)):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
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
    player_map = {}
    for p in db.query(Player).all():
        player_map[p.id] = p.name
    for innings_id in (1, 2):
        balls = db.query(Ball).filter(Ball.match_id == match_id, Ball.innings_id == innings_id, Ball.is_valid_ball == True).order_by(Ball.id).all()
        if not balls:
            continue
        elements.append(Paragraph(f"Innings {innings_id}", styles["Heading2"]))
        elements.append(Spacer(1, 6))
        batters = {}
        for b in balls:
            pid = b.striker_id
            if pid not in batters:
                batters[pid] = {"runs": 0, "balls": 0, "fours": 0, "sixes": 0, "dismissal": None}
            batters[pid]["runs"] += b.runs_batter
            batters[pid]["balls"] += 1
            if b.boundary_type == "4":
                batters[pid]["fours"] += 1
            elif b.boundary_type == "6":
                batters[pid]["sixes"] += 1
            if b.is_wicket and b.striker_id == pid:
                batters[pid]["dismissal"] = b.dismissal_mode or "out"
        batting_data = [["Player", "Runs", "Balls", "4s", "6s", "SR", "Dismissal"]]
        total_runs = 0
        total_wickets = 0
        for pid, data in batters.items():
            sr = round((data["runs"] / data["balls"]) * 100, 2) if data["balls"] > 0 else 0.0
            total_runs += data["runs"]
            if data["dismissal"]:
                total_wickets += 1
            batting_data.append([player_map.get(pid, f"Player {pid}"), str(data["runs"]), str(data["balls"]), str(data["fours"]), str(data["sixes"]), str(sr), data["dismissal"] or ""])
        batting_data.append(["Total", str(total_runs), "", "", "", "", f"{total_wickets} wkts"])
        bt = Table(batting_data)
        bt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.grey), ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke), ("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("ALIGN", (1, 0), (-1, -1), "CENTER")]))
        elements.append(bt)
        elements.append(Spacer(1, 12))
        bowlers = {}
        for b in balls:
            pid = b.bowler_id
            if pid not in bowlers:
                bowlers[pid] = {"overs_count": 0.0, "maidens": 0, "runs": 0, "wickets": 0, "wides": 0, "no_balls": 0}
            bowlers[pid]["overs_count"] += b.ball_number / 6.0
            bowlers[pid]["runs"] += b.runs_batter + b.runs_extras
            if b.is_wicket:
                bowlers[pid]["wickets"] += 1
            if b.extra_type == "wd":
                bowlers[pid]["wides"] += 1
            elif b.extra_type == "nb":
                bowlers[pid]["no_balls"] += 1
        bowling_data = [["Player", "Overs", "Mdns", "Runs", "Wkts", "Wides", "NB", "Econ"]]
        for pid, data in bowlers.items():
            over_whole = int(data["overs_count"])
            over_balls = round((data["overs_count"] - over_whole) * 6)
            over_str = f"{over_whole}.{over_balls}"
            econ = round(data["runs"] / data["overs_count"], 2) if data["overs_count"] > 0 else 0.0
            bowling_data.append([player_map.get(pid, f"Player {pid}"), over_str, str(data["maidens"]), str(data["runs"]), str(data["wickets"]), str(data["wides"]), str(data["no_balls"]), str(econ)])
        bl = Table(bowling_data)
        bl.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.grey), ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke), ("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("ALIGN", (1, 0), (-1, -1), "CENTER")]))
        elements.append(bl)
        elements.append(Spacer(1, 12))
    doc.build(elements)
    output.seek(0)
    return StreamingResponse(output, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="match_{match_id}_scorecard.pdf"'})
@app.get("/matches/{match_id}/export/json", response_model=None)
def export_match_json(match_id: int, db = Depends(get_db)):
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    data = _match_to_dict(db, match)
    return data


@app.get("/matches/{match_id}/export/csv", response_model=None)
def export_match_csv(match_id: int, db = Depends(get_db)):
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Cric-Scorer Match Export"])
    writer.writerow([f"Match: {match.name} ({match.team_a_name} vs {match.team_b_name})"])
    writer.writerow([f"Format: {match.format}, Overs: {match.overs_per_innings}"])
    writer.writerow([f"Status: {match.status}"])
    writer.writerow([])
    for innings_id in (1, 2):
        balls = db.query(Ball).filter(Ball.match_id == match_id, Ball.innings_id == innings_id, Ball.is_valid_ball == True).order_by(Ball.id).all()
        if not balls:
            continue
        writer.writerow([f"=== Innings {innings_id} ==="])
        writer.writerow([])
        writer.writerow(["Batting Scorecard"])
        writer.writerow(["Player", "Runs", "Balls", "4s", "6s", "SR", "Dismissal"])
        batters = {}
        for b in balls:
            pid = b.striker_id
            if pid not in batters:
                batters[pid] = {"runs": 0, "balls": 0, "fours": 0, "sixes": 0, "dismissal": None}
            batters[pid]["runs"] += b.runs_batter
            batters[pid]["balls"] += 1
            if b.boundary_type == "4":
                batters[pid]["fours"] += 1
            elif b.boundary_type == "6":
                batters[pid]["sixes"] += 1
            if b.is_wicket and b.striker_id == pid:
                batters[pid]["dismissal"] = b.dismissal_mode or "out"
        player_map = {}
        for p in db.query(Player).all():
            player_map[p.id] = p.name
        for pid, data in batters.items():
            sr = round((data["runs"] / data["balls"]) * 100, 2) if data["balls"] > 0 else 0.0
            writer.writerow([player_map.get(pid, f"Player {pid}"), data["runs"], data["balls"], data["fours"], data["sixes"], sr, data["dismissal"] or ""])
        writer.writerow([])
        writer.writerow(["Bowling Analysis"])
        writer.writerow(["Player", "Overs", "Maidens", "Runs", "Wickets", "Wides", "No Balls", "Economy"])
        bowlers = {}
        for b in balls:
            pid = b.bowler_id
            if pid not in bowlers:
                bowlers[pid] = {"overs_count": 0.0, "maidens": 0, "runs": 0, "wickets": 0, "wides": 0, "no_balls": 0}
            bowlers[pid]["overs_count"] += b.ball_number / 6.0
            bowlers[pid]["runs"] += b.runs_batter + b.runs_extras
            if b.is_wicket:
                bowlers[pid]["wickets"] += 1
            if b.extra_type == "wd":
                bowlers[pid]["wides"] += 1
            elif b.extra_type == "nb":
                bowlers[pid]["no_balls"] += 1
        for pid, data in bowlers.items():
            over_whole = int(data["overs_count"])
            over_balls = round((data["overs_count"] - over_whole) * 6)
            over_str = f"{over_whole}.{over_balls}"
            econ = round(data["runs"] / data["overs_count"], 2) if data["overs_count"] > 0 else 0.0
            writer.writerow([player_map.get(pid, f"Player {pid}"), over_str, data["maidens"], data["runs"], data["wickets"], data["wides"], data["no_balls"], econ])
        writer.writerow([])
        writer.writerow(["Extras Summary"])
        no_balls = sum(1 for b in balls if b.extra_type == "nb")
        wides = sum(1 for b in balls if b.extra_type == "wd")
        byes = sum(1 for b in balls if b.extra_type == "bye")
        leg_byes = sum(1 for b in balls if b.extra_type == "legbye")
        penalties = sum(b.penalty_runs for b in balls)
        total_extras = sum(b.runs_extras for b in balls) + penalties
        writer.writerow(["No Balls", no_balls])
        writer.writerow(["Wides", wides])
        writer.writerow(["Byes", byes])
        writer.writerow(["Leg Byes", leg_byes])
        writer.writerow(["Penalties", penalties])
        writer.writerow(["Total Extras", total_extras])
        writer.writerow([])
    output.seek(0)
    return StreamingResponse(io.BytesIO(output.getvalue().encode("utf-8")), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=match_" + str(match_id) + "_scorecard.csv"})
def _match_to_dict(db, match):
    team_links = db.query(MatchTeamLink).filter(MatchTeamLink.match_id == match.id).all()
    teams = [{"team_id": tl.team_id, "team_role": tl.team_role, "is_home": tl.is_home} for tl in team_links]
    players = db.query(Player).all()
    players_list = [{"id": p.id, "team_id": p.team_id, "name": p.name, "role": p.role, "jersey_number": p.jersey_number, "is_substitute": p.is_substitute} for p in players]
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
    return {"match": {"id": match.id, "name": match.name, "venue": match.venue, "date": str(match.date) if match.date else None, "format": match.format, "overs_per_innings": match.overs_per_innings, "balls_per_over": match.balls_per_over, "status": match.status, "initiator_session_id": match.initiator_session_id, "checksum": match.checksum, "created_at": str(match.created_at) if match.created_at else None, "updated_at": str(match.updated_at) if match.updated_at else None, "locked_at": str(match.locked_at) if match.locked_at else None, "team_a_name": match.team_a_name, "team_b_name": match.team_b_name}, "teams": teams, "players": players_list, "squads": squads_list, "playing_xi": xis_list, "toss": toss_data, "format_configs": formats_list, "balls": balls_list}


def _backup_db(db_path):
    if not db_path or not os.path.exists(db_path):
        return None
    backup_path = f"{db_path}.bak"
    shutil.copy2(db_path, backup_path)
    return backup_path
from sqlalchemy import select

from app.database import DATABASE_URL

# ── Module 7: Persistence, Export & Import ────────────────────────────────

import os
import csv
import io
import json
import shutil
from fastapi.responses import StreamingResponse


def _get_db_path():
    url = DATABASE_URL
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "")
    return None
