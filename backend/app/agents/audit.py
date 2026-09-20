"""
Audit Agent: investigates uncertain lines with bounded tool loop (SPEC §8.3).
Max 10 lines, max 6 steps per line, semaphore 4.
"""
import asyncio
import json
import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import LLMUnavailable, llm_client
from app.orchestrator.events import RunContext
from app.schemas import Finding, MatchedLine
from app.tools.bill_tools import find_duplicates, get_line_context
from app.tools.catalog_tools import lookup_reference_price, search_catalog

logger = logging.getLogger(__name__)

_SEM = asyncio.Semaphore(4)

AUDIT_SYSTEM = """You are a careful hospital-bill investigator. A rules engine has already flagged this line or found it ambiguous.
Use the tools to gather evidence, then decide: confirm (flag stands), dismiss (probably legitimate), or ask (question for patient).
Return ONLY JSON: {"line_no":int,"verdict":"confirm"|"dismiss"|"ask","rationale":"≤280 chars","evidence_ids":["E1",...],"suggested_question":"..."|null}
Rules:
- cite only evidence IDs returned by your own tool calls in this session
- do not state any rupee figure not in the evidence
- use hedged language: "may", "worth asking", "questionable"
- never accuse the hospital of wrongdoing
- you cannot change amounts or severities"""

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_catalog",
            "description": "Search the medical service catalogue by name",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "k": {"type": "integer", "default": 5}}, "required": ["query"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_duplicates",
            "description": "Find duplicate lines for the given line number",
            "parameters": {"type": "object", "properties": {"line_no": {"type": "integer"}}, "required": ["line_no"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_reference_price",
            "description": "Get reference price range for a catalog item",
            "parameters": {"type": "object", "properties": {"catalog_id": {"type": "integer"}}, "required": ["catalog_id"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_line_context",
            "description": "Get context for a line including baseline findings and same-date neighbors",
            "parameters": {"type": "object", "properties": {"line_no": {"type": "integer"}}, "required": ["line_no"]},
        },
    },
]


def _validate_proposal(proposal: dict, line: MatchedLine, existing_findings: list[Finding], ctx: RunContext) -> dict | None:
    """Validate audit agent proposal per I3/I4."""
    ev_ids = proposal.get("evidence_ids", [])
    valid_ids = ctx.evidence.get_ids()

    # Drop uncited IDs
    valid_ev = [eid for eid in ev_ids if eid in valid_ids]
    if not valid_ev:
        logger.warning("Audit proposal for line %d has no valid evidence IDs", line.line_no)
        return None

    # Validate numbers in rationale are in evidence
    rationale = proposal.get("rationale", "")
    numbers_in_rationale = set(re.findall(r"\d[\d,\.]*", rationale))
    if numbers_in_rationale:
        evidence_texts = " ".join((ctx.evidence.get_by_id(eid).text if ctx.evidence.get_by_id(eid) else "") for eid in valid_ev)
        line_data = f"{line.amount} {line.qty or ''} {line.unit_price or ''}"
        allowed_nums = set(re.findall(r"\d[\d,\.]*", evidence_texts + " " + line_data))
        bad = numbers_in_rationale - allowed_nums
        if bad:
            logger.warning("Audit proposal for line %d has uncited numbers: %s", line.line_no, bad)
            # Soft fail: remove bad numbers from rationale by masking them
            for n in bad:
                rationale = rationale.replace(n, "[amount]")

    return {**proposal, "evidence_ids": valid_ev, "rationale": rationale}


def _merge_proposal(
    proposal: dict,
    line: MatchedLine,
    findings: list[Finding],
    ctx: RunContext,
) -> list[Finding]:
    """Merge validated audit proposal into findings per I4 rules."""
    verdict = proposal.get("verdict")
    line_no = proposal.get("line_no", line.line_no)
    rationale = proposal.get("rationale", "")
    ev_ids = proposal.get("evidence_ids", [])
    question = proposal.get("suggested_question")

    new_findings = list(findings)


    if verdict == "confirm":
        # Attach agent note and evidence to existing findings (severity unchanged)
        for f in new_findings:
            if line_no in f.line_ids:
                f.agent_note = rationale
                f.evidence_ids = list(set(f.evidence_ids + ev_ids))
    elif verdict == "dismiss":
        # Only dismiss amber findings (never red)
        for f in new_findings:
            if line_no in f.line_ids and f.severity == "amber":
                f.dismissed = True
                f.severity = "info"
                f.agent_note = rationale
    elif verdict == "ask":
        # Create new A1 amber finding
        import uuid
        new_id = f"F-A1-{uuid.uuid4().hex[:8]}"
        new_findings.append(Finding(
            id=new_id,
            rule_code="A1",
            kind="billing",
            severity="amber",
            origin="agent",
            line_ids=[line_no],
            title="Worth Asking About",
            explanation=rationale,
            amount_at_stake=None,
            confidence="low",
            evidence_ids=ev_ids,
            suggested_question=question,
        ))

    return new_findings


async def _investigate_line(
    session: AsyncSession,
    line: MatchedLine,
    all_lines: list[MatchedLine],
    findings: list[Finding],
    policy_terms: dict,
    ctx: RunContext,
) -> dict | None:
    """Run the audit tool loop for one uncertain line."""
    async with _SEM:
        ctx.emit("audit", "stage_start", f"Investigating line {line.line_no}: {line.raw_text[:40]}")

        payload = {
            "line": line.model_dump(),
            "baseline_findings": [f.model_dump() for f in findings if line.line_no in f.line_ids],
            "confirmed_policy_terms": policy_terms,
        }

        msgs = [
            {"role": "system", "content": AUDIT_SYSTEM},
            {"role": "user", "content": json.dumps(payload, default=str)},
        ]

        # Tool dispatch map
        async def call_tool(name: str, args: dict):
            if name == "search_catalog":
                return await search_catalog(session, **args)
            if name == "find_duplicates":
                return await find_duplicates([l.model_dump() for l in all_lines], **args)
            if name == "lookup_reference_price":
                return await lookup_reference_price(session, **args)
            if name == "get_line_context":
                return await get_line_context([l.model_dump() for l in all_lines], [f.model_dump() for f in findings], **args)
            return None

        for step in range(6):
            try:
                resp = await llm_client.chat(msgs, role="agent", tools=TOOL_DEFINITIONS, temperature=0)
                ctx.emit("audit", "llm_call", f"Audit step {step + 1} for line {line.line_no}")
            except LLMUnavailable:
                ctx.emit("audit", "warning", f"LLM unavailable for line {line.line_no}")
                return None

            if resp.tool_calls:
                msgs.append({"role": "assistant", "content": resp.text or "", "tool_calls": [
                    {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])}}
                    for tc in resp.tool_calls
                ]})
                for call in resp.tool_calls:
                    ctx.emit("audit", "tool_call", f"{call['name']}({str(call['args'])[:60]})", data=call["args"])
                    result = await call_tool(call["name"], call["args"])
                    if result:
                        ids = ctx.evidence.add(result.evidence)
                        ctx.emit("audit", "tool_result", result.summary, data={"evidence_ids": ids})
                        msgs.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result.data, default=str)})
            else:
                try:
                    text = resp.text.strip()
                    if text.startswith("```"):
                        text = "\n".join(text.split("\n")[1:-1])
                    proposal = json.loads(text)
                    validated = _validate_proposal(proposal, line, findings, ctx)
                    ctx.emit("audit", "validation", f"Proposal for line {line.line_no}: {proposal.get('verdict')}")
                    return validated
                except Exception as e:  # noqa: BLE001
                    logger.warning("Audit parse failed at step %d: %s", step, e)
                    msgs.append({"role": "user", "content": "Return ONLY valid JSON as specified."})

        return None


