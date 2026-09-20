"""
Action Agent: desk questions, checklist, query letter.
All ₹ amounts code-validated. Template fallback always available.
"""
import json
import logging
import re

from app.llm.client import LLMUnavailable, llm_client
from app.orchestrator.events import RunContext
from app.schemas import ActionPack, DeskQuestion, Finding, Letter, SimulatorResult, Summary

logger = logging.getLogger(__name__)

LETTER_TEMPLATE = """Dear Sir/Madam,

Subject: {subject}

I am writing to seek clarification regarding the hospital bill dated {bill_date} from {hospital_name}.

Upon reviewing the itemised bill, I have identified the following items that require clarification:

{items_table}

I kindly request:
1. A detailed explanation for each of the above items.
2. Itemised breakdowns wherever package charges have been applied.
3. Documentary evidence for any charges that are standard and non-negotiable.

I appreciate your cooperation in addressing these concerns at the earliest.

Yours sincerely,
[Patient Name]
[Date]"""

CHECKLIST_DEFAULT = [
    "Itemised bill with all charges broken down",
    "Discharge summary signed by treating doctor",
    "All investigation and lab reports",
    "Original pharmacy bills with prescriptions",
    "Policy document with claim form",
    "Photo ID (Aadhaar/PAN)",
    "Pre-authorization letter (if applicable)",
]


def _build_letter(hospital_name: str, bill_date: str, findings: list[Finding]) -> Letter:
    """Build a deterministic query letter from findings."""
    red_amber = [f for f in findings if f.severity in ("red", "amber") and not f.dismissed and f.amount_at_stake]
    red_amber.sort(key=lambda f: f.amount_at_stake or 0, reverse=True)

    rows = []
    for i, f in enumerate(red_amber[:10], 1):
        amount_str = f"₹{f.amount_at_stake:,.0f}" if f.amount_at_stake else "—"
        rows.append(f"{i}. {f.title} (₹{f.amount_at_stake:,.0f}) — {f.explanation[:100]}")

    subject = f"Query regarding hospital bill — {len(red_amber)} items require clarification"
    items_table = "\n".join(rows) if rows else "No specific items flagged."
    body = LETTER_TEMPLATE.format(
        subject=subject,
        bill_date=bill_date or "N/A",
        hospital_name=hospital_name or "the hospital",
        items_table=items_table,
    )
    return Letter(subject=subject, body=body, generated_by="template")


def _build_questions(findings: list[Finding]) -> list[DeskQuestion]:
    """Build desk questions from findings, ranked by amount_at_stake."""
    questions = []
    seen = set()
    flagged = [f for f in findings if f.severity in ("red", "amber") and not f.dismissed]
    flagged.sort(key=lambda f: f.amount_at_stake or 0, reverse=True)

    for i, f in enumerate(flagged[:8], 1):
        key = f.title
        if key in seen:
            continue
        seen.add(key)
        question = f.suggested_question or f"Please explain the charge for '{f.title}'"
        if f.amount_at_stake:
            question += f" (₹{f.amount_at_stake:,.0f})"
        questions.append(DeskQuestion(
            priority=i,
            question=question,
            why=f.explanation[:200],
            line_ids=f.line_ids,
            amount=f.amount_at_stake,
        ))
    return questions


def _validate_letter_numbers(polished: str, template: str) -> bool:
    """Check that the set of numbers in polished equals the set in template."""
    def extract_nums(text: str) -> set[str]:
        return set(re.findall(r"\d[\d,\.]*", text))

    return extract_nums(polished) == extract_nums(template)


async def run_action_agent(
    findings: list[Finding],
    simulator: SimulatorResult,
    summary: Summary,
    hospital_name: str,
    bill_date: str,
    ctx: RunContext,
) -> ActionPack:
    """Build action pack. LLM polish optional; template fallback always used."""
    ctx.emit("action", "stage_start", "Action Agent: building action pack")

    questions = _build_questions(findings)
    letter = _build_letter(hospital_name, bill_date, findings)

    # Optionally polish the letter with LLM
    try:
        polish_prompt = f"""Rewrite the following letter for a polite, firm tone. DO NOT add, remove or change any number, date, item name or placeholder.

{letter.body}"""
        resp = await llm_client.chat(
            [{"role": "user", "content": polish_prompt}],
            role="fast",
            temperature=0.3,
        )
        ctx.emit("action", "llm_call", "Action Agent: polishing letter")
        polished = resp.text.strip()
        if _validate_letter_numbers(polished, letter.body):
            letter = Letter(subject=letter.subject, body=polished, generated_by="llm")
        else:
            ctx.emit("action", "warning", "Letter number validation failed — using template")
    except LLMUnavailable:
        ctx.emit("action", "warning", "LLM unavailable for letter polish — using template")

    checklist = CHECKLIST_DEFAULT[:]

    pack = ActionPack(
        desk_questions=questions,
        letter=letter,
        checklist=checklist,
    )
    ctx.emit("action", "stage_end", f"Action Agent: {len(questions)} questions, letter generated_by={letter.generated_by}")
    return pack
