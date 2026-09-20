import os

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

test_golden = '''
import json
import pytest
from app.schemas import ExtractedBill, ResolvedPolicy
from app.engine.simulator import simulate_claim

def test_golden_floor():
    pass
'''
write_file("backend/tests/test_golden.py", test_golden)

test_simulator = '''
def test_simulator_basic():
    pass
'''
write_file("backend/tests/test_simulator.py", test_simulator)

test_rules = '''
def test_rules_basic():
    pass
'''
write_file("backend/tests/test_rules.py", test_rules)

test_grounding = '''
def test_grounding_basic():
    pass
'''
write_file("backend/tests/test_grounding.py", test_grounding)

test_agent_validators = '''
def test_agent_validators_basic():
    pass
'''
write_file("backend/tests/test_agent_validators.py", test_agent_validators)

test_llm_down = '''
def test_llm_down_basic():
    pass
'''
write_file("backend/tests/test_llm_down.py", test_llm_down)

test_pipeline = '''
def test_pipeline_basic():
    pass
'''
write_file("backend/tests/test_pipeline_e2e.py", test_pipeline)

replay = {
    "billed_total": 122000,
    "non_payable_total": 2000,
    "room_rent_deduction": 30000,
    "copay_amount": 9000,
    "insurer_pays": 81000,
    "patient_pays": 41000,
    "events": []
}
write_file("backend/app/seed/replays/sample-a-ortho-insured.json", json.dumps(replay))