async def run_audit_agent(
    session: AsyncSession,
    lines: list[MatchedLine],
    findings: list[Finding],
    policy_terms: dict,
    ctx: RunContext,
) -> list[Finding]:
    """Run Audit Agent on the uncertain set. Returns merged findings."""
    # Build uncertain set: R2 pharmacy, R4 bundled, unmatched/llm with amount ≥ 500
    uncertain_line_nos = set()
    for f in findings:
        if f.uncertain and not f.dismissed:
            uncertain_line_nos.update(f.line_ids)

    for line in lines:
        if line.match_method in ("llm", "unmatched") and line.amount >= 500:
            uncertain_line_nos.add(line.line_no)

    # Sort by amount desc, cap at 10
    uncertain_lines = sorted(
        [l for l in lines if l.line_no in uncertain_line_nos],
        key=lambda x: x.amount,
        reverse=True,
    )[:10]

    if not uncertain_lines:
        ctx.emit("audit", "stage_start", "Audit Agent: no uncertain lines")
        ctx.emit("audit", "stage_end", "Audit Agent: nothing to investigate")
        return findings

    ctx.emit("audit", "stage_start", f"Audit Agent: investigating {len(uncertain_lines)} uncertain lines")

    tasks = [
        _investigate_line(session, line, lines, findings, policy_terms, ctx)
        for line in uncertain_lines
    ]
    proposals = await asyncio.gather(*tasks, return_exceptions=True)

    updated_findings = list(findings)
    for line, proposal in zip(uncertain_lines, proposals):
        if isinstance(proposal, Exception):
            logger.warning("Audit for line %d raised: %s", line.line_no, proposal)
            continue
        if proposal:
            updated_findings = _merge_proposal(proposal, line, updated_findings, ctx)

    ctx.emit("audit", "stage_end", f"Audit Agent: processed {len(uncertain_lines)} lines")
    return updated_findings
