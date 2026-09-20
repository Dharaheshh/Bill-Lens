from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.normalizer import normalize_lines
from app.schemas import BillLine


@pytest.mark.asyncio
async def test_normalizer():
    lines = [BillLine(line_no=1, raw_text="ROOM RENT", amount=100)]
    session = AsyncMock(spec=AsyncSession)
    class MockResult:
        def scalars(self):
            class MockScalars:
                def first(self): return None
            return MockScalars()
        def first(self): return None

    session.execute.return_value = MockResult()
    
    res = await normalize_lines(session, lines)
    assert len(res) == 1
    assert res[0].raw_text == "ROOM RENT"
