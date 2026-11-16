from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid
from datetime import datetime, timezone

from .database import AnonymousSession, Match, MatchRole, Base, get_session_local
from .models import (
    AnonymousSessionCreate, AnonymousSessionResponse, MatchCreate,
    MatchResponse, MatchPublicResponse, MatchRoleCreate, MatchRoleResponse,
    ScoringRightRequestCreate, ScoringRightRequestResponse, BallRecord,
    BallRecordResponse, ConfirmScoresRequest, LockMatchRequest, MvpAwardRequest,
)

app = FastAPI(title="Cric-Scorer API", version="0.0.1")

def get_db():
    db = get_session_local()
    try:
        yield db
    finally:
        db.close()

async def get_current_session(request: Request, db: Session) -> AnonymousSession:
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

@app.post("/matches", status_code=201)
def create_match(match_data: MatchCreate, db: Session = Depends(get_db), current_session: AnonymousSession = Depends(get_current_session)) -> dict:
    new_match = Match(name=f"{match_data.team_a_name} vs {match_data.team_b_name}", team_a_name=match_data.team_a_name, team_b_name=match_data.team_b_name, format=match_data.format, overs_per_innings=match_data.overs_per_innings, balls_per_over=match_data.balls_per_over, status="created", initiator_session_id=current_session.session_id, checksum=None)
    db.add(new_match)
    db.commit()
    db.refresh(new_match)
    role = MatchRole(match_id=new_match.id, session_id=current_session.session_id, role="initiator", scoring_rights=True, approved_by_session_id=None, approved_at=None)
    db.add(role)
@app.get("/matches/{match_id}/public")
def match_public(match_id: int, db: Session = Depends(get_db)) -> dict:
    stmt = select(Match).where(Match.id == match_id)
    result = db.execute(stmt)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return MatchPublicResponse(match_id=match.id, team_a_name=match.team_a_name, team_b_name=match.team_b_name, format=match.format, overs_per_innings=match.overs_per_innings, current_score="0/0", current_overs=0.0, wickets=0, status=match.status, last_updated=match.updated_at)

@app.post("/matches/{match_id}/request-scoring", status_code=201)
def request_scoring(match_id: int, request_data: ScoringRightRequestCreate, db: Session = Depends(get_db), current_session: AnonymousSession = Depends(get_current_session)) -> dict:
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

@app.get("/matches/{match_id}/scoring-requests")
def list_scoring_requests(match_id: int, db: Session = Depends(get_db), current_session: AnonymousSession = Depends(get_current_session)) -> dict:
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
        requests.append(ScoringRightRequestResponse(id=role.id, match_id=role.match_id, requestor_session_id=role.session_id, device_name=None, status="pending" if not role.approved_at else "approved", requested_at=role.created_at, approved_at=role.approved_at))
    return requests
@app.post("/matches/{match_id}/scoring-requests/{request_id}/approve")
def approve_scoring_request(match_id: int, request_id: int, db: Session = Depends(get_db), current_session: AnonymousSession = Depends(get_current_session)) -> dict:
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

@app.post("/matches/{match_id}/scoring-requests/{request_id}/reject")
def reject_scoring_request(match_id: int, request_id: int, db: Session = Depends(get_db), current_session: AnonymousSession = Depends(get_current_session)) -> dict:
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
    db.delete(role)
    db.commit()
    return {"message": "Scoring request rejected and removed", "request_id": request_id}

@app.post("/matches/{match_id}/scoring-rights/revoke")
def revoke_scoring_rights(match_id: int, db: Session = Depends(get_db), current_session: AnonymousSession = Depends(get_current_session)) -> dict:
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
@app.post("/matches/{match_id}/transfer-ownership")
def transfer_ownership(match_id: int, new_initiator_session_id: str, db: Session = Depends(get_db), current_session: AnonymousSession = Depends(get_current_session)) -> dict:
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

@app.post("/matches/{match_id}/balls")
def record_ball(match_id: int, ball_data: BallRecord, db: Session = Depends(get_db), current_session: AnonymousSession = Depends(get_current_session)) -> dict:
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
        raise HTTPException(status_code=403, detail="Scoring rights required to record deliveries. Request approval from the initiator.")
    total_runs = ball_data.runs_batter + ball_data.runs_extras
    wickets = 1 if ball_data.is_wicket else 0
    overs = ball_data.over_number + (ball_data.ball_number / 6.0)
    return BallRecordResponse(ball_id=0, over_number=ball_data.over_number, ball_number=ball_data.ball_number, runs_total=total_runs, runs_batter=ball_data.runs_batter, runs_extras=ball_data.runs_extras, wickets=wickets, total_overs=overs, status="recorded")

@app.post("/matches/{match_id}/undo")
def undo_last_ball(match_id: int, db: Session = Depends(get_db), current_session: AnonymousSession = Depends(get_current_session)) -> dict:
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
    db.commit()
    return MatchResponse(id=new_match.id, name=new_match.name, team_a_name=new_match.team_a_name, team_b_name=new_match.team_b_name, format=new_match.format, overs_per_innings=new_match.overs_per_innings, balls_per_over=new_match.balls_per_over, status=new_match.status, initiator_session_id=new_match.initiator_session_id, checksum=new_match.checksum, created_at=new_match.created_at, updated_at=new_match.updated_at, locked_at=str(new_match.locked_at) if new_match.locked_at else None)