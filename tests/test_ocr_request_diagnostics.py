"""Invalid OCR requests expose field/type diagnostics without bill contents."""
import logging

import pytest
from pydantic import ValidationError

from src.routers.ai.parse_tx_text import RecordOcrTextRequest


@pytest.mark.parametrize('field', ['captured_at', 'submitted_at'])
def test_invalid_clock_is_rejected_and_only_field_and_type_are_logged(field, caplog):
    secret = 'PRIVATE-OCR-CONTENT-NOT-FOR-LOGGING'
    with caplog.at_level(logging.WARNING), pytest.raises(ValidationError):
        RecordOcrTextRequest.model_validate({
            'text': secret, 'ledger_id': 'ledger-private-marker', field: secret,
        })
    messages = '\n'.join(r.getMessage() for r in caplog.records)
    assert 'ocr.record.validation_rejected' in messages
    assert field in messages and 'datetime_from_date_parsing' in messages
    assert secret not in messages and 'ledger-private-marker' not in messages


def test_invalid_operation_logs_the_field_without_the_rejected_value(caplog):
    with caplog.at_level(logging.WARNING), pytest.raises(ValidationError):
        RecordOcrTextRequest.model_validate({
            'text': 'PRIVATE-RECEIPT-TEXT', 'ledger_id': 'ledger-private-marker',
            'request_id': 'PRIVATE INVALID ID!',
        })
    messages = '\n'.join(r.getMessage() for r in caplog.records)
    assert 'request_id' in messages and 'string_pattern_mismatch' in messages
    assert 'PRIVATE' not in messages and 'ledger-private-marker' not in messages


def test_valid_request_keeps_clock_and_does_not_emit_rejection(caplog):
    with caplog.at_level(logging.WARNING):
        model = RecordOcrTextRequest.model_validate({
            'text': 'SYNTHETIC', 'ledger_id': 'ledger-synthetic',
            'submitted_at': '2026-10-17T22:20:00+08:00',
        })
    assert model.submitted_at.utcoffset().total_seconds() == 28800
    assert not any('ocr.record.validation_rejected' in r.getMessage() for r in caplog.records)
