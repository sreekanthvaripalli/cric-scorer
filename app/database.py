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
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )