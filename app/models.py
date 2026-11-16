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
        20, ge=5, le=500, description="Overs per innings (initiator decides)"
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