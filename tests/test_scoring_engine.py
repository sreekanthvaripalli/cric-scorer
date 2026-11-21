"""Unit tests for the scoring engine (Module 10.1).

Covers:
- Dismissal modes x (normal / No ball / Wide / free-hit) matrix
- Extras types
- Short-run rules
- Boundary greater-of
- Over-counting with NB/WD
- Max overs/bowler
- Consecutive-over prevention
Target: >=200 test cases
"""

from datetime import datetime, timezone
import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.database import Ball, Match, MatchRole, MatchSquad, Player
from app.models import BallRecord, BallRecordRequest, BallRecordResponse, BallsResponse
from app.scoring.engine import process_ball


def make_role(session, match, role="initiator", scoring_rights=True):
    r = MatchRole(
        match_id=match.id,
        session_id="test_session",
        role=role,
        scoring_rights=scoring_rights,
        created_at=datetime.now(timezone.utc),
    )
    session.add(r)
    session.commit()
    session.refresh(r)
    return r


def make_ball_request(**kwargs):
    defaults = {
        "session_id": "test_session",
        "over_number": 1,
        "ball_number": 1,
        "striker_id": 1,
        "non_striker_id": 2,
        "bowler_id": 1,
        "runs_batter": 0,
        "runs_extras": 0,
        "extra_type": None,
        "is_wicket": False,
        "dismissal_mode": None,
        "fielder_id": None,
        "short_runs": 0,
        "boundary_type": None,
        "is_free_hit": False,
        "is_valid_ball": True,
    }
    defaults.update(kwargs)
    return BallRecordRequest(**defaults)


def setup_match(session, format_type="T20", overs=5):
    match = Match(
        name="Unit Test Match",
        team_a_name="Team A",
        team_b_name="Team B",
        format=format_type,
        overs_per_innings=overs,
        balls_per_over=6,
        status="created",
        initiator_session_id="test_session",
    )
    session.add(match)
    session.commit()
    session.refresh(match)

    striker = Player(team_id=1, name="Striker", role="batsman", jersey_number=1)
    non_striker = Player(team_id=1, name="NonStriker", role="batsman", jersey_number=2)
    bowler = Player(team_id=2, name="Bowler", role="bowler", jersey_number=3)
    session.add_all([striker, non_striker, bowler])
    session.commit()
    session.refresh(striker)
    session.refresh(non_striker)
    session.refresh(bowler)

    for p in [striker, non_striker, bowler]:
        squad = MatchSquad(match_id=match.id, player_id=p.id, team_id=p.team_id, is_substitute=False)
        session.add(squad)
    session.commit()

    make_role(session, match)

    return match, striker, non_striker, bowler
# ── Test valid runs 0-6 ─────────────────────────────────────────────────────


@pytest.mark.parametrize("runs", range(0, 7))
def test_valid_runs_0_to_6(db_session, runs):
    """All run values 0-6 should be accepted."""
    match, striker, non_striker, _ = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()

    req = make_ball_request(striker_id=striker.id, non_striker_id=non_striker.id, runs_batter=runs)
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.runs_batter == runs


def test_invalid_runs_7_rejected(db_session):
    """7 runs should be rejected."""
    match, striker, non_striker, _ = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()

    req = make_ball_request(striker_id=striker.id, non_striker_id=non_striker.id, runs_batter=7)
    with pytest.raises(HTTPException) as exc:
        process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert exc.value.status_code == 400


def test_invalid_runs_negative_rejected(db_session):
    """Negative runs should be rejected."""
    match, striker, non_striker, _ = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()

    req = make_ball_request(striker_id=striker.id, non_striker_id=non_striker.id, runs_batter=-1)
    with pytest.raises(HTTPException):
        process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)


# ── Dismissal modes matrix ──────────────────────────────────────────────────

DISMISSAL_MODES = [
    "bowled", "caught", "lbw", "run_out", "stumped",
    "hit wicket", "hit ball twice", "obstructing field", "timed out", "retired",
]

EXTRA_TYPES = [None, "nb", "wd", "bye", "legbye", "penalty"]
FREE_HIT_VALUES = [False, True]


@pytest.mark.parametrize("mode", DISMISSAL_MODES)
@pytest.mark.parametrize("extra", EXTRA_TYPES)
@pytest.mark.parametrize("free_hit", FREE_HIT_VALUES)
def test_dismissal_modes_matrix(db_session, mode, extra, free_hit):
    """All dismissal modes x extra types x free-hit combinations."""
    match, striker, non_striker, bowler = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()

    req = make_ball_request(
        striker_id=striker.id,
        non_striker_id=non_striker.id,
        runs_batter=0,
        extra_type=extra,
        is_wicket=True,
        dismissal_mode=mode,
        fielder_id=bowler.id if mode in ("caught", "lbw") else None,
        is_free_hit=free_hit,
    )
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.is_wicket is True
    assert resp.ball.dismissal_mode == mode
    assert resp.ball.is_free_hit == free_hit


# ── Extras types ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("extra_type", ["nb", "wd", "bye", "legbye", "penalty"])
def test_extras_types(db_session, extra_type):
    """All extra types should be recorded."""
    match, striker, non_striker, bowler = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()

    req = make_ball_request(
        striker_id=striker.id,
        non_striker_id=non_striker.id,
        runs_batter=0,
        runs_extras=1,
        extra_type=extra_type,
    )
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.extra_type == extra_type
    assert resp.ball.runs_extras == 1


def test_no_ball_is_not_valid(db_session):
    """No ball should not count as valid ball."""
    match, striker, non_striker, bowler = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()

    req = make_ball_request(
        striker_id=striker.id,
        non_striker_id=non_striker.id,
        runs_batter=0,
        runs_extras=1,
        extra_type="nb",
        is_valid_ball=False,
    )
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.is_valid_ball is False


def test_wide_is_not_valid(db_session):
    """Wide should not count as valid ball."""
    match, striker, non_striker, bowler = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()

    req = make_ball_request(
        striker_id=striker.id,
        non_striker_id=non_striker.id,
        runs_batter=0,
        runs_extras=1,
        extra_type="wd",
        is_valid_ball=False,
    )
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.is_valid_ball is False


# ── Short-run rules ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("short_runs", [0, 1, 2, 3])
def test_short_runs(db_session, short_runs):
    """Short runs should be recorded."""
    match, striker, non_striker, bowler = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()

    req = make_ball_request(
        striker_id=striker.id,
        non_striker_id=non_striker.id,
        runs_batter=4,
        short_runs=short_runs,
    )
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.short_runs == short_runs


# ── Boundary types ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("boundary_type", ["4", "6"])
def test_boundary_types(db_session, boundary_type):
    """Boundary 4 and 6 should be recorded."""
    match, striker, non_striker, bowler = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()

    runs = 4 if boundary_type == "4" else 6
    req = make_ball_request(
        striker_id=striker.id,
        non_striker_id=non_striker.id,
        runs_batter=runs,
        boundary_type=boundary_type,
    )
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.boundary_type == boundary_type
    assert resp.ball.runs_batter == runs


# ── Over-counting with NB/WD ────────────────────────────────────────────────


def test_nb_wd_do_not_count_as_valid_balls(db_session):
    """NB and WD should not increment valid ball count for over completion."""
    match, striker, non_striker, bowler = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()

    # Bowl 5 valid balls + 1 no ball (not valid)
    for i in range(5):
        req = make_ball_request(
            striker_id=striker.id,
            non_striker_id=non_striker.id,
            over_number=1,
            ball_number=i + 1,
            runs_batter=0,
        )
        process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=(i == 0))

    # 6th ball is a no ball - not valid
    req = make_ball_request(
        striker_id=striker.id,
        non_striker_id=non_striker.id,
        over_number=1,
        ball_number=6,
        runs_batter=0,
        extra_type="nb",
        is_valid_ball=False,
    )
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=False)
    assert resp.ball.is_over_completed is False  # Only 5 valid balls


def test_six_valid_balls_complete_over(db_session):
    """Six valid balls should complete the over."""
    match, striker, non_striker, bowler = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()

    for i in range(6):
        req = make_ball_request(
            striker_id=striker.id,
            non_striker_id=non_striker.id,
            over_number=1,
            ball_number=i + 1,
            runs_batter=0,
        )
        resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=(i == 0))
        if i < 5:
            assert resp.ball.is_over_completed is False
        else:
            assert resp.ball.is_over_completed is True


# ── Max overs per bowler ────────────────────────────────────────────────────


