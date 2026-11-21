"""Ball-by-ball scoring engine with validated core and Laws of Cricket adherence."""

import hashlib
import threading
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.database import Ball, Match, MatchRole, Player, MatchTeamLink, FormatConfig, Wicket, Innings, Over
from app.models import BallRecordRequest, BallRecordResponse, BallsResponse

_scoring_lock = threading.Lock()

DISMISSAL_MODES = {
    'bowled', 'caught', 'lbw', 'run_out', 'stumped',
    'hit_wicket', 'hit wicket', 'hit_ball_twice', 'hit ball twice',
    'obstructing_field', 'obstructing field', 'timed_out', 'timed out', 'retired',
}

DISMISSAL_MODES_NORM = {
    'bowled', 'caught', 'lbw', 'run_out', 'stumped',
    'hit_wicket', 'hit_ball_twice', 'obstructing_field', 'timed_out', 'retired',
}

LEGAL_DISMISSALS_NO_BALL = {'run_out', 'obstructing_field', 'hit_ball_twice'}
ILLEGAL_DISMISSALS_WIDE = {'bowled', 'caught', 'lbw', 'hit_ball_twice'}
BOWLER_CREDITED_DISMISSALS = {'bowled', 'caught', 'lbw', 'stumped', 'hit_wicket'}

EXTRA_TYPES = {'nb', 'wd', 'bye', 'legbye', 'penalty'}
BALL_RUNS = set(range(0, 7))

RESULT_TYPES = {'win_by_runs', 'win_by_wickets', 'tie', 'no_result', 'draw', 'conceded', 'awarded'}


def compute_checksum(match: Match, db: Optional[Session] = None) -> str:
    """Compute cryptographic hash of match state and delivery history (Laws 2.15 / 3.2)."""
    parts = [
        str(match.id),
        str(match.status),
        str(match.balls_per_over),
        str(match.overs_per_innings),
    ]
    if db is not None:
        balls = (
            db.query(Ball)
            .filter(Ball.match_id == match.id)
            .order_by(Ball.id.asc())
            .all()
        )
        for b in balls:
            parts.append(
                f"|{b.innings_id}:{b.over_number}:{b.ball_number}:{b.bowler_id}:"
                f"{b.striker_id}:{b.runs_batter}:{b.runs_extras}:{b.extra_type}:"
                f"{b.is_wicket}:{b.dismissal_mode}"
            )
    return hashlib.sha256("".join(parts).encode()).hexdigest()


def _is_valid_bat_runs(runs: int) -> bool:
    return runs in BALL_RUNS


def _get_bowler_max_overs(match: Match) -> int:
    if match.format == 'T20':
        return 4
    elif match.format == 'ODI':
        return 10
    elif match.format == 'Test':
        return 9999
    # Custom format: derive from overs_per_innings (overs // 5, min 1)
    if match.overs_per_innings:
        return max(1, match.overs_per_innings // 5)
    return 4


def _get_bowler_overs_bowled(db: Session, bowler_id: int, match_id: int, innings_id: int = 1) -> int:
    balls = db.query(Ball).filter(
        Ball.bowler_id == bowler_id,
        Ball.match_id == match_id,
        Ball.innings_id == innings_id,
    ).all()
    valid = sum(1 for b in balls if b.is_valid_ball)
    return valid // 6


def _check_bowler_consecutive_overs(
    db: Session, match_id: int, innings_id: int, over_number: int, bowler_id: int
):
    """Enforce Law 17.6: Bowler cannot bowl two consecutive overs."""
    if over_number > 1:
        prev_balls = (
            db.query(Ball)
            .filter(
                Ball.match_id == match_id,
                Ball.innings_id == innings_id,
                Ball.over_number == over_number - 1,
            )
            .all()
        )
        if prev_balls and any(b.bowler_id == bowler_id for b in prev_balls):
            raise HTTPException(
                status_code=400,
                detail="Bowler cannot bowl consecutive overs (Law 17.6)",
            )


def _validate_dismissal(
    is_wicket: bool,
    dismissal_mode: Optional[str],
    extra_type: Optional[str],
    is_free_hit: bool,
    fielder_id: Optional[int],
    bowler_id: int,
) -> Tuple[Optional[str], bool, Optional[int]]:
    """Validate dismissal mode against Laws of Cricket (Laws 21.17, 22.9, 32-40)."""
    if not is_wicket:
        return None, False, fielder_id

    if not dismissal_mode:
        raise HTTPException(
            status_code=400, detail="Dismissal mode required when is_wicket is True"
        )

    norm = dismissal_mode.lower().strip().replace(" ", "_")
    if norm not in DISMISSAL_MODES_NORM:
        raise HTTPException(
            status_code=400, detail=f"Invalid dismissal mode: {dismissal_mode}"
        )

    # Law 38: Run out requires a fielder
    if norm == "run_out" and fielder_id is None:
        raise HTTPException(
            status_code=400, detail="Fielder is required for run out"
        )

    # Law 21.17: Out from a No ball
    if extra_type == "nb" and norm not in LEGAL_DISMISSALS_NO_BALL:
        raise HTTPException(
            status_code=400,
            detail=f"Batter cannot be dismissed {dismissal_mode} off a No ball (Law 21.17)",
        )

    # ICC Playing Conditions: Free hit dismissals follow No ball conditions
    if is_free_hit and norm not in LEGAL_DISMISSALS_NO_BALL:
        raise HTTPException(
            status_code=400,
            detail=f"Batter cannot be dismissed {dismissal_mode} on a free hit (ICC Playing Conditions 21.19)",
        )

    # Law 22.9: Out from a Wide
    if extra_type == "wd" and norm in ILLEGAL_DISMISSALS_WIDE:
        raise HTTPException(
            status_code=400,
            detail=f"Batter cannot be dismissed {dismissal_mode} off a Wide (Law 22.9)",
        )

    # Convention: is_shot_out is True for bowled & caught
    is_shot_out = norm in ("bowled", "caught")

    # Caught and bowled defaults fielder to bowler
    if norm == "caught" and fielder_id is None:
        fielder_id = bowler_id

    return norm, is_shot_out, fielder_id


def process_ball(
    db: Session,
    match: Match,
    request: BallRecordRequest,
    match_role: MatchRole,
    innings_id: int = 1,
    is_first_ball_of_match: bool = False,
) -> BallsResponse:
    """Process and record one ball atomically with full Laws of Cricket validation."""
    with _scoring_lock:
        if match_role.role not in ('initiator', 'scorer') or not match_role.scoring_rights:
            raise HTTPException(status_code=403, detail='Scoring rights required')

        # Section 7, Step 1: Validate match state (in progress; not locked)
        if match.status == 'locked':
            raise HTTPException(status_code=400, detail='Match is locked; no further deliveries allowed')

        # Law 16.6 / Section 7, Step 9: prevent balls after match completed
        if match.status == 'completed':
            raise HTTPException(status_code=400, detail='Match already completed; no further deliveries allowed')

        # Section 7, Step 2: Validate striker (not out, at crease)
        dismissed_strikers = _get_dismissed_batters(db, match.id, innings_id)
        if request.striker_id in dismissed_strikers:
            raise HTTPException(
                status_code=400,
                detail=f'Striker {request.striker_id} is already out and cannot face deliveries',
            )
        if request.non_striker_id in dismissed_strikers:
            raise HTTPException(
                status_code=400,
                detail=f'Non-striker {request.non_striker_id} is already out and cannot be at crease',
            )

        if not _is_valid_bat_runs(request.runs_batter):
            raise HTTPException(status_code=400, detail='Invalid runs (0-6 only)')

        # Check consecutive overs for the BOWLER (Law 17.6)
        _check_bowler_consecutive_overs(
            db, match.id, innings_id, request.over_number, request.bowler_id
        )

        # Check max overs for bowler
        max_overs = _get_bowler_max_overs(match)
        current_overs_bowled = _get_bowler_overs_bowled(
            db, request.bowler_id, match.id, innings_id
        )
        if current_overs_bowled >= max_overs:
            raise HTTPException(
                status_code=400,
                detail=f'Bowler has reached max overs ({max_overs})',
            )

        # Normalize extra type
        extra_type = request.extra_type.lower().strip() if request.extra_type else None
        if extra_type and extra_type not in EXTRA_TYPES:
            raise HTTPException(status_code=400, detail=f'Invalid extra type: {request.extra_type}')

        # Validate dismissal legality (Laws 21.17, 22.9, 32-40)
        dismissal_norm, is_shot_out, fielder_id = _validate_dismissal(
            is_wicket=request.is_wicket,
            dismissal_mode=request.dismissal_mode,
            extra_type=extra_type,
            is_free_hit=request.is_free_hit,
            fielder_id=request.fielder_id,
            bowler_id=request.bowler_id,
        )

        # Greater-of rule for boundaries (Law 19.7)
        boundary_type = str(request.boundary_type).strip() if request.boundary_type else None
        runs_batter = request.runs_batter
        if boundary_type == '4':
            runs_batter = max(runs_batter, 4)
        elif boundary_type == '6':
            runs_batter = max(runs_batter, 6)

        # Extras calculation
        runs_extras = request.runs_extras
        if extra_type in ('nb', 'wd') and runs_extras == 0:
            runs_extras = 1

        # Valid ball: No ball & Wide do not count toward the over (Law 17.3)
        is_valid_ball = extra_type not in ('nb', 'wd')

        # Section 7, Step 5 / FR-4.10: Short-run deliberate penalty (5 runs to fielding side)
        deliberate_short_run = getattr(request, 'deliberate_short_run', False)
        penalty_runs = request.penalty_runs
        if request.short_runs > 0 and deliberate_short_run:
            penalty_runs += 5  # 5-run penalty to fielding side for deliberate short runs

        ball = Ball(
            match_id=match.id,
            innings_id=innings_id,
            over_number=request.over_number,
            ball_number=request.ball_number,
            striker_id=request.striker_id,
            non_striker_id=request.non_striker_id,
            bowler_id=request.bowler_id,
            runs_batter=runs_batter,
            runs_extras=runs_extras,
            extra_type=extra_type,
            penalty_runs=penalty_runs,
            is_wicket=request.is_wicket,
            dismissal_mode=dismissal_norm,
            fielder_id=fielder_id,
            short_runs=request.short_runs,
            boundary_type=boundary_type,
            is_free_hit=request.is_free_hit,
            is_valid_ball=is_valid_ball,
            is_over_completed=False,
            is_shot_out=is_shot_out,
            created_at=datetime.now(timezone.utc),
        )
        db.add(ball)
        db.flush()

        # Section 6: Populate Wicket table when a wicket falls
        if request.is_wicket and dismissal_norm:
            runs_at_fall = sum(
                b.runs_batter + b.runs_extras + b.penalty_runs
                for b in db.query(Ball).filter(Ball.match_id == match.id, Ball.innings_id == innings_id).all()
            ) + runs_batter + runs_extras + penalty_runs
            wicket_row = Wicket(
                ball_id=ball.id,
                dismissal_mode=dismissal_norm,
                batter_out_id=request.striker_id,
                fielder_id=fielder_id,
                bowler_credit_id=request.bowler_id if dismissal_norm in BOWLER_CREDITED_DISMISSALS else None,
                not_out_batter_id=request.non_striker_id,
                runs_at_fall=runs_at_fall,
                over_at_fall=f"{request.over_number}.{request.ball_number}",
                created_at=datetime.now(timezone.utc),
            )
            db.add(wicket_row)

        # Over completion check
        balls_per_over = match.balls_per_over or 6
        valid_balls_in_over = db.query(Ball).filter(
            Ball.match_id == match.id,
            Ball.innings_id == innings_id,
            Ball.over_number == request.over_number,
            Ball.is_valid_ball == True,
        ).count()

        if valid_balls_in_over >= balls_per_over:
            ball.is_over_completed = True

            # Section 6: Populate Over table on over completion
            over_row = Over(
                innings_id=innings_id,
                over_number=request.over_number,
                bowler_id=request.bowler_id,
                balls_valid=valid_balls_in_over,
                completed_at=datetime.now(timezone.utc),
            )
            db.add(over_row)

        # Section 6: Ensure Innings row exists
        innings_row = db.query(Innings).filter(
            Innings.match_id == match.id,
            Innings.innings_number == innings_id,
        ).first()
        if not innings_row:
            innings_row = Innings(
                match_id=match.id,
                innings_number=innings_id,
                status='in_progress',
                total_runs=0,
                total_wickets=0,
                overs_bowled='0.0',
                created_at=datetime.now(timezone.utc),
            )
            db.add(innings_row)
            db.flush()

        # Recompute match checksum with all deliveries
        match.checksum = compute_checksum(match, db)
        match.updated_at = datetime.now(timezone.utc)
        if match.status == 'created':
            match.status = 'in_progress'

        db.commit()
        db.refresh(ball)
        db.refresh(match)

        return _build_response(ball, match, db)


def _build_response(ball: Ball, match: Match, db: Session) -> BallsResponse:
    """Dynamically compute match totals and return BallsResponse."""
    innings_balls = (
        db.query(Ball)
        .filter(Ball.match_id == match.id, Ball.innings_id == ball.innings_id)
        .all()
    )
    total_runs = sum(b.runs_batter + b.runs_extras + b.penalty_runs for b in innings_balls)
    wickets = sum(1 for b in innings_balls if b.is_wicket)
    valid_balls = sum(1 for b in innings_balls if b.is_valid_ball)
    balls_per_over = match.balls_per_over or 6
    completed_overs = valid_balls // balls_per_over
    balls_in_cur_over = valid_balls % balls_per_over
    current_overs = float(f"{completed_overs}.{balls_in_cur_over}")
    current_score = f"{total_runs}/{wickets}"

    # Strike rotation calculation (Law 18.11 / 18.12)
    running_runs = ball.runs_batter + (ball.runs_extras if ball.extra_type in ('bye', 'legbye') else 0)
    swap_strike = (running_runs % 2 == 1)
    next_striker = ball.non_striker_id if swap_strike else ball.striker_id
    next_non_striker = ball.striker_id if swap_strike else ball.non_striker_id

    if ball.is_over_completed:
        # Ends swap at end of over
        next_striker, next_non_striker = next_non_striker, next_striker

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
        current_score=current_score,
        current_overs=current_overs,
        wickets=wickets,
        current_innings=ball.innings_id,
        over_number=ball.over_number,
        ball_number=ball.ball_number,
        striker=next_striker,
        non_striker=next_non_striker,
        bowler=ball.bowler_id,
        match_id=ball.match_id,
        checksum=match.checksum,
    )


