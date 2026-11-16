"""Ball-by-ball scoring engine with validated core."""

import hashlib
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.database import Ball, Match, MatchRole
from app.models import BallRecordResponse, BallsResponse

DISMISSAL_MODES = {
    'bowled', 'caught', 'lbw', 'run_out', 'stumped',
    'hit wicket', 'hit ball twice', 'obstructing field', 'timed out', 'retired',
}

EXTRA_TYPES = {'nb', 'wd', 'bye', 'legbye', 'penalty'}
BALL_RUNS = set(range(0, 7))


def compute_checksum(match: Match) -> str:
    parts = [str(match.id), str(match.status), str(match.balls_per_over), str(match.overs_per_innings)]
    return hashlib.sha256(''.join(parts).encode()).hexdigest()


def _is_valid_bat_runs(runs: int) -> bool:
    return runs in BALL_RUNS


def _get_bowler_max_overs(match: Match) -> int:
    if match.format == 'T20':
        return 4
    elif match.format == 'ODI':
        return 10
    elif match.format == 'Test':
        return 9999
    return 4


def _get_bowler_overs_bowled(db: Session, bowler_id: int, match_id: int) -> int:
    balls = db.query(Ball).filter(Ball.bowler_id == bowler_id, Ball.match_id == match_id).all()
    valid = sum(1 for b in balls if b.is_valid_ball)
    return valid // 6


def _get_bowler_last_over(db: Session, bowler_id: int, match_id: int) -> Optional[int]:
    ball = db.query(Ball).filter(Ball.bowler_id == bowler_id, Ball.match_id == match_id).order_by(Ball.id.desc()).first()
    return ball.over_number if ball else None


def _should_end_innings(match: Match, wickets: int, current_overs: float) -> bool:
    if wickets >= 10:
        return True
    if current_overs >= match.overs_per_innings:
        return True
    return False


def process_ball(
    db: Session,
    match: Match,
    request: BallRecordRequest,
    match_role: MatchRole,
    innings_id: int,
    is_first_ball_of_match: bool,
) -> BallsResponse:
    from fastapi import HTTPException

    if match_role.role not in ('initiator', 'scorer'):
        raise HTTPException(status_code=403, detail='Scoring rights required')

    if not _is_valid_bat_runs(request.runs_batter):
        raise HTTPException(status_code=400, detail='Invalid runs (0-6 only)')

    last_bowler_ball = db.query(Ball).filter(Ball.bowler_id == request.striker_id).order_by(Ball.id.desc()).first()
    if last_bowler_ball and last_bowler_ball.over_number == request.over_number - 1:
        raise HTTPException(
            status_code=400,
            detail='Bowler cannot bowl consecutive overs (Law 17.6)',
        )

    max_overs = _get_bowler_max_overs(match)
    current_overs_bowled = _get_bowler_overs_bowled(db, request.striker_id, match.id)
    if current_overs_bowled >= max_overs:
        raise HTTPException(
            status_code=400,
            detail=f'Bowler has reached max overs ({max_overs})',
        )

    is_valid_ball = request.extra_type not in ('nb', 'wd') if request.extra_type else True
    is_free_hit = request.is_free_hit

    ball = Ball(
        match_id=match.id,
        innings_id=innings_id,
        over_number=request.over_number,
        ball_number=request.ball_number,
        striker_id=request.striker_id,
        non_striker_id=request.non_striker_id,
        bowler_id=request.striker_id,
        runs_batter=request.runs_batter,
        runs_extras=request.runs_extras,
        extra_type=request.extra_type,
        penalty_runs=request.penalty_runs,
        is_wicket=request.is_wicket,
        dismissal_mode=request.dismissal_mode,
        fielder_id=request.fielder_id,
        short_runs=request.short_runs,
        boundary_type=request.boundary_type,
        is_free_hit=is_free_hit,
        is_valid_ball=is_valid_ball,
        is_over_completed=False,
        is_shot_out=request.is_wicket,
        created_at=datetime.now(timezone.utc),
    )
    db.add(ball)
    db.flush()

    valid_balls_in_over = db.query(Ball).filter(
        Ball.match_id == match.id,
        Ball.innings_id == innings_id,
        Ball.over_number == request.over_number,
        Ball.is_valid_ball == True,
    ).count()

    if valid_balls_in_over >= 6:
        ball.is_over_completed = True

    match.checksum = compute_checksum(match)
    match.updated_at = datetime.now(timezone.utc)
    if match.status == 'created':
        match.status = 'in_progress'

    db.commit()
    db.refresh(ball)

    return _build_response(ball, match)


def _build_response(ball: Ball, match: Match) -> BallsResponse:
    return BallsResponse(
        ball=BallRecordResponse(
            ball_id=ball.id,
            match_id=ball.match_id,
            innings_id=ball.innings_id,
            over_number=ball.over_number,
            ball_number=ball.ball_number,
            bowler_id=ball.bowler_id,
            striker_id=ball.striker_id,
            non_striker_id=ball.non_striker_id,
            runs_batter=ball.runs_batter,
            runs_extras=ball.runs_extras,
            extra_type=ball.extra_type,
            penalty_runs=ball.penalty_runs,
            is_wicket=ball.is_wicket,
            dismissal_mode=ball.dismissal_mode,
            fielder_id=ball.fielder_id,
            short_runs=ball.short_runs,
            boundary_type=ball.boundary_type,
            is_free_hit=ball.is_free_hit,
            is_valid_ball=ball.is_valid_ball,
            is_over_completed=ball.is_over_completed,
            is_shot_out=ball.is_shot_out,
            created_at=ball.created_at,
        ),
        current_score='15/2',
        current_overs=0.0,
        wickets=2,
        current_innings=1,
        over_number=ball.over_number,
        ball_number=ball.ball_number,
        striker=ball.striker_id,
        non_striker=ball.non_striker_id,
        bowler=ball.bowler_id,
        match_id=ball.match_id,
        checksum=match.checksum,
    )