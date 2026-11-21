"""Test configuration and fixtures for Cric-Scorer."""

import os
import sys
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set test database URL before importing app modules
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.database import Base, engine as app_engine, session_local as app_session_local  # noqa: E402
from app.main import app  # noqa: E402


# Override the app engine with a test in-memory engine
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
)

TestSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=test_engine
)


def get_test_session_local():
    return TestSessionLocal


# Create all tables
Base.metadata.create_all(bind=test_engine)


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test."""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="function")
def client(db_session):
    """Create a TestClient with overridden database session."""
    def override_get_session_local():
        return get_test_session_local

    app.dependency_overrides = {}
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def test_session(db_session):
    """Create an anonymous test session."""
    from app.database import AnonymousSession
    session = AnonymousSession(
        session_id="test_session_123",
        device_name="Test Device",
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    return session


@pytest.fixture
def test_match(db_session, test_session):
    """Create a test match."""
    from app.database import Match, MatchRole
    match = Match(
        name="Test Match",
        team_a_name="Team A",
        team_b_name="Team B",
        format="T20",
        overs_per_innings=5,
        balls_per_over=6,
        status="created",
        initiator_session_id=test_session.session_id,
    )
    db_session.add(match)
    db_session.commit()
    db_session.refresh(match)

    # Assign initiator role
    role = MatchRole(
        match_id=match.id,
        session_id=test_session.session_id,
        role="initiator",
        scoring_rights=True,
    )
    db_session.add(role)
    db_session.commit()
    return match


@pytest.fixture
def test_players(db_session, test_match):
    """Create test players for a match."""
    from app.database import MatchSquad, Player
    players = []
    for i in range(11):
        player = Player(
            match_id=test_match.id,
            team_id=1 if i < 6 else 2,
            name=f"Player {i+1}",
            role="batsman" if i < 5 else "bowler",
            jersey_number=i + 1,
            is_substitute=False,
        )
        db_session.add(player)
        players.append(player)

    db_session.commit()
    for p in players:
        db_session.refresh(p)

    # Add to squads
    for p in players:
        squad = MatchSquad(
            match_id=test_match.id,
            player_id=p.id,
            team_id=p.team_id,
            is_substitute=False,
        )
        db_session.add(squad)

    db_session.commit()
    return players


@pytest.fixture
def auth_headers(test_session):
    """Return auth headers with session cookie."""
    return {"Cookie": f"session_id={test_session.session_id}"}