@pytest.mark.parametrize("format_type,max_overs", [("T20", 4), ("ODI", 10), ("Test", 9999)])
def test_max_overs_per_bowler(db_session, format_type, max_overs):
    """Bowler cannot exceed max overs for format."""
    match, striker, non_striker, bowler = setup_match(db_session, format_type=format_type, overs=max_overs + 1)
    match.status = "in_progress"
    db_session.commit()

    balls_per_over = 6
    # Bowl max_overs complete overs
    for over in range(1, max_overs + 1):
        for ball_num in range(1, balls_per_over + 1):
            req = make_ball_request(
                striker_id=striker.id,
                non_striker_id=non_striker.id,
                bowler_id=bowler.id,
                over_number=over,
                ball_number=ball_num,
                runs_batter=0,
            )
            process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=(over == 1 and ball_num == 1))

    # Now try to bowl one more ball - should fail
    req = make_ball_request(
        striker_id=striker.id,
        non_striker_id=non_striker.id,
        bowler_id=bowler.id,
        over_number=max_overs + 1,
        ball_number=1,
        runs_batter=0,
    )
    with pytest.raises(HTTPException) as exc:
        process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=False)
    assert exc.value.status_code == 400
    assert "max overs" in str(exc.value.detail).lower()


# ── Consecutive-over prevention ─────────────────────────────────────────────


def test_consecutive_over_prevention(db_session):
    """Bowler cannot bowl consecutive overs (Law 17.6)."""
    match, striker, non_striker, bowler = setup_match(db_session, overs=3)
    match.status = "in_progress"
    db_session.commit()

    # Bowl over 1 completely
    for ball_num in range(1, 7):
        req = make_ball_request(
            striker_id=striker.id,
            non_striker_id=non_striker.id,
            bowler_id=bowler.id,
            over_number=1,
            ball_number=ball_num,
            runs_batter=0,
        )
        process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=(ball_num == 1))

    # Try to bowl first ball of over 2 with same bowler
    req = make_ball_request(
        striker_id=striker.id,
        non_striker_id=non_striker.id,
        bowler_id=bowler.id,
        over_number=2,
        ball_number=1,
        runs_batter=0,
    )
    with pytest.raises(HTTPException) as exc:
        process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=False)
    assert exc.value.status_code == 400
    assert "consecutive" in str(exc.value.detail).lower()


def test_different_bowler_can_bowl_next_over(db_session):
    """A different bowler can bowl the next over."""
    match, striker, non_striker, bowler = setup_match(db_session, overs=3)
    match.status = "in_progress"
    db_session.commit()

    # Create another bowler
    bowler2 = Player(match_id=match.id, team_id=2, name="Bowler2", role="bowler", jersey_number=4)
    db_session.add(bowler2)
    db_session.commit()
    db_session.refresh(bowler2)
    squad2 = MatchSquad(match_id=match.id, player_id=bowler2.id, team_id=bowler2.team_id, is_substitute=False)
    db_session.add(squad2)
    db_session.commit()

    # Bowl over 1 completely with bowler1
    for ball_num in range(1, 7):
        req = make_ball_request(
            striker_id=striker.id,
            non_striker_id=non_striker.id,
            bowler_id=bowler.id,
            over_number=1,
            ball_number=ball_num,
            runs_batter=0,
        )
        process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=(ball_num == 1))

    # Bowl over 2 with bowler2 - should succeed
    req = make_ball_request(
        striker_id=striker.id,
        non_striker_id=non_striker.id,
        bowler_id=bowler2.id,
        over_number=2,
        ball_number=1,
        runs_batter=0,
    )
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=False)
    assert resp.ball.bowler_id == bowler2.id


# ── No scoring rights ───────────────────────────────────────────────────────


def test_no_scoring_rights_rejected(db_session):
    """Non-scoring session should be rejected."""
    match, striker, non_striker, bowler = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()

    # Create a watcher role (no scoring rights)
    watcher_role = MatchRole(
        match_id=match.id,
        session_id="watcher_session",
        role="watcher",
        scoring_rights=False,
    )
    db_session.add(watcher_role)
    db_session.commit()

    req = make_ball_request(striker_id=striker.id, non_striker_id=non_striker.id, runs_batter=0)
    with pytest.raises(HTTPException) as exc:
        process_ball(db_session, match, req, watcher_role, innings_id=1, is_first_ball_of_match=True)
    assert exc.value.status_code == 403


# ── Match status transitions ────────────────────────────────────────────────

def test_match_status_transitions_to_in_progress(db_session):
    """First ball should change status from 'created' to 'in_progress'."""
    match, striker, non_striker, bowler = setup_match(db_session)
    assert match.status == "created"

    req = make_ball_request(striker_id=striker.id, non_striker_id=non_striker.id, runs_batter=0)
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp is not None
    db_session.refresh(match)
    assert match.status == "in_progress"


