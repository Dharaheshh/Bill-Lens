from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

Category = Literal["room","nursing","professional_fee","procedure","pharmacy","consumable","investigation","implant","other"]
Severity = Literal["red","amber","info"]
Confidence = Literal["high","medium","low"]

# ---------- bill ----------
class BillLine(BaseModel):
    line_no: int
    raw_text: str
    qty: float | None = None
    unit_price: float | None = None
    amount: float
    service_date: date | None = None
    category_guess: Category | None = None

class ExtractedBill(BaseModel):
    hospital_name: str | None = None
    bill_date: date | None = None
    stated_total: float | None = None
    estimate_amount: float | None = None
    lines: list[BillLine]
    notes: list[str] = []

class MatchedLine(BillLine):
    catalog_id: int | None = None
    canonical_name: str | None = None
    category: Category | None = None
    match_method: Literal["exact","embedding","llm","unmatched"] = "unmatched"
    match_score: float | None = None
    extraction_flag: bool = False
    user_edited: bool = False

# ---------- policy ----------
TermKey = Literal["sum_insured","room_rent_cap","copay_pct","proportionate_deduction"]
class PolicyTerm(BaseModel):
    key: TermKey
    status: Literal["extracted","manual","not_found"]
    value: float | bool | None = None
    room_cap_kind: Literal["absolute","pct_si"] | None = None
    quote: str | None = None
    page: int | None = None
    chunk_id: int | None = None
    similarity: float | None = None

class ResolvedPolicy(BaseModel):
    is_insured: bool
    sum_insured: float | None = None
    room_rent_cap_per_day: float | None = None
    copay_pct: float = 0.0
    proportionate_deduction: bool = False
    term_evidence: dict[str, str] = {}

# ---------- evidence / findings ----------
class Evidence(BaseModel):
    id: str
    type: Literal["line","clause","catalog","calc","kb"]
    text: str
    meta: dict[str, Any] = {}

class Finding(BaseModel):
    id: str
    rule_code: str
    kind: Literal["billing","coverage"]
    severity: Severity
    origin: Literal["rule","agent"]
    line_ids: list[int] = []
    title: str
    explanation: str
    amount_at_stake: float | None = None
    confidence: Confidence
    evidence_ids: list[str] = []
    suggested_question: str | None = None
    uncertain: bool = False
    agent_note: str | None = None
    dismissed: bool = False

class WaterfallStep(BaseModel):
    key: Literal["billed","non_payable","room_rent","copay","sum_insured_cap","insurer_pays","patient_pays"]
    label: str
    amount: float
    running_total: float
    explanation: str
    evidence_ids: list[str] = []

class SimulatorResult(BaseModel):
    applied: bool
    billed_total: float
    non_payable_total: float = 0
    room_rent_deduction: float = 0
    copay_amount: float = 0
    insurer_pays: float
    patient_pays: float
    steps: list[WaterfallStep] = []
    assumptions: list[str] = []

class DeskQuestion(BaseModel):
    priority: int
    question: str
    why: str
    line_ids: list[int] = []
    amount: float | None = None

class Letter(BaseModel):
    subject: str
    body: str
    generated_by: Literal["template","llm"]

class ActionPack(BaseModel):
    desk_questions: list[DeskQuestion]
    letter: Letter
    checklist: list[str]

class Summary(BaseModel):
    billed_total: float
    questionable_total: float
    insurer_deductions_total: float
    insurer_pays: float | None
    patient_pays: float
    counts: dict[str, int]
    agent_stats: dict[str, int] = {}

class RunResult(BaseModel):
    run_id: str
    bill: ExtractedBill
    lines: list[MatchedLine]
    policy_terms: dict[str, PolicyTerm] = {}
    policy: ResolvedPolicy
    findings: list[Finding]
    evidence: list[Evidence]
    simulator: SimulatorResult
    summary: Summary
    action_pack: ActionPack | None = None
    mode: Literal["live","replay"] = "live"

# ---------- trace ----------
AgentName = Literal["orchestrator","extraction","normalizer","rules","policy","audit","simulator","action"]
EventType = Literal["stage_start","stage_end","tool_call","tool_result","retrieval","llm_call","finding","validation","warning","error","done"]
class TraceEvent(BaseModel):
    run_id: str
    seq: int
    ts_ms: int
    agent: AgentName
    type: EventType
    title: str
    data: dict[str, Any] = {}
