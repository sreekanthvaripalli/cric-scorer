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


# ── Scorecard Helpers ────────────────────────────────────────────────────────

def _overs_notation(overs_float: float) -> str:
    whole_overs = int(overs_float)
    remaining_balls = round((overs_float - whole_overs) * 6)
    return f"{whole_overs}.{remaining_balls}"


def _player_name(db: Session, player_id: int) -> str:
    player = db.query(Player).filter(Player.id == player_id).first()
    return player.name if player else f"Player {player_id}"


def compute_batting_scorecard(db: Session, match_id: int, innings_id: int) -> list:
    balls = db.query(Ball).filter(
        Ball.match_id == match_id,
        Ball.innings_id == innings_id,
        Ball.is_valid_ball == True,
    ).order_by(Ball.id).all()

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
        entry["balls"] += 1
        if b.boundary_type == "4":
            entry["fours"] += 1
        elif b.boundary_type == "6":
            entry["sixes"] += 1
        if b.is_wicket and b.striker_id == pid:
            entry["dismissal"] = "out"
            entry["dismissal_mode"] = b.dismissal_mode
            entry["bowler_fielder_id"] = b.bowler_id if b.dismissal_mode in (
                "bowled", "caught", "lbw", "hit wicket"
            ) else b.fielder_id

    for entry in batters.values():
        if entry["balls"] > 0:
            entry["strike_rate"] = round((entry["runs"] / entry["balls"]) * 100, 2)
        else:
            entry["strike_rate"] = 0.0

    non_strikers = db.query(Ball).filter(
        Ball.match_id == match_id,
        Ball.innings_id == innings_id,
        Ball.is_valid_ball == True,
    ).all()
    seen_ids = set(batters.keys())
    for b in non_strikers:
        if b.non_striker_id not in seen_ids:
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
            seen_ids.add(b.non_striker_id)

    return list(batters.values())


def compute_bowling_analysis(db: Session, match_id: int, innings_id: int) -> list:
    balls = db.query(Ball).filter(
        Ball.match_id == match_id,
        Ball.innings_id == innings_id,
    ).order_by(Ball.id).all()

    bowlers = {}
    for b in balls:
        pid = b.bowler_id
        if pid not in bowlers:
            bowlers[pid] = {
                "player_id": pid,
                "name": _player_name(db, pid),
                "overs_count": 0.0,
                "maidens": 0,
                "runs": 0,
                "wickets": 0,
                "wides": 0,
                "no_balls": 0,
            }
        entry = bowlers[pid]
        entry["overs_count"] += b.ball_number / 6.0
        entry["runs"] += b.runs_batter + b.runs_extras
        if b.is_wicket:
            entry["wickets"] += 1
        if b.extra_type == "wd":
            entry["wides"] += 1
        elif b.extra_type == "nb":
            entry["no_balls"] += 1

    result = []
    for entry in bowlers.values():
        over_notation = _overs_notation(entry["overs_count"])
        econ = round(entry["runs"] / entry["overs_count"], 2) if entry["overs_count"] > 0 else 0.0
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
    balls = db.query(Ball).filter(
        Ball.match_id == match_id,
        Ball.innings_id == innings_id,
    ).all()

    no_balls = sum(1 for b in balls if b.extra_type == "nb")
    wides = sum(1 for b in balls if b.extra_type == "wd")
    byes = sum(1 for b in balls if b.extra_type == "bye")
    leg_byes = sum(1 for b in balls if b.extra_type == "legbye")
    penalties = sum(b.penalty_runs for b in balls)
    total_extras = sum(b.runs_extras for b in balls) + penalties

    return {
        "no_balls": no_balls,
        "wides": wides,
        "byes": byes,
        "leg_byes": leg_byes,
        "penalties": penalties,
        "total_extras": total_extras,
    }


def compute_fall_of_wickets(db: Session, match_id: int, innings_id: int) -> list:
    balls = db.query(Ball).filter(
        Ball.match_id == match_id,
        Ball.innings_id == innings_id,
        Ball.is_wicket == True,
    ).order_by(Ball.id).all()

    fow = []
    prev_total = 0

    for idx, b in enumerate(balls, 1):
        all_balls_up_to = db.query(Ball).filter(
            Ball.match_id == match_id,
            Ball.innings_id == innings_id,
            Ball.id <= b.id,
        ).all()
        total_runs = sum(bb.runs_batter + bb.runs_extras for bb in all_balls_up_to)

        partnership = total_runs - prev_total
        over_notation = f"{b.over_number}.{b.ball_number}"

        fow.append({
            "wicket": idx,
            "batter_out": _player_name(db, b.striker_id),
            "batter_out_id": b.striker_id,
            "not_out_batter": _player_name(db, b.non_striker_id),
            "not_out_batter_id": b.non_striker_id,
            "runs_at_fall": total_runs,
            "over": over_notation,
            "partnership": partnership,
        })
        prev_total = total_runs

    return fow


