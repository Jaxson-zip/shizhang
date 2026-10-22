"""Result-page missing facts are explicit user choices, never inferred payments."""
from datetime import datetime, timedelta, timezone

from test_ai_parse_tx import _make_client
from test_ocr_result_page import RESULT
from test_ocr_trigger import setup_trigger

from src.main import app


def test_result_page_requires_expense_time_confirmation_and_account_before_native_write():
    client = _make_client()
    try:
        headers, ledger, account, category, body = setup_trigger(client,'ocr-result-write@example.invalid')
        captured = datetime.now(timezone.utc).replace(microsecond=0)
        body.update(text=RESULT,captured_at=captured.isoformat())
        endpoint = '/api/v1/ai/record-ocr-text'
        first = client.post(endpoint,headers=headers,json=body)
        assert first.status_code == 422
        choices = first.json()['shortcut_choices']
        assert choices['confirm_capture_time'] is True and choices['confirm_result_expense'] is True
        assert choices['confirmation_required'] is True
        assert '截图时间' in choices['summary'] and '.02' in choices['summary']
        rows_path = '/api/v1/read/ledgers/'+ledger+'/transactions'
        assert client.get(rows_path,headers=headers).json() == []
        chosen = {**body,'account_id':account,'category_id':category,'confirm_result_expense':True}
        still_pending = client.post(endpoint,headers=headers,json=chosen)
        assert still_pending.status_code == 422 and client.get(rows_path,headers=headers).json() == []
        chosen['confirm_capture_time'] = True
        saved = client.post(endpoint,headers=headers,json=chosen)
        assert saved.status_code == 200, saved.text
        replay = client.post(endpoint,headers=headers,json=chosen)
        assert replay.status_code == 200 and replay.json()['entity_id'] == saved.json()['entity_id']
        rows = client.get(rows_path,headers=headers).json()
        assert len(rows) == 1 and rows[0]['amount'] == .02 and rows[0]['account_id'] == account
        assert datetime.fromisoformat(rows[0]['happened_at'].replace('Z','+00:00')) == captured
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_result_without_capture_timestamp_keeps_legacy_review_and_old_capture_is_not_used():
    client = _make_client()
    try:
        headers, ledger, account, category, body = setup_trigger(client,'ocr-result-clock@example.invalid')
        body.update(text=RESULT,account_id=account,category_id=category,confirm_result_expense=True,confirm_capture_time=True)
        endpoint = '/api/v1/ai/record-ocr-text'
        for captured in (None,(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()):
            request = {**body,**({'captured_at':captured} if captured else {})}
            response = client.post(endpoint,headers=headers,json=request)
            assert response.status_code == 422 and 'shortcut_choices' not in response.json()
        naive = client.post(endpoint,headers=headers,json={**body,'captured_at':'2026-10-17T16:33:00'})
        assert naive.status_code == 422
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions',headers=headers).json() == []
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_explicit_payment_time_is_preserved_and_capture_time_does_not_replace_it():
    client = _make_client()
    try:
        headers, ledger, account, category, body = setup_trigger(client,'ocr-result-explicit-time@example.invalid')
        payment = datetime.now(timezone.utc).replace(microsecond=0)-timedelta(minutes=3)
        captured = payment+timedelta(minutes=3)
        body.update(text=RESULT+'\n支付时间\n'+payment.isoformat(),captured_at=captured.isoformat(),
                    account_id=account,category_id=category,confirm_capture_time=True)
        endpoint = '/api/v1/ai/record-ocr-text'
        pending = client.post(endpoint,headers=headers,json=body)
        assert pending.status_code == 422 and pending.json()['shortcut_choices']['confirm_result_expense'] is True
        assert pending.json()['shortcut_choices']['confirm_capture_time'] is False
        saved = client.post(endpoint,headers=headers,json={**body,'confirm_result_expense':True})
        assert saved.status_code == 200, saved.text
        rows = client.get('/api/v1/read/ledgers/'+ledger+'/transactions',headers=headers).json()
        assert len(rows) == 1 and datetime.fromisoformat(rows[0]['happened_at'].replace('Z','+00:00')) == payment
    finally:
        client.close()
        app.dependency_overrides.clear()