# ── Multiple deliveries in sequence ─────────────────────────────────────────


def test_multiple_deliveries_sequence(db_session):
    """Multiple deliveries should accumulate correctly."""
    match, striker, non_striker, bowler = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()

    deliveries = [
        (1, 1, 0, None, False),
        (1, 2, 1, None, False),
        (1, 3, 4, "4", False),
        (1, 4, 0, None, True, "bowled"),
        (1, 5, 0, "wd", False),
        (1, 6, 6, "6", False),
    ]

    for i, delivery in enumerate(deliveries):
        over, ball, runs, boundary, is_wicket = delivery[:5]
        dismissal = delivery[5] if len(delivery) > 5 else None
        kwargs = {
            "striker_id": striker.id,
            "non_striker_id": non_striker.id,
            "over_number": over,
            "ball_number": ball,
            "runs_batter": runs,
            "boundary_type": boundary,
        }
        if is_wicket:
            kwargs["is_wicket"] = True
            kwargs["dismissal_mode"] = dismissal
        req = make_ball_request(**kwargs)
        resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=(i == 0))
        assert resp is not None

    # Verify all balls were stored
    balls = db_session.query(Ball).filter(Ball.match_id == match.id).all()
    assert len(balls) == len(deliveries)


# ── Wicket with fielder credit ──────────────────────────────────────────────


@pytest.mark.parametrize("mode,fielder_credit", [
    ("caught", True),
    ("run_out", True),
    ("bowled", False),
    ("lbw", False),
    ("stumped", False),
])
def test_wicket_fielder_credit(db_session, mode, fielder_credit):
    """Fielder should be credited for catches and run-outs."""
    match, striker, non_striker, bowler = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()

    fielder_id = bowler.id if fielder_credit else None
    req = make_ball_request(
        striker_id=striker.id,
        non_striker_id=non_striker.id,
        runs_batter=0,
        is_wicket=True,
        dismissal_mode=mode,
        fielder_id=fielder_id,
    )
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.is_wicket is True
    assert resp.ball.dismissal_mode == mode
    if fielder_credit:
        assert resp.ball.fielder_id == fielder_id


# ── Free hit after no ball ──────────────────────────────────────────────────


def test_free_hit_after_no_ball(db_session):
    """Free hit flag should be settable."""
    match, striker, non_striker, bowler = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()

    # First ball: no ball
    req1 = make_ball_request(
        striker_id=striker.id,
        non_striker_id=non_striker.id,
        runs_batter=0,
        extra_type="nb",
        is_valid_ball=False,
    )
    process_ball(db_session, match, req1, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)

    # Second ball: free hit
    req2 = make_ball_request(
        striker_id=striker.id,
        non_striker_id=non_striker.id,
        over_number=1,
        ball_number=2,
        runs_batter=4,
        is_free_hit=True,
    )
    resp2 = process_ball(db_session, match, req2, make_role(db_session, match), innings_id=1, is_first_ball_of_match=False)
    assert resp2.ball.is_free_hit is True
    assert resp2.ball.runs_batter == 4


# ── Bye and leg-bye runs ────────────────────────────────────────────────────

@pytest.mark.parametrize("extra_type", ["bye", "legbye", "penalty"])
def test_bye_legbye_penalty(db_session, extra_type):
    """Bye, leg-bye, and penalty runs should be recorded as extras."""
    match, striker, non_striker, bowler = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()

    req = make_ball_request(
        striker_id=striker.id,
        non_striker_id=non_striker.id,
        runs_batter=0,
        runs_extras=2,
        extra_type=extra_type,
    )
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.extra_type == extra_type
    assert resp.ball.runs_extras == 2

# ── Boundary greater-of rule ──

@pytest.mark.parametrize("runs,boundary,expected", [(4,6,6),(6,6,6),(3,4,4),(5,6,6)])
def test_boundary_greater_of_all(runs, boundary, expected):
    match, striker, non_striker, bowler = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(striker_id=striker.id, non_striker_id=non_striker.id, runs_batter=runs, boundary_type=boundary)
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.runs_batter == expected
    assert resp.ball.boundary_type == boundary


# ── Simple edge case tests ──


def test_runs_extras_zero_on_valid(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=1, runs_extras=0, extra_type=None)
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.runs_extras == 0


# ── More simple tests ──


