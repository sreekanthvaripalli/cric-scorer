from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid
from datetime import datetime, timezone

from .database import AnonymousSession, Match, MatchRole, Base, get_session_local, Team, Player, MatchTeamLink, MatchSquad, PlayingXI, Toss, FormatConfig, Ball
from .websocket_manager import manager
from .models import (
    AnonymousSessionCreate, AnonymousSessionResponse, MatchCreate,
    MatchResponse, MatchPublicResponse, MatchRoleCreate, MatchRoleResponse,
    ScoringRightRequestCreate, ScoringRightRequestResponse, BallRecord,
    BallRecordResponse, ConfirmScoresRequest, LockMatchRequest, MvpAwardRequest,
    TeamResponse, PlayerResponse, MatchTeamLinkResponse, MatchSquadResponse,
    PlayingXIResponse, TossResponse, FormatConfigResponse, TeamData,
    Player as PlayerRequest, XIEntry, TossCallData, TossFlipData, TossResultData,
)

app = FastAPI(title="Cric-Scorer API", version="0.0.1")

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
    return {"message": "Scoring rights approved", "request_id": request_id, "granted_to_session": role.session_id, "role": role.role, "scoring_rights": role.scoring_rights}


@app.post("/matches/{match_id}/scoring-requests/{request_id}/reject", response_model=None)
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
    return {"message": "Scoring rights revoked for all scorers", "match_status": match.status}
def reject_scoring_request(match_id: int, request_id: int, db = Depends(get_db), current_session = Depends(get_current_session)) -> dict:
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
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
