from datetime import datetime, timezone
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


# --- Anonymous Session Models ---


class AnonymousSessionCreate(BaseModel):
    """Create an anonymous session (optional device nickname)."""

    device_name: Optional[str] = Field(None, max_length=100, description="Optional nickname for the device")


class AnonymousSessionResponse(BaseModel):
    """Response model for anonymous session."""

    id: int
    session_id: str
    device_name: Optional[str]
    created_at: datetime
    last_seen_at: datetime

    class Config:
        from_attributes = True


# --- Match Models ---


class MatchCreate(BaseModel):
    """Create a new match (anonymous, no auth required)."""

    team_a_name: str = Field(..., max_length=150, description="First team name")
    team_b_name: str = Field(..., max_length=150, description="Second team name")
    format: str = Field("Custom", max_length=20, description="Match format: T20, ODI, Test, Custom")
    overs_per_innings: int = Field(
        20, ge=1, le=500, description="Overs per innings (initiator decides)"
    )
    balls_per_over: int = Field(
        6, ge=1, le=10, description="Balls per over"
    )


class MatchResponse(BaseModel):
    """Response model for match details (public or authenticated)."""

    id: int
    name: str
    team_a_name: str
    team_b_name: str
    format: str
    overs_per_innings: int
    balls_per_over: int
    status: str
    initiator_session_id: str
    checksum: Optional[str]
    created_at: datetime
    updated_at: datetime
    locked_at: Optional[str]

    class Config:
        from_attributes = True


class MatchPublicResponse(BaseModel):
    """Public match summary - no auth required."""

    match_id: int
    team_a_name: str
    team_b_name: str
    format: str
    overs_per_innings: int
    current_score: str  # e.g. "150/5"
    current_overs: float  # e.g. 15.3
    wickets: int
    status: str
    last_updated: datetime


# --- Match Role Models ---


class MatchRoleCreate(BaseModel):
    """Request to create/update a match role."""

    role: str = Field(
        "scorer", max_length=20, description="Role: initiator / scorer / watcher"
    )
    scoring_rights: bool = Field(False, description="Whether session has scoring rights")


class MatchRoleResponse(BaseModel):
    """Response model for match role."""

    match_id: int
    session_id: str
    role: str
    scoring_rights: bool
    approved_by_session_id: Optional[str]
    approved_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


# --- Scoring Rights Request Models ---


class ScoringRightRequestCreate(BaseModel):
    """Request to add scoring rights (anonymous session requests)."""

    requestor_session_id: str = Field(..., description="Session ID requesting rights")
    device_name: Optional[str] = Field(None, max_length=100, description="Optional device name")


class ScoringRightRequestResponse(BaseModel):
    """Response model for scoring right request."""

    id: int
    match_id: int
    requestor_session_id: str
    device_name: Optional[str]
    status: str = "pending"  # pending / approved / rejected
    requested_at: datetime
    approved_at: Optional[datetime]

    class Config:
        from_attributes = True


# --- Ball Recording Models ---


class BallRecord(BaseModel):
    """Ball recording input (requires scoring rights)."""

    session_id: str
    over_number: int = Field(..., ge=1, description="Over number (1-based)")
    ball_number: int = Field(
        1, ge=1, le=6, description="Ball number within over (1-6)"
    )
    striker_id: Optional[int] = Field(None, description="Striker batter index")
    non_striker_id: Optional[int] = Field(None, description="Non-striker batter index")
    runs_batter: int = Field(0, ge=0, description="Runs scored by batter")
    runs_extras: int = Field(0, ge=0, description="Extras runs")
    extra_type: Optional[str] = Field(
        None, max_length=20, description="Extra type: no_ball, wide, bye, leg_bye"
    )
    is_wicket: bool = Field(False, description="Whether a wicket fell")
    dismissal_mode: Optional[str] = Field(
        None, max_length=30, description="Dismissal mode if wicket"
    )
    fielder_id: Optional[int] = Field(None, description="Fielder index if involved")
    short_runs: int = Field(0, ge=0, description="Short runs subtracted")
    boundary_type: Optional[str] = Field(
        None, max_length=10, description="Boundary type: 4, 6"
    )
    is_free_hit: bool = Field(False, description="Whether this is a free hit")
    is_valid_ball: bool = Field(True, description="Whether this counts as a valid ball")


class BallRecordResponse(BaseModel):
    """Response model for recorded ball."""

    ball_id: int
    over_number: int
    ball_number: int
    runs_total: int
    runs_batter: int
    runs_extras: int
    wickets: int
    total_overs: float
    status: str


# --- Result/Confirmation Models ---


class ConfirmScoresRequest(BaseModel):
    """Request to confirm scores (Law 3.2)."""

    confirmed_by_session_id: str


class LockMatchRequest(BaseModel):
    """Request to lock match result."""

    locked_by_session_id: str
    result: str  # e.g. "team_a_won", "team_b_won", "tie", "conceded"
    margin: Optional[str] = Field(None, description="Runs or wickets margin")


# --- MVP Award Models ---