# ── Scorecard Helpers ────────────────────────────────────────────────────────

def _get_dismissed_batters(db: Session, match_id: int, innings_id: int) -> set:
    """Return set of batter IDs dismissed in the given innings (FR-4.13 striker validation)."""
    balls = (
        db.query(Ball)
        .filter(Ball.match_id == match_id, Ball.innings_id == innings_id, Ball.is_wicket == True)
        .all()
    )
    return {b.striker_id for b in balls}


def _player_name(db: Session, player_id: int) -> str:
    player = db.query(Player).filter(Player.id == player_id).first()
    return player.name if player else f"Player {player_id}"


def compute_batting_scorecard(db: Session, match_id: int, innings_id: int) -> list:
    """Compute batting scorecard for an innings."""
    balls = (
        db.query(Ball)
        .filter(Ball.match_id == match_id, Ball.innings_id == innings_id)
        .order_by(Ball.id.asc())
        .all()
    )

    batters = {}
    for b in balls:
        pid = b.striker_id
        if pid not in batters:
            batters[pid] = {
                "player_id": pid,
                "name": _player_name(db, pid),
                "runs": 0,
                "balls": 0,
                "fours": 0,
                "sixes": 0,
                "dismissal": None,
                "dismissal_mode": None,
                "bowler_fielder_id": None,
            }
        entry = batters[pid]
        entry["runs"] += b.runs_batter
        # Balls faced: count valid balls + no balls (Law 18.10)
        if b.is_valid_ball or b.extra_type == 'nb':
            entry["balls"] += 1
        if b.boundary_type == "4":
            entry["fours"] += 1
        elif b.boundary_type == "6":
            entry["sixes"] += 1
        if b.is_wicket and b.striker_id == pid:
            entry["dismissal"] = "out"
            entry["dismissal_mode"] = b.dismissal_mode
            entry["bowler_fielder_id"] = b.bowler_id if b.dismissal_mode in BOWLER_CREDITED_DISMISSALS else b.fielder_id

    # Add non-strikers who may not have faced a ball
    for b in balls:
        if b.non_striker_id not in batters:
            batters[b.non_striker_id] = {
                "player_id": b.non_striker_id,
                "name": _player_name(db, b.non_striker_id),
                "runs": 0,
                "balls": 0,
                "fours": 0,
                "sixes": 0,
                "strike_rate": 0.0,
                "dismissal": None,
                "dismissal_mode": None,
                "bowler_fielder_id": None,
            }

    for entry in batters.values():
        if entry["balls"] > 0:
            entry["strike_rate"] = round((entry["runs"] / entry["balls"]) * 100, 2)
        else:
            entry["strike_rate"] = 0.0

    return list(batters.values())