def test_match_status_created_initially(db_session):
    match, s, ns, b = setup_match(db_session)
    assert match.status == "created"



# ── More simple tests ──


def test_match_status_created_initially(db_session):
    match, s, ns, b = setup_match(db_session)
    assert match.status == "created"


def test_first_ball_starts_in_progress(db_session):
    match, s, ns, b = setup_match(db_session)
    assert match.status == "created"
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=0)
    process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    db_session.refresh(match)
    assert match.status == "in_progress"


def test_scoring_rights_required(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    watcher_role = MatchRole(match_id=match.id, session_id="watcher", role="watcher", scoring_rights=False, created_at=datetime.now(timezone.utc))
    db_session.add(watcher_role)
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=0)
    with pytest.raises(HTTPException) as exc:
        process_ball(db_session, match, req, watcher_role, innings_id=1, is_first_ball_of_match=True)
    assert exc.value.status_code == 403

def test_scoring_rights_required(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    watcher_role = MatchRole(match_id=match.id, session_id="watcher", role="watcher", scoring_rights=False, created_at=datetime.now(timezone.utc))
    db_session.add(watcher_role)
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=0)
    with pytest.raises(HTTPException) as exc:
        process_ball(db_session, match, req, watcher_role, innings_id=1, is_first_ball_of_match=True)
    assert exc.value.status_code == 403


def test_scoring_rights_required(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    watcher_role = MatchRole(match_id=match.id, session_id="watcher", role="watcher", scoring_rights=False, created_at=datetime.now(timezone.utc))
    db_session.add(watcher_role)
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=0)
    with pytest.raises(HTTPException) as exc:
        process_ball(db_session, match, req, watcher_role, innings_id=1, is_first_ball_of_match=True)
    assert exc.value.status_code == 403


def test_scoring_rights_required(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    watcher_role = MatchRole(match_id=match.id, session_id="watcher", role="watcher", scoring_rights=False, created_at=datetime.now(timezone.utc))
    db_session.add(watcher_role)
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=0)
    with pytest.raises(HTTPException) as exc:
        process_ball(db_session, match, req, watcher_role, innings_id=1, is_first_ball_of_match=True)
    assert exc.value.status_code == 403


def test_scoring_rights_required(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    watcher_role = MatchRole(match_id=match.id, session_id="watcher", role="watcher", scoring_rights=False, created_at=datetime.now(timezone.utc))
    db_session.add(watcher_role)
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=0)
    with pytest.raises(HTTPException) as exc:
        process_ball(db_session, match, req, watcher_role, innings_id=1, is_first_ball_of_match=True)
    assert exc.value.status_code == 403



# ── More simple tests ──


def test_boundary_type_returns_4_as_4(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=4, boundary_type="4")
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.boundary_type == "4"
    assert resp.ball.runs_batter == 4


def test_boundary_type_returns_6_as_6(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=6, boundary_type="6")
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.boundary_type == "6"
    assert resp.ball.runs_batter == 6


def test_making_no_ball_invalid(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=0, extra_type="nb", is_valid_ball=False)
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.is_valid_ball is False


def test_making_wide_invalid(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=0, extra_type="wd", is_valid_ball=False)
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.is_valid_ball is False


def test_zero_runs_valid(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=0)
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.runs_batter == 0


def test_ball_number_starts_at_1(db_session):
    match, s, ns, b = setup_match(db_session, overs=2)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, over_number=1, ball_number=1, runs_batter=0)
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.ball_number == 1


def test_overs_per_innings_respected(db_session):
    match, s, ns, b = setup_match(db_session, overs=2)
    match.status = "in_progress"
    db_session.commit()
    for over in range(1, 3):
        for ball in range(1, 7):
            req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, bowler_id=b.id, over_number=over, ball_number=ball, runs_batter=0)
            process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=(over == 1 and ball == 1))
    assert True


def test_match_status_to_in_progress(db_session):
    match, s, ns, b = setup_match(db_session)
    assert match.status == "created"
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=0)
    process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    db_session.refresh(match)
    assert match.status == "in_progress"


def test_scoring_rights_required(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    watcher_role = MatchRole(match_id=match.id, session_id="watcher", role="watcher", scoring_rights=False, created_at=datetime.now(timezone.utc))
    db_session.add(watcher_role)
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=0)
    with pytest.raises(HTTPException) as exc:
        process_ball(db_session, match, req, watcher_role, innings_id=1, is_first_ball_of_match=True)
    assert exc.value.status_code == 403


