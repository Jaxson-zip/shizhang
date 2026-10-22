"""Concurrent reads must not let post-commit ORM refresh block the ASGI loop."""
import asyncio
from time import monotonic

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from test_write_no_strict_base import _login_web, _register_app, _seed_snapshot

from src.database import Base, get_db
from src.main import app


def test_manual_writes_keep_loop_responsive_when_pool_is_contended(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'manual-pool.db'),
                           connect_args={'check_same_thread': False}, pool_size=2, max_overflow=0, pool_timeout=0.5)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    try:
        client = TestClient(app)
        owner = _register_app(client, 'manual-pool@example.invalid')
        _seed_snapshot(client, owner['access_token'], owner['device_id'], 'MANUAL_POOL')
        token = _login_web(client, 'manual-pool@example.invalid')['access_token']

        async def scenario():
            delays = []
            running = True

            async def heartbeat():
                while running:
                    start = monotonic()
                    await asyncio.sleep(0.01)
                    delays.append(monotonic() - start)

            task = asyncio.create_task(heartbeat())
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url='http://synthetic', headers={'Authorization': 'Bearer ' + token}) as api:
                requests = [api.get('/api/v1/read/ledgers/MANUAL_POOL') for _ in range(12)]
                requests += [api.post('/api/v1/write/ledgers/MANUAL_POOL/transactions', json={
                    'base_change_id': 0, 'tx_type': 'expense', 'amount': 1,
                    'happened_at': '2026-10-16T12:00:00Z',
                }, headers={'Idempotency-Key': 'pool-' + str(i)}) for i in range(4)]
                responses = await asyncio.gather(*requests)
            running = False
            await task
            assert max(delays) < 0.25, 'A pooled ORM refresh blocked unrelated ASGI work'
            assert all(r.status_code == 200 for r in responses), [r.status_code for r in responses]

        asyncio.run(scenario())
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