def compute_bowling_analysis(db: Session, match_id: int, innings_id: int) -> list:
    """Compute accurate bowling figures per Laws of Cricket (Laws 17, 23, 38)."""
    balls = (
        db.query(Ball)
        .filter(Ball.match_id == match_id, Ball.innings_id == innings_id)
        .order_by(Ball.id.asc())
        .all()
    )

    bowlers = {}
    over_deliveries = {}  # (bowler_id, over_number) -> list of balls for maiden calculation

    for b in balls:
        pid = b.bowler_id
        if pid not in bowlers:
            bowlers[pid] = {
                "player_id": pid,
                "name": _player_name(db, pid),
                "valid_balls": 0,
                "maidens": 0,
                "runs": 0,
                "wickets": 0,
                "wides": 0,
                "no_balls": 0,
            }
        entry = bowlers[pid]

        if b.is_valid_ball:
            entry["valid_balls"] += 1

        # Bowler runs: bat runs + wides + no-balls (Law 23: Byes/Leg byes not debited to bowler)
        bowler_extra = b.runs_extras if b.extra_type in ('nb', 'wd') else 0
        entry["runs"] += b.runs_batter + bowler_extra

        # Bowler wickets: only bowled, caught, lbw, stumped, hit wicket (Law 38: Run outs not credited)
        if b.is_wicket and b.dismissal_mode in BOWLER_CREDITED_DISMISSALS:
            entry["wickets"] += 1

        if b.extra_type == "wd":
            entry["wides"] += 1
        elif b.extra_type == "nb":
            entry["no_balls"] += 1

        key = (pid, b.over_number)
        if key not in over_deliveries:
            over_deliveries[key] = []
        over_deliveries[key].append(b)

    # Compute maidens: completed overs (6 valid balls) with 0 runs debited to bowler
    for (pid, _), o_balls in over_deliveries.items():
        v_count = sum(1 for b in o_balls if b.is_valid_ball)
        if v_count >= 6:
            runs_in_over = sum(
                b.runs_batter + (b.runs_extras if b.extra_type in ('nb', 'wd') else 0)
                for b in o_balls
            )
            if runs_in_over == 0:
                bowlers[pid]["maidens"] += 1

    result = []
    for entry in bowlers.values():
        v = entry["valid_balls"]
        overs_comp = v // 6
        balls_rem = v % 6
        over_notation = f"{overs_comp}.{balls_rem}"
        overs_float = overs_comp + (balls_rem / 6.0)
        econ = round(entry["runs"] / overs_float, 2) if overs_float > 0 else 0.0

        result.append({
            "player_id": entry["player_id"],
            "name": entry["name"],
            "overs": over_notation,
            "maidens": entry["maidens"],
            "runs": entry["runs"],
            "wickets": entry["wickets"],
            "wides": entry["wides"],
            "no_balls": entry["no_balls"],
            "economy": econ,
        })
    return result