class MvpAwardRequest(BaseModel):
    """Request to award MVP."""

    player_id: int = Field(..., ge=1, description="Player index from candidates list")
    points: int = Field(..., ge=0, description="Points awarded")
    reason_summary: str = Field(..., max_length=500, description="Reason for MVP award")
    awarded_by_session_id: str


# --- Module 3 Response Models ---


class TeamResponse(BaseModel):
    """Response for team data."""

    id: int
    name: str
    short_name: Optional[str]
    created_at: datetime


class PlayerResponse(BaseModel):
    """Response for player data."""

    id: int
    team_id: int
    name: str
    role: str
    jersey_number: Optional[int]
    created_at: datetime


class MatchTeamLinkResponse(BaseModel):
    """Response for match-team link."""

    id: int
    match_id: int
    team_id: int
    team_role: str
    team_name: str
    short_name: Optional[str]
    is_home: bool
    created_at: datetime


class MatchSquadResponse(BaseModel):
    """Response for match squad."""

    id: int
    match_id: int
    player_id: int
    team_id: int
    is_substitute: bool
    created_at: datetime


class PlayingXIResponse(BaseModel):
    """Response for playing XI entries."""

    id: int
    match_id: int
    player_id: int
    team_id: int
    is_captain: bool
    is_wicketkeeper: bool
    created_at: datetime


class TossResponse(BaseModel):
    """Response for toss records. Two-phase: call + flip."""

    id: int
    match_id: int
    initiator_call: Optional[str]  # heads or tails called
    coin_result: Optional[str]  # heads or tails actual result
    winner_team_id: Optional[int]
    toss_decision: Optional[str]  # bat or field chosen by winning team
    called_by_session_id: Optional[str]
    created_at: datetime


class FormatConfigResponse(BaseModel):
    """Response for format configuration."""

    id: int
    format_name: str
    overs_per_innings: int
    balls_per_over: int
    max_overs_per_bowler: int
    free_hit_after_no_ball: bool
    powerplay_max_overs: Optional[int]
    new_ball_every_overs: Optional[int]
    follow_on_threshold: Optional[int]
    created_at: datetime


# --- Module 3 Request Models ---


class TeamData(BaseModel):
    """Request model for team creation."""

    team_a_name: str = Field(..., max_length=150)
    team_a_short: Optional[str] = Field(None, max_length=50, description="Team A short name")
    team_b_name: str = Field(..., max_length=150)
    team_b_short: Optional[str] = Field(None, max_length=50, description="Team B short name")


class Player(BaseModel):
    """Request model for player data."""

    team_id: int
    name: str
    role: str = Field("all-rounder", description="batter / bowler / all-rounder / wicketkeeper")
    jersey_number: Optional[int] = Field(None, description="1-11 for the XI")
    is_substitute: bool = Field(False, description="Whether player is a substitute")


class XIEntry(BaseModel):
    """Entry in playing XI selection."""

    player_id: int
    team_id: int
    is_captain: bool = Field(False)
    is_wicketkeeper: bool = Field(False)


class TossCallData(BaseModel):
    """Request model for initiating the toss call (Phase 1)."""

    call: str = Field(..., description="heads or tails (initiator call)")


class TossFlipData(BaseModel):
    """Request model for flipping the coin (Phase 2)."""

    pass


class TossResultData(BaseModel):
    """Response data for toss outcome with decision."""

    winner_team_id: int = Field(..., description="Team that won the toss")
    coin_result: str = Field(..., description="heads or tails")
    toss_decision: str = Field(..., description="bat or field chosen by winning team")


class BallRecordRequest(BaseModel):
    """Request model for recording a delivery."""
    bowler_id: int = Field(..., description="Player ID of the bowler")
    striker_id: int = Field(..., description="Player ID of the striker")
    non_striker_id: int = Field(..., description="Player ID of the non-striker")
    runs_batter: int = Field(0, ge=0, le=6, description="Runs scored by batter (0-6)")
    runs_extras: int = Field(0, ge=0, description="Extras scored")
    over_number: int = Field(..., ge=1, description="Over number (1-based)")
    ball_number: int = Field(..., ge=1, le=6, description="Ball number within over (1-6)")
    extra_type: Optional[str] = Field(None, description="nb / wd / bye / legbye / penalty")
    penalty_runs: int = Field(0, ge=0, description="Penalty runs (separate from extras)")
    is_wicket: bool = Field(False, description="Whether a wicket fell")
    dismissal_mode: Optional[str] = Field(None, description="Bowled / caught / lbw / run_out / stumped / etc.")
    fielder_id: Optional[int] = Field(None, description="Player ID of the fielder")
    short_runs: int = Field(0, ge=0, description="Short run penalty (leg-bye style)")
    deliberate_short_run: bool = Field(False, description="Whether short runs were deliberate (5-run penalty to fielding side)")
    boundary_type: Optional[str] = Field(None, description="4 / 6 / None")
    is_free_hit: bool = Field(False, description="Free hit after no ball")
    is_valid_ball: bool = Field(True, description="Whether this counts as a valid ball")
    delivery_type: Optional[str] = Field(None, description="Optional shorthand delivery type from UI (e.g. 0-6, nb, wd, bye, wicket)")