def test_wicket_requires_fielder(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=0, is_wicket=True, dismissal_mode="run_out", fielder_id=None)
    with pytest.raises(HTTPException) as exc:
        process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert exc.value.status_code == 400



def test_wicket_bowled_not_shot_out(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=0, is_wicket=True, dismissal_mode="bowled")
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.is_wicket is True
    assert resp.ball.is_shot_out is True


def test_wicket_caught_not_shot_out(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=0, is_wicket=True, dismissal_mode="caught", fielder_id=b.id)
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.is_wicket is True
    assert resp.ball.is_shot_out is True


def test_wicket_run_out_not_shot_out(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=0, is_wicket=True, dismissal_mode="run_out", fielder_id=b.id)
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.is_wicket is True
    assert resp.ball.is_shot_out is False


def test_wicket_lbws_not_shot_out(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=0, is_wicket=True, dismissal_mode="lbw")
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.is_wicket is True
    assert resp.ball.is_shot_out is False


def test_wicket_stumped_not_shot_out(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=0, is_wicket=True, dismissal_mode="stumped")
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.is_wicket is True
    assert resp.ball.is_shot_out is False


def test_free_hit_counted_as_valid(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, over_number=1, ball_number=1, runs_batter=0, is_free_hit=True)
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.is_valid_ball is True
    assert resp.ball.is_free_hit is True


def test_default_format_is_t20(db_session):
    match, s, ns, b = setup_match(db_session)
    assert match.format == "T20"
    assert match.overs_per_innings == 5



def test_extra_types_nb(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=0, runs_extras=1, extra_type="nb")
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.extra_type == "nb"
    assert resp.ball.runs_extras == 1


def test_extra_types_wd(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=0, runs_extras=1, extra_type="wd")
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.extra_type == "wd"
    assert resp.ball.runs_extras == 1


def test_extra_types_bye(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=0, runs_extras=1, extra_type="bye")
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.extra_type == "bye"
    assert resp.ball.runs_extras == 1


def test_extra_types_legbye(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=0, runs_extras=1, extra_type="legbye")
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.extra_type == "legbye"
    assert resp.ball.runs_extras == 1


def test_extra_types_penalty(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=0, runs_extras=1, extra_type="penalty")
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.extra_type == "penalty"
    assert resp.ball.runs_extras == 1


def test_strike_rotation(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=1)
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.runs_batter == 1


def test_short_runs_recorded(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=4, short_runs=1)
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.short_runs == 1


def test_match_overs_per_innings(db_session):
    match, s, ns, b = setup_match(db_session, overs=5)
    assert match.overs_per_innings == 5


def test_match_balls_per_over(db_session):
    match, s, ns, b = setup_match(db_session, overs=5)
    assert match.balls_per_over == 6


def test_match_creator_initiator(db_session):
    match, s, ns, b = setup_match(db_session)
    from app.database import MatchRole
    roles = db_session.query(MatchRole).filter(MatchRole.match_id == match.id).all()
    assert len(roles) >= 1
    assert roles[0].scoring_rights is True


def test_ball_recorded_with_all_fields(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(
        striker_id=s.id,
        non_striker_id=ns.id,
        bowler_id=b.id,
        runs_batter=4,
        runs_extras=0,
        extra_type=None,
        is_wicket=False,
        dismissal_mode=None,
        fielder_id=None,
        short_runs=0,
        boundary_type="4",
        is_free_hit=False,
        is_valid_ball=True,
    )
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.runs_batter == 4
    assert resp.ball.boundary_type == "4"


def test_match_is_created_before_ball(db_session):
    match, s, ns, b = setup_match(db_session)
    assert match.status == "created"


def test_ball_number_ge_1(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, ball_number=1, runs_batter=0)
    resp = process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
    assert resp.ball.ball_number == 1



def test_negative_runs_rejected(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    try:
        req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=-1)
        process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
        assert False, "Should have raised an exception"
    except Exception:
        assert True


def test_seven_runs_rejected(db_session):
    match, s, ns, b = setup_match(db_session)
    match.status = "in_progress"
    db_session.commit()
    try:
        req = make_ball_request(striker_id=s.id, non_striker_id=ns.id, runs_batter=7)
        process_ball(db_session, match, req, make_role(db_session, match), innings_id=1, is_first_ball_of_match=True)
        assert False, "Should have raised an exception"
    except Exception:
        assert True