def compute_extras_summary(db: Session, match_id: int, innings_id: int) -> dict:
    """Compute summary of extras for an innings."""
    balls = db.query(Ball).filter(
        Ball.match_id == match_id,
        Ball.innings_id == innings_id,
    ).all()

    no_balls = sum(b.runs_extras for b in balls if b.extra_type == "nb")
    wides = sum(b.runs_extras for b in balls if b.extra_type == "wd")
    byes = sum(b.runs_extras for b in balls if b.extra_type == "bye")
    leg_byes = sum(b.runs_extras for b in balls if b.extra_type == "legbye")
    penalties = sum(b.penalty_runs for b in balls)
    total_extras = no_balls + wides + byes + leg_byes + penalties

    return {
        "no_balls": no_balls,
        "wides": wides,
        "byes": byes,
        "leg_byes": leg_byes,
        "penalties": penalties,
        "total_extras": total_extras,
    }


def compute_fall_of_wickets(db: Session, match_id: int, innings_id: int) -> list:
    """Compute fall of wickets table."""
    all_balls = (
        db.query(Ball)
        .filter(Ball.match_id == match_id, Ball.innings_id == innings_id)
        .order_by(Ball.id.asc())
        .all()
    )

    fow = []
    running_runs = 0
    valid_balls_count = 0
    prev_total = 0
    wicket_count = 0

    for b in all_balls:
        running_runs += b.runs_batter + b.runs_extras + b.penalty_runs
        if b.is_valid_ball:
            valid_balls_count += 1

        if b.is_wicket:
            wicket_count += 1
            completed_overs = valid_balls_count // 6
            balls_in_over = valid_balls_count % 6
            over_notation = f"{completed_overs}.{balls_in_over}"
            partnership = running_runs - prev_total

            fow.append({
                "wicket": wicket_count,
                "batter_out": _player_name(db, b.striker_id),
                "batter_out_id": b.striker_id,
                "not_out_batter": _player_name(db, b.non_striker_id),
                "not_out_batter_id": b.non_striker_id,
                "runs_at_fall": running_runs,
                "over": over_notation,
                "partnership": partnership,
            })
            prev_total = running_runs

    return fow


