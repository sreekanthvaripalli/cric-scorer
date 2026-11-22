import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    String,
    Boolean,
    Integer,
    Text,
    func,
    create_engine,
)
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.pool import StaticPool

Base = declarative_base()

# ── Database configuration ────────────────────────────────────────────────
# DATABASE_URL defaults to a local SQLite file (cric_scorer.db beside the app).
# Set DATABASE_URL env var to switch to PostgreSQL or another backend.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "sqlite:///./cric_scorer.db"
)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    poolclass=StaticPool if DATABASE_URL == "sqlite:///:memory:" else None,
)

session_local = scoped_session(
    sessionmaker(autocommit=False, autoflush=False, bind=engine)
)


def get_session_local():
    return session_local


def init_db():
    """Create all tables defined on Base. Call this at application startup."""
    Base.metadata.create_all(bind=engine)


class AnonymousSession(Base):
    """Anonymous session model for matches without user authentication.

    Each match creation or scoring session gets an anonymous session
    identifier. No passwords, usernames, or personal data is stored.
    """

    __tablename__ = "anonymous_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(36), unique=True, index=True, nullable=False, default=lambda: str(uuid.uuid4()))
    device_name = Column(String(100), nullable=True)  # optional nickname
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_seen_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class Match(Base):
    """Match model for anonymous cricket matches.

    Any device can create a match anonymously. The creator becomes the
    initiator with full scoring rights by default. Team names and match
    configuration are stored here.
    """

    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)  # e.g. "City vs Country"
    venue = Column(String(300), nullable=True)
    date = Column(DateTime(timezone=True), nullable=True)
    format = Column(String(20), nullable=False, default="Custom")  # T20, ODI, Test, Custom
    overs_per_innings = Column(Integer, nullable=False, default=20)  # configurable by initiator
    balls_per_over = Column(Integer, nullable=False, default=6)
    status = Column(
        String(20),
        nullable=False,
        default="created",  # created / in_progress / completed / locked
    )
    initiator_session_id = Column(
        String(36), nullable=False
    )  # session_id of the match creator
    checksum = Column(String(64), nullable=True)  # match integrity hash
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    locked_at = Column(DateTime(timezone=True), nullable=True)
    team_a_name = Column(String(150), nullable=False)  # stored at match creation
    team_b_name = Column(String(150), nullable=False)  # stored at match creation
    innings_count = Column(Integer, nullable=False, default=0)
    toss_winner_team_id = Column(Integer, nullable=True)
    toss_decision = Column(String(10), nullable=True)  # 'bat' or 'field'
    # Manual result override (Draw / Conceded / Awarded) — FR-6.5
    result_type = Column(String(30), nullable=True)
    winner_team_id_manual = Column(Integer, nullable=True)
    margin_runs = Column(Integer, nullable=True, default=0)
    margin_wickets = Column(Integer, nullable=True, default=0)
    margin_text = Column(String(100), nullable=True)
    team_a_runs = Column(Integer, nullable=True, default=0)
    team_a_wickets = Column(Integer, nullable=True, default=0)
    team_a_overs = Column(String(10), nullable=True, default="0.0")
    team_b_runs = Column(Integer, nullable=True, default=0)
    team_b_wickets = Column(Integer, nullable=True, default=0)
    team_b_overs = Column(String(10), nullable=True, default="0.0")


class MatchRole(Base):
    """MatchRole model linking a session to a match with a specific role.

    Roles: initiator (match creator, default scoring rights),
           scorer (approved to record deliveries),
           watcher (read-only, can view live score).

    scoring_rights indicates whether this session can record deliveries.
    approved_by_session_id tracks who approved the role change.
    """

    __tablename__ = "match_roles"

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, nullable=False)  # foreign key to matches.id
    session_id = Column(String(36), nullable=False)  # anonymous session identifier
    role = Column(
        String(20),
        nullable=False,  # initiator / scorer / watcher
        default="watcher",
    )
    scoring_rights = Column(Boolean, nullable=False, default=False)
    approved_by_session_id = Column(String(36), nullable=True)  # session that approved
    approved_at = Column(
        DateTime(timezone=True), nullable=True
    )  # when approval happened
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )  # when role was created

