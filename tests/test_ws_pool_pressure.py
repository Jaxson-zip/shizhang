"""WebSocket authentication must not stall all HTTP traffic under DB pressure."""
import asyncio
from time import monotonic
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models import User
from src.routers import ws
from src.security import SCOPE_APP_WRITE, create_access_token
from src.websocket_manager import WSConnectionManager


def test_ws_pool_wait_does_not_block_event_loop(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "pool.db"),
        connect_args={"check_same_thread": False},
        pool_size=1, max_overflow=0, pool_timeout=0.4,
    )
    monkeypatch.setattr(ws, "SessionLocal", sessionmaker(bind=engine))
    token, _ = create_access_token("synthetic-user", scopes=[SCOPE_APP_WRITE], client_type="app")
    closed = []

    class Socket:
        app = SimpleNamespace(state=SimpleNamespace())

        async def close(self, code):
            closed.append(code)

    async def scenario():
        start = monotonic()
        heartbeat_at = []

        async def heartbeat():
            await asyncio.sleep(0.01)
            heartbeat_at.append(monotonic() - start)

        results = await asyncio.gather(ws.websocket_endpoint(Socket(), token), heartbeat(), return_exceptions=True)
        assert heartbeat_at[0] < 0.25, "DB pool wait blocked the event loop and unrelated HTTP traffic"
        assert not any(isinstance(result, Exception) for result in results)
        assert closed == [1013], "Temporary DB pressure must refuse the handshake without an ASGI 500"

    try:
        with engine.connect():  # Exhaust the real native SQLAlchemy pool.
            asyncio.run(scenario())
        assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("registered", [True, False])
def test_ws_auth_releases_connection_and_preserves_ping(tmp_path, monkeypatch, registered):
    engine = create_engine("sqlite:///" + str(tmp_path / "auth.db"), connect_args={"check_same_thread": False}, pool_size=1, max_overflow=0)
    User.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(ws, "SessionLocal", factory)
    if registered:
        with factory() as db:
            db.add(User(id="synthetic-user", email="ws@example.invalid", password_hash="unused"))
            db.commit()
    token, _ = create_access_token("synthetic-user", scopes=[SCOPE_APP_WRITE], client_type="app")
    manager = WSConnectionManager()

    class Socket:
        app = SimpleNamespace(state=SimpleNamespace(ws_manager=manager))

        def __init__(self):
            self.accepted = False
            self.closed = None
            self.sent = []
            self.received = 0

        async def accept(self):
            self.accepted = True
            assert engine.pool.checkedout() == 0

        async def close(self, code):
            self.closed = code

        async def receive_text(self):
            self.received += 1
            assert engine.pool.checkedout() == 0
            if self.received == 1:
                return '{"type":"ping"}'
            raise RuntimeError("Synthetic peer disconnected")

        async def send_text(self, text):
            self.sent.append(text)

    try:
        peer = Socket()
        asyncio.run(ws.websocket_endpoint(peer, token))
        assert peer.accepted is registered
        assert peer.closed == (None if registered else 1008)
        assert peer.sent == (['{"type":"pong"}'] if registered else [])
        assert not list(manager.online_user_ids())
        assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()