def compute_full_scorecard(db: Session, match_id: int, innings_id: int = 1) -> dict:
    """Return full scorecard dictionary for an innings."""
    return {
        "innings_id": innings_id,
        "batting": compute_batting_scorecard(db, match_id, innings_id),
        "bowling": compute_bowling_analysis(db, match_id, innings_id),
        "extras": compute_extras_summary(db, match_id, innings_id),
        "fall_of_wickets": compute_fall_of_wickets(db, match_id, innings_id),
    }


# ── Match Result Computation (Law 16) ───────────────────────────────────────

def compute_match_result(db: Session, match_id: int) -> dict:
    """Compute legally correct match result according to Law 16."""
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        return {"result_type": "no_match", "margin_text": "Match not found"}

    # If match has a manually-set result (draw, conceded, awarded), return it
    if getattr(match, 'result_type', None) and match.result_type in RESULT_TYPES:
        return {
            "result_type": match.result_type,
            "winner_team_id": getattr(match, 'winner_team_id', None),
            "margin_runs": getattr(match, 'margin_runs', 0) or 0,
            "margin_wickets": getattr(match, 'margin_wickets', 0) or 0,
            "margin_text": getattr(match, 'margin_text', '') or '',
            "details": {
                "team_a_runs": getattr(match, 'team_a_runs', 0) or 0,
                "team_a_wickets": getattr(match, 'team_a_wickets', 0) or 0,
                "team_a_overs": getattr(match, 'team_a_overs', 0.0) or 0.0,
                "team_b_runs": getattr(match, 'team_b_runs', 0) or 0,
                "team_b_wickets": getattr(match, 'team_b_wickets', 0) or 0,
                "team_b_overs": getattr(match, 'team_b_overs', 0.0) or 0.0,
            },
        }

    innings_1 = db.query(Ball).filter(
        Ball.match_id == match_id, Ball.innings_id == 1
    ).all()
    innings_2 = db.query(Ball).filter(
        Ball.match_id == match_id, Ball.innings_id == 2
    ).all()

    team1_runs = sum(b.runs_batter + b.runs_extras + b.penalty_runs for b in innings_1)
    team1_wickets = sum(1 for b in innings_1 if b.is_wicket)
    v1 = sum(1 for b in innings_1 if b.is_valid_ball)
    team1_overs = float(f"{v1 // 6}.{v1 % 6}")

    team2_runs = sum(b.runs_batter + b.runs_extras + b.penalty_runs for b in innings_2)
    team2_wickets = sum(1 for b in innings_2 if b.is_wicket)
    v2 = sum(1 for b in innings_2 if b.is_valid_ball)
    team2_overs = float(f"{v2 // 6}.{v2 % 6}")

    team_a_link = db.query(MatchTeamLink).filter(
        MatchTeamLink.match_id == match_id,
        MatchTeamLink.team_role == "team_a",
    ).first()
    team_b_link = db.query(MatchTeamLink).filter(
        MatchTeamLink.match_id == match_id,
        MatchTeamLink.team_role == "team_b",
    ).first()

    team_a_id = team_a_link.team_id if team_a_link else 1
    team_b_id = team_b_link.team_id if team_b_link else 2

    if not innings_2:
        return {
            "result_type": "no_result",
            "winner_team_id": None,
            "margin_runs": 0,
            "margin_wickets": 0,
            "margin_text": "Match in progress" if innings_1 else "Not started",
            "details": {
                "team_a_runs": team1_runs,
                "team_a_wickets": team1_wickets,
                "team_a_overs": team1_overs,
                "team_b_runs": 0,
                "team_b_wickets": 0,
                "team_b_overs": 0.0,
            },
        }

    if team1_runs == team2_runs:
        return {
            "result_type": "tie",
            "winner_team_id": None,
            "margin_runs": 0,
            "margin_wickets": 0,
            "margin_text": "Match Tied",
            "details": {
                "team_a_runs": team1_runs,
                "team_a_wickets": team1_wickets,
                "team_a_overs": team1_overs,
                "team_b_runs": team2_runs,
                "team_b_wickets": team2_wickets,
                "team_b_overs": team2_overs,
            },
        }

    # Law 16.6 Winning-hit rule: if team batting last reaches target, match ends immediately
    # even if a wicket falls on the same ball. The win still stands.
    if team2_runs > team1_runs:
        wickets_remaining = 10 - team2_wickets
        # Check if this was a winning hit (team2 reached target on last ball)
        winning_hit = innings_2 and innings_2[-1].runs_batter + innings_2[-1].runs_extras + innings_2[-1].penalty_runs > 0
        margin_text = f"Won by {wickets_remaining} wickets"
        if winning_hit and innings_2[-1].is_wicket:
            margin_text += " (winning hit - Law 16.6)"
        return {
            "result_type": "win_by_wickets",
            "winner_team_id": team_b_id,
            "margin_runs": 0,
            "margin_wickets": wickets_remaining,
            "margin_text": margin_text,
            "details": {
                "team_a_runs": team1_runs,
                "team_a_wickets": team1_wickets,
                "team_a_overs": team1_overs,
                "team_b_runs": team2_runs,
                "team_b_wickets": team2_wickets,
                "team_b_overs": team2_overs,
            },
        }
    else:
        runs_difference = team1_runs - team2_runs
        return {
            "result_type": "win_by_runs",
            "winner_team_id": team_a_id,
            "margin_runs": runs_difference,
            "margin_wickets": 0,
            "margin_text": f"Won by {runs_difference} runs",
            "details": {
                "team_a_runs": team1_runs,
                "team_a_wickets": team1_wickets,
                "team_a_overs": team1_overs,
                "team_b_runs": team2_runs,
                "team_b_wickets": team2_wickets,
                "team_b_overs": team2_overs,
            },
        }


