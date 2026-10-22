"""User-selected policy: a simple result page uses this operation's submit time."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from test_ai_parse_tx import _make_client
from test_ocr_result_page import RESULT
from test_ocr_trigger import setup_trigger

from src.main import app


def test_simple_result_uses_fixed_submit_time_without_reconfirming_time_and_replays_one_run():
    client = _make_client()
    try:
        headers, ledger, account, category, body = setup_trigger(client,'ocr-submit-time@example.invalid')
        submitted = datetime.now(timezone.utc).replace(microsecond=0)
        body.update(text=RESULT,submitted_at=submitted.isoformat(),result_time_policy='submission',
                    account_id=account,category_id=category)
        endpoint = '/api/v1/ai/record-ocr-text'
        first = client.post(endpoint,headers=headers,json=body)
        assert first.status_code == 200, first.text
        replay = client.post(endpoint,headers=headers,json=body)
        assert replay.status_code == 200 and replay.json()['entity_id'] == first.json()['entity_id']
        next_run = client.post(endpoint,headers=headers,json={**body,'request_id':str(uuid4())})
        assert next_run.status_code == 200 and next_run.json()['entity_id'] != first.json()['entity_id']
        rows = client.get('/api/v1/read/ledgers/'+ledger+'/transactions',headers=headers).json()
        assert len(rows) == 2
        assert all(datetime.fromisoformat(r['happened_at'].replace('Z','+00:00'))==submitted for r in rows)
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_missing_account_asks_only_for_dictionary_choice_not_time_confirmation():
    client = _make_client()
    try:
        headers, ledger, account, category, body = setup_trigger(client,'ocr-submit-account@example.invalid')
        submitted = datetime.now(timezone.utc).replace(microsecond=0)
        body.update(text=RESULT,submitted_at=submitted.isoformat(),result_time_policy='submission')
        endpoint = '/api/v1/ai/record-ocr-text'
        pending = client.post(endpoint,headers=headers,json=body)
        assert pending.status_code == 422
        choices = pending.json()['shortcut_choices']
        assert choices['confirmation_required'] is False and choices['confirm_capture_time'] is False
        assert choices['confirm_result_expense'] is False and '提交时间' in choices['summary']
        assert choices['account_ids'] == {'微信零钱':account}
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions',headers=headers).json() == []
        saved = client.post(endpoint,headers=headers,json={**body,'account_id':account,'category_id':category})
        assert saved.status_code == 200, saved.text
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_explicit_bill_time_keeps_priority_and_submission_policy_is_not_applied_to_other_missing_time():
    client = _make_client()
    try:
        headers, ledger, account, category, body = setup_trigger(client,'ocr-submit-explicit@example.invalid')
        original_text = body['text']
        submitted = datetime.now(timezone.utc).replace(microsecond=0)
        payment = submitted-timedelta(minutes=2)
        body.update(text=RESULT+'\n支付时间\n'+payment.isoformat(),submitted_at=submitted.isoformat(),
                    result_time_policy='submission',account_id=account,category_id=category)
        endpoint = '/api/v1/ai/record-ocr-text'
        saved = client.post(endpoint,headers=headers,json=body)
        assert saved.status_code == 200
        rows = client.get('/api/v1/read/ledgers/'+ledger+'/transactions',headers=headers).json()
        assert datetime.fromisoformat(rows[0]['happened_at'].replace('Z','+00:00')) == payment
        partial = {**body,'request_id':str(uuid4()),'text':'\n'.join(line for line in original_text.splitlines() if not line.startswith('交易时间'))}
        rejected = client.post(endpoint,headers=headers,json=partial)
        assert rejected.status_code == 422 and 'review_payload' in rejected.json()
        assert len(client.get('/api/v1/read/ledgers/'+ledger+'/transactions',headers=headers).json()) == 1
    finally:
        client.close()
        app.dependency_overrides.clear()


@pytest.mark.parametrize('stamp',[None,'2026-10-17T16:33:00','2020-01-01T16:33:00+08:00'])
def test_missing_naive_or_stale_submit_timestamp_falls_back_without_writing(stamp):
    client = _make_client()
    try:
        headers, ledger, account, category, body = setup_trigger(client,'ocr-submit-clock@example.invalid')
        body.update(text=RESULT,result_time_policy='submission',account_id=account,category_id=category)
        if stamp:
            body['submitted_at']=stamp
        response = client.post('/api/v1/ai/record-ocr-text',headers=headers,json=body)
        assert response.status_code == 422
        assert client.get('/api/v1/read/ledgers/'+ledger+'/transactions',headers=headers).json() == []
    finally:
        client.close()
        app.dependency_overrides.clear()
