"""The distributable Shortcut must ask for instance details at import time."""

import plistlib
from pathlib import Path


def test_public_shortcut_routes_native_requests_through_imported_settings():
    root = Path(__file__).resolve().parents[1]
    workflow = plistlib.loads((root / "shortcuts/Shizhang-OCR-public.plist").read_bytes())
    actions = workflow["WFWorkflowActions"]
    questions = workflow["WFWorkflowImportQuestions"]
    assert len(questions) == 4
    config = {}
    for question in questions:
        action = actions[question["ActionIndex"]]
        assert action["WFWorkflowActionIdentifier"] == "is.workflow.actions.gettext"
        assert question["ParameterKey"] == "WFTextActionText"
        params = action["WFWorkflowActionParameters"]
        config[params["CustomOutputName"]] = params
    assert set(config) == {"server", "email", "ledger", "password"}
    assert all(p["WFTextActionText"] == "" for p in config.values())

    requests = [a["WFWorkflowActionParameters"] for a in actions
                if a["WFWorkflowActionIdentifier"] == "is.workflow.actions.downloadurl"]
    assert len(requests) == 3
    for request, path in zip(requests, ("auth/login", "ai/record-ocr-text", "auth/logout")):
        assert request["WFHTTPMethod"] == "POST"
        assert request["WFHTTPBodyType"] == "JSON"
        url = request["WFURL"]
        assert url["WFSerializationType"] == "WFTextTokenString"
        assert url["Value"]["string"] == "\ufffc/api/v1/" + path
        refs = list(url["Value"]["attachmentsByRange"].values())
        assert len(refs) == 1
        assert refs[0]["OutputUUID"] == config["server"]["UUID"]

    def fields(request):
        return {item["WFKey"]["Value"]["string"]: item["WFValue"]["Value"]
                for item in request["WFJSONValues"]["Value"]["WFDictionaryFieldValueItems"]}

    def reference(value):
        refs = list(value["attachmentsByRange"].values())
        assert len(refs) == 1
        return refs[0]["OutputUUID"]

    login, record = fields(requests[0]), fields(requests[1])
    assert reference(login["email"]) == config["email"]["UUID"]
    assert reference(login["password"]) == config["password"]["UUID"]
    assert reference(record["ledger_id"]) == config["ledger"]["UUID"]
    assert {"text", "image_base64", "request_id", "submitted_at"} <= record.keys()
    # Screenshot and OCR still run first; settings change no capture semantics.
    assert actions[0]["WFWorkflowActionIdentifier"] == "is.workflow.actions.takescreenshot"
    assert actions[1]["WFWorkflowActionIdentifier"] == "is.workflow.actions.extracttextfromimage"