def compute_follow_on(db: Session, match_id: int) -> dict:
    """Compute follow-on eligibility for Test matches."""
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        return {"follow_on_possible": False, "message": "Match not found"}

    if match.format != "Test":
        return {"follow_on_possible": False, "message": "Follow-on only applies to Test matches"}

    fmt_config = db.query(FormatConfig).filter(FormatConfig.format_name == "Test").first()
    threshold = (fmt_config.follow_on_threshold if fmt_config and fmt_config.follow_on_threshold else 200)

    innings_1 = db.query(Ball).filter(
        Ball.match_id == match_id, Ball.innings_id == 1
    ).all()
    innings_2 = db.query(Ball).filter(
        Ball.match_id == match_id, Ball.innings_id == 2
    ).all()

    if not innings_2:
        return {
            "follow_on_possible": False,
            "message": "Second innings not started",
            "threshold": threshold,
        }

    team1_runs = sum(b.runs_batter + b.runs_extras + b.penalty_runs for b in innings_1)
    team2_runs = sum(b.runs_batter + b.runs_extras + b.penalty_runs for b in innings_2)

    lead = team1_runs - team2_runs
    should_offer = lead >= threshold

    return {
        "follow_on_possible": True,
        "threshold": threshold,
        "team_a_runs": team1_runs,
        "team_b_runs": team2_runs,
        "lead": lead,
        "should_offer": should_offer,
        "message": (
            f"Follow-on can be offered (lead {lead} >= {threshold})"
            if should_offer
            else f"Follow-on not available (lead {lead} < {threshold})"
        ),
    }