# Module 3: Teams, players, squads & format config
class Team(Base):
    """Team model for cricket teams in a match."""

    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)  # team name
    short_name = Column(String(50), nullable=True)  # e.g. "CC" for Cricket Club
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class Player(Base):
    """Player model for individuals in a team squad."""

    __tablename__ = "players"

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, nullable=True)  # optional match_id
    team_id = Column(Integer, nullable=False)  # foreign key to teams.id
    name = Column(String(150), nullable=False)  # player name
    role = Column(
        String(20),
        nullable=False,
        default="all-rounder",  # batter / bowler / all-rounder / wicketkeeper
    )
    jersey_number = Column(Integer, nullable=True)  # 1-11 for the XI
    is_substitute = Column(Boolean, nullable=True, default=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class MatchTeamLink(Base):
    """Link a team to a match."""

    __tablename__ = "match_team_links"

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, nullable=False)
    team_id = Column(Integer, nullable=False)
    team_role = Column(
        String(10), nullable=False, default="team_a"  # team_a or team_b
    )
    is_home = Column(Boolean, nullable=False, default=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class MatchSquad(Base):
    """Player squad for a match (up to 12 players per team, 11 + sub)."""

    __tablename__ = "match_squads"

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, nullable=False)
    player_id = Column(Integer, nullable=False)
    team_id = Column(Integer, nullable=False)  # which team this player belongs to
    is_substitute = Column(Boolean, nullable=False, default=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class PlayingXI(Base):
    """Selected playing XI for a match."""

    __tablename__ = "playing_xi"

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, nullable=False)
    player_id = Column(Integer, nullable=False)
    team_id = Column(Integer, nullable=False)
    is_captain = Column(Boolean, nullable=False, default=False)
    is_wicketkeeper = Column(Boolean, nullable=False, default=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class Toss(Base):
    """Online toss (heads/tails) before first ball.

    Two-phase:
    1. CALL: initiator calls heads or tails
    2. FLIP: system determines coin result, winner team derived from call vs result
    """

    __tablename__ = "toss"

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, nullable=False)
    initiator_call = Column(String(10), nullable=True)  # heads or tails called
    coin_result = Column(String(10), nullable=True)  # heads or tails actual result
    winner_team_id = Column(Integer, nullable=True)  # team decided by call vs result
    toss_decision = Column(
        String(10), nullable=True
    )  # bat or field chosen by winning team
    called_by_session_id = Column(
        String(36), nullable=True
    )  # session that called the toss
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class FormatConfig(Base):
    """Format configuration (T20, ODI, Test, Custom)."""

    __tablename__ = "format_configs"

    id = Column(Integer, primary_key=True, index=True)
    format_name = Column(String(20), nullable=False, unique=True)  # T20, ODI, Test, Custom
    overs_per_innings = Column(Integer, nullable=False, default=20)
    balls_per_over = Column(Integer, nullable=False, default=6)
    max_overs_per_bowler = Column(Integer, nullable=False, default=4)  # T20: 4, ODI: 10, Test: unlimited
    free_hit_after_no_ball = Column(Boolean, nullable=False, default=True)  # T20: yes, ODI: yes, Test: yes
    powerplay_max_overs = Column(Integer, nullable=True)  # T20: 6 overs, ODI: 30 overs, Test: N/A
    new_ball_every_overs = Column(
        Integer, nullable=True
    )  # Test: 80 overs
    follow_on_threshold = Column(
        Integer, nullable=True
    )  # Test: 200
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

