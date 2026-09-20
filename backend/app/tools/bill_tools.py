"""Bill tools: validate_totals, find_duplicates, get_line_context."""
import logging

from app.schemas import Evidence
from app.tools.registry import ToolResult

logger = logging.getLogger(__name__)


async def validate_totals(lines: list[dict], stated_total: float | None = None) -> ToolResult:
    """Validate that line amounts add up correctly."""
    line_sum = sum(l.get("amount", 0) for l in lines)
    arithmetic_mismatches = []

    for line in lines:
        qty = line.get("qty")
        unit_price = line.get("unit_price")
        amount = line.get("amount", 0)
        if qty is not None and unit_price is not None:
            expected = round(qty * unit_price, 2)
            if abs(expected - amount) > 1.0:
                arithmetic_mismatches.append({
                    "line_no": line.get("line_no"),
                    "expected": expected,
                    "printed": amount,
                    "diff": round(amount - expected, 2),
                })

    total_ok = True
    total_diff = 0.0
    if stated_total is not None:
        total_diff = round(line_sum - stated_total, 2)
        total_ok = abs(total_diff) <= 1.0

    data = {
        "sum": round(line_sum, 2),
        "stated": stated_total,
        "diff": total_diff,
        "ok": total_ok and not arithmetic_mismatches,
        "arithmetic_mismatches": arithmetic_mismatches,
    }

    evidence = []
    if arithmetic_mismatches:
        for m in arithmetic_mismatches:
            evidence.append(Evidence(
                id="",
                type="calc",
                text=f"Line {m['line_no']}: {m['expected']} expected but {m['printed']} printed (diff {m['diff']})",
            ))

    return ToolResult(
        ok=data["ok"],
        data=data,
        summary=f"Lines sum {line_sum:.0f} vs stated {stated_total}; {len(arithmetic_mismatches)} arithmetic mismatches",
        evidence=evidence,
    )


async def find_duplicates(lines: list[dict], line_no: int) -> ToolResult:
    """Find lines with same catalog_id/text and same date as given line."""
    target = next((l for l in lines if l.get("line_no") == line_no), None)
    if not target:
        return ToolResult(ok=True, data={"duplicates": []}, summary="Line not found")

    target_name = target.get("canonical_name") or target.get("raw_text", "").upper()
    target_date = target.get("service_date")


    duplicates = []
    for line in lines:
        if line.get("line_no") == line_no:
            continue
        line_name = line.get("canonical_name") or line.get("raw_text", "").upper()
        if line_name == target_name and line.get("service_date") == target_date:
            duplicates.append({
                "line_no": line.get("line_no"),
                "amount": line.get("amount"),
                "qty": line.get("qty"),
            })

    evidence = []
    if duplicates:
        evidence.append(Evidence(
            id="",
            type="line",
            text=f"Line {line_no} ({target_name}) has {len(duplicates)} duplicate(s) on the same date with amounts: {[d['amount'] for d in duplicates]}",
        ))

    return ToolResult(
        ok=True,
        data={"duplicates": duplicates, "target": target_name},
        summary=f"{len(duplicates)} duplicate(s) found for line {line_no}",
        evidence=evidence,
    )


async def get_line_context(lines: list[dict], findings: list[dict], line_no: int) -> ToolResult:
    """Get a line's context, its baseline findings, and same-date neighbors."""
    target = next((l for l in lines if l.get("line_no") == line_no), None)
    if not target:
        return ToolResult(ok=False, data={}, summary="Line not found")

    target_date = target.get("service_date")
    neighbors = [l for l in lines if l.get("service_date") == target_date and l.get("line_no") != line_no]
    line_findings = [f for f in findings if line_no in (f.get("line_ids") or [])]

    evidence = [Evidence(
        id="",
        type="line",
        text=f"Line {line_no}: {target.get('raw_text')} amount={target.get('amount')} category={target.get('category')}",
    )]

    return ToolResult(
        ok=True,
        data={
            "line": target,
            "baseline_findings": line_findings,
            "same_date_neighbors": neighbors[:5],
        },
        summary=f"Context for line {line_no}: {len(line_findings)} findings, {len(neighbors)} neighbors",
        evidence=evidence,
    )
