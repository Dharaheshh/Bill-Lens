import json
import os

from app import schemas


def test_schema_instantiation():
    # Verify we can instantiate a finding
    f = schemas.Finding(
        id="F1",
        rule_code="R1",
        kind="billing",
        severity="red",
        origin="rule",
        title="Test",
        explanation="Test finding",
        confidence="high"
    )
    assert f.severity == "red"

def test_fixture_loading():
    path = os.path.join(os.path.dirname(__file__), "fixtures", "golden", "sample-a.expected.json")
    assert os.path.exists(path)
    with open(path, 'r') as file:
        data = json.load(file)
        assert "billed_total" in data

def test_catalog_count():
    path = os.path.join(os.path.dirname(__file__), "..", "app", "seed", "catalog.csv")
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            assert len(lines) > 180, "Catalog should have ~200 items"

def test_openapi_contract():
    from app.main import app
    schema = app.openapi()
    assert "RunResult" in schema["components"]["schemas"]
    assert "Finding" in schema["components"]["schemas"]