class Ball(Base):
    """Individual delivery record in a match."""

    __tablename__ = "balls"

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, nullable=False)
    innings_id = Column(Integer, nullable=False)  # ball belongs to a specific innings
    over_number = Column(Integer, nullable=False)  # current over number
    ball_number = Column(Integer, nullable=False)  # 1-6 within the over
    striker_id = Column(Integer, nullable=False)  # player_id of striker
    non_striker_id = Column(Integer, nullable=False)  # player_id of non-striker
    bowler_id = Column(Integer, nullable=False)  # player_id of bowler
    runs_batter = Column(Integer, nullable=False, default=0)  # runs scored by batter
    runs_extras = Column(Integer, nullable=False, default=0)  # wides, no-balls, byes, leg-byes, penalties
    extra_type = Column(
        String(10), nullable=True
    )  # nb / wd / bye / legbye / penalty / None (valid ball)
    penalty_runs = Column(
        Integer, nullable=False, default=0
    )  # separate from runs_extras for accounting
    is_wicket = Column(Boolean, nullable=False, default=False)
    dismissal_mode = Column(
        String(20), nullable=True
    )  # bowled / caught / lbw / run_out / stumped / etc.
    fielder_id = Column(Integer, nullable=True)  # player_id who took the catch / runout
    short_runs = Column(Integer, nullable=False, default=0)  # short run penalty (leg-bye style)
    boundary_type = Column(
        String(2), nullable=True
    )  # 4 / 6 / None
    is_free_hit = Column(Boolean, nullable=False, default=False)  # free hit after no ball
    is_valid_ball = Column(Boolean, nullable=False, default=True)  # is this a valid ball toward over count
    is_over_completed = Column(Boolean, nullable=False, default=False)  # marks end of an over
    is_shot_out = Column(Boolean, nullable=False, default=False)  # whether batter got out on this ball
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class AuditLog(Base):
    """Audit log entry for authorization and security events.

    Records every scoring-rights change, match lock/unlock,
    ownership transfer, and other security-relevant actions.
    """

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    actor_session_id = Column(String(36), nullable=False)
    action = Column(String(50), nullable=False)
    match_id = Column(Integer, nullable=True, index=True)
    target_id = Column(String(50), nullable=True)
    timestamp = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    details = Column(Text, nullable=True)


class MVP(Base):
    """Most Valuable Player award for a match.

    Records which player was awarded MVP for a match,
    along with points breakdown and who awarded it.
    """

    __tablename__ = "mvp"

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, nullable=False, index=True)  # match this MVP belongs to
    player_id = Column(Integer, nullable=False)  # player_id of MVP winner
    points = Column(Integer, nullable=False, default=0)  # total points scored
    reason_summary = Column(Text, nullable=True)  # human-readable reason
    awarded_by_session_id = Column(String(36), nullable=False)  # session that awarded
    awarded_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class Innings(Base):
    """Innings model tracking an innings within a match."""

    __tablename__ = "innings"

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, nullable=False, index=True)
    innings_number = Column(Integer, nullable=False)  # 1, 2, 3, 4
    batting_team_id = Column(Integer, nullable=True)
    bowling_team_id = Column(Integer, nullable=True)
    target_runs = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="in_progress")  # in_progress, completed
    total_runs = Column(Integer, nullable=False, default=0)
    total_wickets = Column(Integer, nullable=False, default=0)
    overs_bowled = Column(String(10), nullable=False, default="0.0")
    result = Column(String(50), nullable=True)
    result_margin = Column(String(100), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class Over(Base):
    """Over model tracking an individual over."""

    __tablename__ = "overs"

    id = Column(Integer, primary_key=True, index=True)
    innings_id = Column(Integer, nullable=False, index=True)
    over_number = Column(Integer, nullable=False)
    bowler_id = Column(Integer, nullable=False)
    end = Column(String(50), nullable=True)  # pavilion end, etc.
    balls_valid = Column(Integer, nullable=False, default=0)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class Wicket(Base):
    """Wicket model tracking individual dismissals and fall of wickets."""

    __tablename__ = "wickets"

    id = Column(Integer, primary_key=True, index=True)
    ball_id = Column(Integer, nullable=False, index=True)
    dismissal_mode = Column(String(30), nullable=False)
    batter_out_id = Column(Integer, nullable=False)
    fielder_id = Column(Integer, nullable=True)
    bowler_credit_id = Column(Integer, nullable=True)
    not_out_batter_id = Column(Integer, nullable=True)
    runs_at_fall = Column(Integer, nullable=False, default=0)
    over_at_fall = Column(String(10), nullable=False, default="0.0")
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class ScoreSnapshot(Base):
    """Point-in-time snapshot of the scorecard for audit and recovery."""

    __tablename__ = "score_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, nullable=False, index=True)
    generated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    payload_json = Column(Text, nullable=False)
    checksum = Column(String(64), nullable=False)