def compute_full_scorecard(db: Session, match_id: int, innings_id: int) -> dict:
    return {
        "innings_id": innings_id,
        "batting": compute_batting_scorecard(db, match_id, innings_id),
        "bowling": compute_bowling_analysis(db, match_id, innings_id),
        "extras": compute_extras_summary(db, match_id, innings_id),
        "fall_of_wickets": compute_fall_of_wickets(db, match_id, innings_id),
    }


# ── Match Result Computation (Law 16) ───────────────────────────────────────

def compute_match_result(db: Session, match_id: int) -> dict:
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        return {"result_type": "no_match", "margin_text": "Match not found"}

    innings_1 = db.query(Ball).filter(
        Ball.match_id == match_id, Ball.innings_id == 1
    ).all()
    innings_2 = db.query(Ball).filter(
        Ball.match_id == match_id, Ball.innings_id == 2
    ).all()

    team1_runs = sum(b.runs_batter + b.runs_extras for b in innings_1)
    team1_wickets = sum(1 for b in innings_1 if b.is_wicket)
    team1_overs = round(
        sum(b.over_number + b.ball_number / 6.0 for b in innings_1 if b.is_valid_ball) / max(1, len([b for b in innings_1 if b.is_valid_ball])),
        2,
    ) if innings_1 else 0.0

    team2_runs = sum(b.runs_batter + b.runs_extras for b in innings_2)
    team2_wickets = sum(1 for b in innings_2 if b.is_wicket)
    team2_overs = round(
        sum(b.over_number + b.ball_number / 6.0 for b in innings_2 if b.is_valid_ball) / max(1, len([b for b in innings_2 if b.is_valid_ball])),
        2,
    ) if innings_2 else 0.0

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

    if not innings_2 or len(innings_2) == 0:
        return {
            "result_type": "no_result",
            "winner_team_id": None,
            "margin_runs": 0,
            "margin_wickets": 0,
            "margin_text": "Match not completed",
            "details": {
                "team_a_runs": team1_runs,
                "team_a_wickets": team1_wickets,
                "team_a_overs": team1_overs,
                "team_b_runs": team2_runs,
                "team_b_wickets": team2_wickets,
                "team_b_overs": team2_overs,
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

    team_batting_first_id = team_a_id
    team_batting_second_id = team_b_id

    if team2_runs > team1_runs:
        wickets_remaining = 10 - team2_wickets
        return {
            "result_type": "win_by_wickets",
            "winner_team_id": team_batting_second_id,
            "margin_runs": 0,
            "margin_wickets": wickets_remaining,
            "margin_text": f"Won by {wickets_remaining} wickets",
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
            "winner_team_id": team_batting_first_id,
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
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        return {"follow_on_possible": False, "message": "Match not found"}

    if match.format != "Test":
        return {"follow_on_possible": False, "message": "Follow-on only applies to Test matches"}

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
            "threshold": match.follow_on_threshold or 200,
        }

    team1_runs = sum(b.runs_batter + b.runs_extras for b in innings_1)
    team2_runs = sum(b.runs_batter + b.runs_extras for b in innings_2)

    threshold = match.follow_on_threshold or 200
    should_offer = team1_runs - team2_runs >= threshold

    return {
        "follow_on_possible": True,
        "threshold": threshold,
        "team_a_runs": team1_runs,
        "team_b_runs": team2_runs,
        "lead": team1_runs - team2_runs,
        "should_offer": should_offer,
        "message": (
            f"Follow-on can be offered (lead {team1_runs - team2_runs} >= {threshold})"
            if should_offer
            else f"Follow-on not available (lead {team1_runs - team2_runs} < {threshold})"
        ),
    }


def compute_super_over(db: Session, match_id: int) -> dict:
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

    team_a_so = sum(b.runs_batter + b.runs_extras for b in super_over_1)
    team_b_so = sum(b.runs_batter + b.runs_extras for b in super_over_2)

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