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
)
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()
session_local = scoped_session(sessionmaker(autocommit=False, autoflush=False))


def get_session_local():
    return session_local


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
        DateTime(timezone=True), nullable=False
    )  # when approval happened

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
    team_id = Column(Integer, nullable=False)  # foreign key to teams.id
    name = Column(String(150), nullable=False)  # player name
    role = Column(
        String(20),
        nullable=False,
        default="all-rounder",  # batter / bowler / all-rounder / wicketkeeper
    )
    jersey_number = Column(Integer, nullable=True)  # 1-11 for the XI
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