class BallRecordResponse(BaseModel):
    """Response model for a recorded delivery."""
    ball_id: int
    match_id: int
    innings_id: int
    over_number: int
    ball_number: int
    bowler_id: int
    striker_id: int
    non_striker_id: int
    runs_batter: int
    runs_extras: int
    extra_type: Optional[str]
    penalty_runs: int
    is_wicket: bool
    dismissal_mode: Optional[str]
    fielder_id: Optional[int]
    short_runs: int
    boundary_type: Optional[str]
    is_free_hit: bool
    is_valid_ball: bool
    is_over_completed: bool
    is_shot_out: bool
    created_at: datetime


class BallsResponse(BaseModel):
    """Response containing the ball record and updated match state."""
    ball: BallRecordResponse
    current_score: str  # e.g. "15/2"
    current_overs: float  # e.g. 15.3
    wickets: int
    current_innings: int  # 1 or 2
    over_number: int
    ball_number: int
    striker: int  # player_id
    non_striker: int  # player_id
    bowler: int  # player_id
    match_id: int
    checksum: str


# ── Scorecard Models ──


class BattingScorecardEntry(BaseModel):
    player_id: int
    name: str
    runs: int
    balls: int
    fours: int
    sixes: int
    strike_rate: float
    dismissal: Optional[str]
    dismissal_mode: Optional[str]
    bowler_fielder_id: Optional[int]


class BowlingAnalysisEntry(BaseModel):
    player_id: int
    name: str
    overs: str  # cricket notation e.g. "10.3"
    maidens: int
    runs: int
    wickets: int
    wides: int
    no_balls: int
    economy: float


class ExtrasSummary(BaseModel):
    no_balls: int
    wides: int
    byes: int
    leg_byes: int
    penalties: int
    total_extras: int


class FallOfWicketEntry(BaseModel):
    wicket: int
    batter_out: str
    batter_out_id: int
    not_out_batter: str
    not_out_batter_id: int
    runs_at_fall: int
    over: str
    partnership: int


class InningsScorecard(BaseModel):
    innings_id: int
    batting: List[BattingScorecardEntry]
    bowling: List[BowlingAnalysisEntry]
    extras: ExtrasSummary
    fall_of_wickets: List[FallOfWicketEntry]


class MatchScorecard(BaseModel):
    match_id: int
    innings: List[InningsScorecard]


class MatchResult(BaseModel):
    result_type: str  # win_by_runs / win_by_wickets / tie / no_result / no_match
    winner_team_id: Optional[int]
    margin_runs: int
    margin_wickets: int
    margin_text: str
    details: dict


class FollowOnStatus(BaseModel):
    follow_on_possible: bool
    threshold: int
    team_a_runs: int
    team_b_runs: int
    lead: int
    should_offer: bool
    message: str


class SuperOverStatus(BaseModel):
    available: bool
    message: str
    team_a_score: Optional[int]
    team_b_score: Optional[int]
    winner_team_id: Optional[int]


class LockMatchRequest(BaseModel):
    confirm: bool = Field(..., description="Must be true to lock the match")


class LockMatchResponse(BaseModel):
    match_id: int
    status: str
    locked_at: Optional[datetime]
    message: str


# ── MVP Models ──


class MVPPointsBreakdown(BaseModel):
    """Points breakdown for a player from delivery log."""

    player_id: int
    name: str
    team_id: int
    runs: int = 0
    wickets: int = 0
    fours: int = 0
    sixes: int = 0
    catches: int = 0
    run_outs: int = 0
    balls_faced: int = 0
    strike_rate: float = 0.0
    overs_bowled: float = 0.0
    economy_rate: float = 0.0
    points_runs: int = 0  # 1 point per run
    points_wickets: int = 0  # 10 points per wicket
    points_catches: int = 0  # 5 points per catch
    points_run_outs: int = 0  # 5 points per run-out
    points_strike_rate: int = 0  # bonus for SR > 150
    points_economy: int = 0  # bonus for economy < 7
    points_win_bonus: int = 0  # bonus for winning team
    total_points: int = 0


class MVPCandidate(BaseModel):
    """MVP candidate with points breakdown."""

    player_id: int
    name: str
    team_id: int
    team_role: str
    total_points: int
    breakdown: MVPPointsBreakdown


class MVPCreate(BaseModel):
    """Request to create an MVP award."""

    player_id: int = Field(..., description="Player ID to award MVP to")
    points: int = Field(..., ge=0, description="Total points for the MVP")
    reason_summary: Optional[str] = Field(None, max_length=500, description="Reason for award")


class MVPResponse(BaseModel):
    """Response model for MVP award."""

    id: int
    match_id: int
    player_id: int
    points: int
    reason_summary: Optional[str]
    awarded_by_session_id: str
    awarded_at: datetime

    class Config:
        from_attributes = True


class MvpAwardRequest(BaseModel):
    """Request to award MVP to a player."""

    player_id: int = Field(..., description="Player ID to award MVP to")
    points: int = Field(..., ge=0, description="Total points for the MVP")
    reason_summary: Optional[str] = Field(None, max_length=500, description="Reason for award")