def compute_super_over(db: Session, match_id: int) -> dict:
    """Compute Super Over scores for T20 ties."""
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        return {"available": False, "message": "Match not found"}

    if match.format != "T20":
        return {"available": False, "message": "Super Over only applies to T20 matches"}

    super_over_1 = db.query(Ball).filter(
        Ball.match_id == match_id, Ball.innings_id == 3
    ).all()
    super_over_2 = db.query(Ball).filter(
        Ball.match_id == match_id, Ball.innings_id == 4
    ).all()

    if not super_over_1 and not super_over_2:
        return {
            "available": True,
            "message": "Super Over not yet played",
            "team_a_score": None,
            "team_b_score": None,
            "winner_team_id": None,
        }

    team_a_so = sum(b.runs_batter + b.runs_extras + b.penalty_runs for b in super_over_1)
    team_b_so = sum(b.runs_batter + b.runs_extras + b.penalty_runs for b in super_over_2)

    team_a_link = db.query(MatchTeamLink).filter(
        MatchTeamLink.match_id == match_id,
        MatchTeamLink.team_role == "team_a",
    ).first()
    team_b_link = db.query(MatchTeamLink).filter(
        MatchTeamLink.match_id == match_id,
        MatchTeamLink.team_role == "team_b",
    ).first()

    team_a_id = team_a_link.team_id if team_a_link else 1
    team_b_id = team_b_link.team_id if team_b_link else 2

    if team_a_so > team_b_so:
        winner = team_a_id
    elif team_b_so > team_a_so:
        winner = team_b_id
    else:
        winner = None

    return {
        "available": True,
        "message": f"Super Over: Team A {team_a_so} vs Team B {team_b_so}",
        "team_a_score": team_a_so,
        "team_b_score": team_b_so,
        "winner_team_id": winner,
    }
