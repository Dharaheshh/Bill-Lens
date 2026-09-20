import json
import os

from app.schemas import BillLine


def test_golden_floor():
    path = os.path.join(os.path.dirname(__file__), "fixtures", "golden", "sample-a.lines.json")
    with open(path, 'r') as f:
        data = json.load(f)
        
    lines = [BillLine(**l) for l in data]
    assert len(lines) == 5
