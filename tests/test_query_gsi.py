"""The dashboard's per-type reads must hit the type-ts GSI via Query, not Scan."""
import importlib
import os
import sys

os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("TABLE_NAME", "unit-test-table")
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, "query"))


def _load_handler():
    return importlib.import_module("query.handler")


class _SpyTable:
    """Records the kwargs of the last query/scan call."""

    def __init__(self):
        self.query_kwargs = None
        self.scan_kwargs = None

    def query(self, **kwargs):
        self.query_kwargs = kwargs
        return {"Items": []}

    def scan(self, **kwargs):
        self.scan_kwargs = kwargs
        return {"Items": []}


def test_type_param_queries_the_gsi_not_scan(monkeypatch):
    handler = _load_handler()
    spy = _SpyTable()
    monkeypatch.setattr(handler, "table", spy)

    response = handler.lambda_handler(
        {"queryStringParameters": {"type": "temp", "limit": "50"}}, None
    )

    assert response["statusCode"] == 200
    assert spy.scan_kwargs is None, "type-filtered read must not Scan"
    assert spy.query_kwargs is not None
    assert spy.query_kwargs["IndexName"] == handler.TYPE_TS_INDEX
    assert spy.query_kwargs["ScanIndexForward"] is False
    assert spy.query_kwargs["Limit"] == 50


def test_no_device_and_no_type_still_scans(monkeypatch):
    handler = _load_handler()
    spy = _SpyTable()
    monkeypatch.setattr(handler, "table", spy)

    handler.lambda_handler({"queryStringParameters": {"limit": "10"}}, None)

    assert spy.query_kwargs is None
    assert spy.scan_kwargs is not None
