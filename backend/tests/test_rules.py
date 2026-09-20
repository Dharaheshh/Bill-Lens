from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.rules import apply_rules
from app.schemas import ExtractedBill, MatchedLine, ResolvedPolicy


@pytest.mark.asyncio
async def test_rules():
    bill = ExtractedBill(lines=[], stated_total=1000, estimate_amount=500)
    lines = [
        MatchedLine(line_no=1, raw_text="X", amount=200, qty=2, unit_price=100), # OK
        MatchedLine(line_no=2, raw_text="Y", amount=300, qty=2, unit_price=100), # R1 fail
        MatchedLine(line_no=3, raw_text="Z", amount=100, canonical_name="Z", service_date=None), 
        MatchedLine(line_no=4, raw_text="Z", amount=100, canonical_name="Z", service_date=None) # R2 fail
    ]
    policy = ResolvedPolicy(is_insured=True)
    
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value.scalars.return_value = [] # Mock catalog
    
    findings, evidence = await apply_rules(session, bill, lines, policy)
    
    rule_codes = [f.rule_code for f in findings]
    assert "R1" in rule_codes # Arithmetic error
    assert "R2" in rule_codes # Duplicate
    assert "R6" in rule_codes # Estimate variance (1000 > 500 * 1.2)
