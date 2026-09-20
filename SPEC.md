# SPEC.md: BillLens technical specification

Section numbers are referenced by task prompts in `PHASES.md`. Read only the sections your task names, plus section 1.

---

## 0. End-to-end data flow

```
[Policy PDF] ─► ingest (chunk, embed, pgvector) ─► Policy Agent (search_policy → cited terms) ─► USER CONFIRMS TERMS
[Bill image/PDF] ─► Extraction Agent (vision → JSON → validate_totals → ≤2 repairs)
                 ─► Normalizer (exact → embedding → LLM re-rank among top-5)
                 ─► USER VERIFIES LINES (or auto_confirm)                        ◄── end of Phase 1
Phase 2:  Rules R1-R6 sweep (deterministic baseline findings)
       ─► Audit Agent (only "uncertain set", ≤10 lines, ≤6 steps each, parallel) → Proposals → validator → merge
       ─► Simulator (pure) → waterfall + coverage finding C1
       ─► Action Agent (questions, letter, checklist; number-checked; template fallback)
       ─► RunResult persisted in runs.result; events streamed via SSE throughout
```

---

## 1. Domain models (`backend/app/schemas.py`): single source of truth

Freeze after tag `contracts-v1`. Frontend types are generated from OpenAPI.

```python
from typing import Literal, Any
from datetime import date
from pydantic import BaseModel, Field

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
    extraction_flag: bool = False          # true if arithmetic/checksum suspicious → highlight in Verify screen
    user_edited: bool = False

# ---------- policy ----------
TermKey = Literal["sum_insured","room_rent_cap","copay_pct","proportionate_deduction"]
class PolicyTerm(BaseModel):
    key: TermKey
    status: Literal["extracted","manual","not_found"]
    value: float | bool | None = None      # sum_insured ₹ | room cap (₹/day or pct) | copay % | proportionate bool
    room_cap_kind: Literal["absolute","pct_si"] | None = None   # only for room_rent_cap
    quote: str | None = None               # VERBATIM from chunk (≤300 chars)
    page: int | None = None
    chunk_id: int | None = None
    similarity: float | None = None

class ResolvedPolicy(BaseModel):          # what the engine consumes (built from confirmed terms)
    is_insured: bool
    sum_insured: float | None = None
    room_rent_cap_per_day: float | None = None   # already resolved from pct_si via calc_room_cap
    copay_pct: float = 0.0
    proportionate_deduction: bool = False
    term_evidence: dict[str, str] = {}     # key → evidence_id

# ---------- evidence / findings ----------
class Evidence(BaseModel):
    id: str                                 # "E1","E2",… unique per run
    type: Literal["line","clause","catalog","calc","kb"]
    text: str                               # human-readable snippet (clause quote, catalogue row summary, calc string)
    meta: dict[str, Any] = {}               # page, similarity, source, ref_id, chunk_id…

class Finding(BaseModel):
    id: str                                 # "F1"…
    rule_code: str                          # R1..R6, C1 (coverage/room), A1 (agent ask)
    kind: Literal["billing","coverage"]
    severity: Severity
    origin: Literal["rule","agent"]
    line_ids: list[int] = []                # BillLine.line_no; [] for bill-level
    title: str
    explanation: str
    amount_at_stake: float | None = None    # None for agent 'ask' findings
    confidence: Confidence
    evidence_ids: list[str] = []
    suggested_question: str | None = None
    uncertain: bool = False                 # selects lines for the Audit Agent
    agent_note: str | None = None           # rationale from Audit Agent if confirmed/dismissed
    dismissed: bool = False

class WaterfallStep(BaseModel):
    key: Literal["billed","non_payable","room_rent","copay","sum_insured_cap","insurer_pays","patient_pays"]
    label: str
    amount: float                           # signed delta (negative = deduction); billed/insurer_pays/patient_pays are absolute
    running_total: float
    explanation: str
    evidence_ids: list[str] = []

class SimulatorResult(BaseModel):
    applied: bool                           # False when uninsured
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
    questionable_total: float               # billing findings, deduped per line (see 5.7)
    insurer_deductions_total: float         # non_payable + room_rent deduction
    insurer_pays: float | None
    patient_pays: float
    counts: dict[str, int]                  # {"red":n,"amber":n,"info":n}
    agent_stats: dict[str, int] = {}        # tool_calls, evidence_items, llm_calls, duration_ms

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
    ts_ms: int                              # ms since run start
    agent: AgentName
    type: EventType
    title: str                              # ALWAYS present: one human-readable line for the UI
    data: dict[str, Any] = {}               # tool args/results, quotes, similarity, counts
```

---

## 2. Database (`models.py`, SQLAlchemy 2.x async, `postgresql+psycopg://…?sslmode=require` for Neon)

Startup: `CREATE EXTENSION IF NOT EXISTS vector;` then `Base.metadata.create_all`. No Alembic. Store run-scoped artifacts as JSONB (they are always read and written whole).

| Table | Columns |
|---|---|
| `catalog_items` | id PK, canonical_name, category, synonyms text[], non_payable bool, non_payable_reason, bundled_in (nullable, e.g. `room_rent`), max_per_day (nullable int), ref_price_low, ref_price_high (nullable), ref_unit, ref_source, embedding Vector(384) |
| `documents` | id uuid PK, kind (`policy`\|`kb`), name, session_id (nullable for kb), page_count, created_at |
| `chunks` | id serial PK, document_id FK, page int, heading text, text, embedding Vector(384) |
| `policies` | id uuid PK, document_id FK, session_id, terms JSONB (`dict[key, PolicyTerm]`), confirmed bool, created_at |
| `bills` | id uuid PK, session_id, file_hash, filename, storage_path, page_count, is_insured bool, extracted JSONB, verified JSONB (list[MatchedLine]), created_at |
| `runs` | id uuid PK, session_id, kind (`policy_ingest`\|`bill_audit`), bill_id, policy_id, status, phase, mode (`live`\|`replay`), error, result JSONB, created_at, finished_at |
| `trace_events` | id serial PK, run_id, seq, ts_ms, agent, type, title, data JSONB. Unique (run_id, seq) |
| `llm_cache` | key PK (sha256), response JSONB, created_at |

`runs.status`: `queued → extracting → awaiting_verification → auditing → done | failed`. Policy-ingest runs: `queued → ingesting → done | failed`.
`session_id`: anonymous UUID generated by the frontend, sent as header `X-Session-Id`. No auth.

---

## 3. Catalogue and knowledge-base data

### 3.1 `seed/catalog.csv` (target 180-220 rows)

Columns: `canonical_name,category,synonyms,non_payable,non_payable_reason,bundled_in,max_per_day,ref_price_low,ref_price_high,ref_unit,ref_source`
- `synonyms`: pipe-separated abbreviations/variants (`INJ PANTOP 40|PANTOPRAZOLE INJ|PANTOP 40MG INJ`).
- Rough distribution: pharmacy generics ~60, consumables ~35 (about half `non_payable=1`), investigations ~35, room/nursing/fees/procedures ~30, other ~20. Include `ROOM RENT` (category `room`), `NURSING CHARGES` (`bundled_in=room_rent`), `RMO CHARGES` (`bundled_in=room_rent`), and typical non-payables (gloves, masks, admission kit, hand sanitizer, thermometer, BP cuff disposable, toiletries, shoe covers, caps).
- **Honesty (I10):** every row's `ref_source` is `DEMO_REFERENCE` unless copied from a public list; then use the list name. `non_payable_reason` text like "Commonly listed as non-payable consumable in standard insurer exclusion lists (verify against the official list before production use)". Do NOT invent precise real-world market prices as if factual; ranges are plausible demo numbers.
- Seeding embeds `canonical_name + " " + synonyms` with fastembed.

### 3.2 `seed/kb/*.md` (shared knowledge base, `documents.kind='kb'`)
Chunk by `## ` heading; the heading goes into `chunks.heading`, page = 1.
- `kb_nonpayable.md`: explanation of non-payable categories, one `##` per group (consumables, hospital-provided toiletries, registration/admission fees...), plain language.
- `kb_room_rent_rules.md`: how room-rent caps and proportionate deduction typically work, with a worked example.
- `kb_claim_documents.md`: documents to keep (itemised bill, discharge summary, investigation reports, pharmacy bills with prescriptions, ID/policy copy).
- `kb_billing_glossary.md`: abbreviations (RMO, INJ, NS, IV, OT, ICU, MRD...), "package vs itemised billing".
Each file ≤ ~1,200 words. Content is general, non-authoritative. Add the header line "Demo knowledge base; not legal advice".

---

## 4. Normalizer (`engine/normalizer.py`)

Input `list[BillLine]` → `list[MatchedLine]`. Steps per line:
1. **Clean**: uppercase, strip punctuation/extra spaces, expand a small abbreviation dict (`INJ→INJECTION, TAB→TABLET, NS→NORMAL SALINE, PCM→PARACETAMOL, PANTOP→PANTOPRAZOLE, RMO→RESIDENT MEDICAL OFFICER, IV→INTRAVENOUS, SYP→SYRUP`). Strip dosage tokens for matching only (`\b\d+\s?(MG|ML|GM|MCG)\b`); keep the raw text.
2. **Exact**: cleaned text equals a cleaned canonical name or synonym → `match_method="exact"`, score 1.0.
3. **Embedding**: embed all unmatched cleaned texts in ONE batch; cosine top-5 vs catalogue. Auto-accept if `top1 ≥ T_ACCEPT (0.82)` and `top1-top2 ≥ MARGIN (0.04)` → `"embedding"`.
4. **LLM re-rank**: for remaining lines with `top1 ≥ T_FLOOR (0.55)`, ONE batched LLM call: given each line and its 5 candidates `{id,name}`, return `{line_no, choice_id | null}`. The choice must be one of the 5 ids or null (validate; invalid → null). → `"llm"`. Else `"unmatched"`.
5. **Thresholds are starting points.** In Phase 2 tests, print a table of score distributions on the golden bills and tune. Target ≥ 90% of golden lines matched correctly without the LLM step.
6. If LLM is unavailable: skip step 4 (lines stay unmatched). Never fail the run.

Confidence bands from match method: `exact` or `embedding ≥ 0.85` → high; `embedding < 0.85` or `llm` → medium; unmatched lines produce NO findings except R1.

---

## 5. Rules (`engine/rules.py`): pure functions, no LLM, no DB

Signature: `run_rules(lines: list[MatchedLine], bill: ExtractedBill, policy: ResolvedPolicy, catalog: CatalogLookup, cfg: Config) -> list[Finding]`. Evidence: rule code creates `Evidence` rows (type `line` and `catalog`) through an `EvidenceStore` passed in.

| Code | Kind | Trigger | Severity | `amount_at_stake` |
|---|---|---|---|---|
| **R1** arithmetic | billing | line: `qty` and `unit_price` present and `abs(qty*unit_price - amount) > 1`. Bill-level: `abs(sum(amount) - stated_total) > 1`. | red, high | line: `abs(diff)`. Bill-level: `abs(diff)` (counted once). |
| **R2** duplicate | billing | Group by (`catalog_id` or cleaned text, `service_date`). (a) category in {investigation, procedure, professional_fee, nursing, room}: count > `max_per_day or 1` → **red**, high. (b) category in {pharmacy, consumable}: ≥2 lines with identical qty and amount → **amber**, `uncertain=True` (could be legitimate re-dosing). | see left | sum of `amount` of the extra lines (all but the first) |
| **R3** non-payable | coverage | `policy.is_insured` and matched catalog row `non_payable` | red; high if exact/embedding≥0.85 else medium | line `amount` |
| **R4** bundled | billing | catalog `bundled_in == "room_rent"` and the bill has ≥1 `room` line | amber, `uncertain=True` (depends on policy wording) | line `amount` |
| **R5** price variance | billing | `unit_price` (or `amount/qty`) `> ref_price_high * cfg.PRICE_VARIANCE_FACTOR (1.5)` | amber | `(unit_price - ref_price_high) * qty`. Explanation must say "above the demo reference range (a reference benchmark, not a legal cap)". |
| **R6** estimate variance | billing | `stated_total > estimate_amount * 1.2` | amber | `None` (bill-level; excluded from totals to avoid double counting) |
| **C1** room-rent limit | coverage | produced by the **simulator** (section 6), not `rules.py` | red | `room_rent_deduction` |

### 5.7 Totals (`engine/totals.py`)
- `questionable_total` = Σ over **billing** findings that are not dismissed, taking **max `amount_at_stake` per line** (dedupe per line), plus the bill-level R1 total diff once.
- `insurer_deductions_total` = `non_payable_total + room_rent_deduction` from the simulator (coverage kind). These are two different numbers on purpose: questionable = "ask the hospital"; deductions = "insurer will likely refuse".
- `counts` include only non-dismissed findings.

---

## 6. Claim simulator (`engine/simulator.py`): pure

Input: verified `MatchedLine`s, `ResolvedPolicy`. Config: `ROOM_LINKED = {"room","nursing","professional_fee","procedure"}` (real policies vary; state this in `assumptions`).

If `not policy.is_insured`: `applied=False`, `insurer_pays=0`, `patient_pays=billed_total`, no steps.

Algorithm:
1. `billed_total = Σ amount`.
2. `non_payable_total = Σ amount` for lines whose catalog row is non-payable (matched only).
3. Room: take the `room` line with the highest `unit_price` → `actual_rent`. If `cap` known and `actual_rent > cap`:
   - `ratio = cap / actual_rent`.
   - If `proportionate_deduction`: `room_rent_deduction = Σ amount*(1-ratio)` over lines in `ROOM_LINKED` that are not non-payable.
   - Else (flat cap only): `room_rent_deduction = room_line.amount * (1-ratio)` (only the room line).
   - Emit finding **C1** with evidence: the policy clause (from `policy.term_evidence`) and a `calc` evidence: `"ratio = 5000/8000 = 0.625"`.
4. `admissible = billed_total - non_payable_total - room_rent_deduction`.
5. `copay_amount = admissible * copay_pct/100`.
6. `insurer_pays = admissible - copay_amount`; if `sum_insured` known and `insurer_pays > sum_insured`: cap it (step `sum_insured_cap`).
7. `patient_pays = billed_total - insurer_pays`.
8. Steps (waterfall) in order: billed, non_payable (neg), room_rent (neg), copay (neg), sum_insured_cap (neg, only if applied), insurer_pays, patient_pays. Each with `running_total`, a one-sentence `explanation`, and `evidence_ids`.
9. `assumptions` always includes: "Estimate based on the terms you confirmed; actual insurer decisions may differ." and "Co-pay applied to the admissible amount after deductions." and, if used, "Proportionate deduction applied to room-linked categories: room, nursing, professional fees, procedures."

**Unit-test worked example (must pass exactly):** room 5 days × ₹8,000 = 40,000; surgeon fee 40,000 (professional_fee); pharmacy 30,000; non-payable consumables 2,000; investigations 10,000; cap ₹5,000/day; proportionate on; co-pay 10%.
→ billed 122,000; non_payable 2,000; ratio 0.625; room-linked 80,000 → deduction 30,000; admissible 90,000; co-pay 9,000; **insurer pays 81,000; patient pays 41,000**.
Second case: same but `proportionate_deduction=False` → deduction = 40,000×0.375 = 15,000; admissible 105,000; co-pay 10,500; insurer 94,500; patient 27,500.

---

## 7. Tools (`tools/*.py`): deterministic, the only source of evidence

Every tool: `async def tool(ctx: RunContext, args: ArgsModel) -> ToolResult`.

```python
class ToolResult(BaseModel):
    ok: bool
    data: Any                 # what the LLM sees (compact JSON)
    summary: str              # one line for the trace title
    evidence: list[Evidence]  # NEW evidence rows; runner registers them in ctx.evidence and gives them IDs
```

| Tool | Args | Returns / evidence | Used by |
|---|---|---|---|
| `validate_totals` | lines, stated_total | `{sum, stated, diff, ok, arithmetic_mismatches[{line_no,expected,printed}]}` | extraction |
| `search_catalog` | query, k=5 | top-k `{catalog_id,name,category,similarity}`; evidence type `catalog` | audit |
| `search_policy` | query, k=4 | chunks of THIS run's policy doc `{chunk_id,page,heading,text,similarity}`; evidence type `clause` (meta: page, similarity, chunk_id) | policy, audit |
| `search_kb` | query, k=3 | shared KB chunks; evidence type `kb` | audit |
| `get_clause` | chunk_id | full chunk text (and neighbours ±1 chunk); evidence `clause` | policy, audit |
| `find_duplicates` | line_no | lines with the same catalog/text and date, with their amounts; evidence `line` | audit |
| `lookup_reference_price` | catalog_id | `{low,high,unit,source}`; evidence `catalog` | audit |
| `get_line_context` | line_no | the line, its baseline findings, same-date neighbours; evidence `line` | audit |
| `calc_room_cap` | sum_insured, pct | `{cap_per_day}`; evidence `calc` (`"1% of ₹5,00,000 = ₹5,000/day"`) | policy |

Tool schemas for the LLM are generated from the Pydantic args models (`registry.py::openai_tool_schemas(names)`). Each agent gets an **allowlist**; a call to any other tool returns `ok=False`.

---

## 8. Agents (`agents/*.py`)

### 8.0 The runner (`agents/base.py`): the only agent loop

```python
class AgentSpec(BaseModel):
    name: AgentName; system_prompt: str; tools: list[str]; max_steps: int
    output_model: type[BaseModel]
    model_role: Literal["vision","agent","fast"] = "agent"

async def run_agent(spec, payload: dict, ctx: RunContext, validate, fallback):
    msgs = [system(spec.system_prompt), user(json.dumps(payload))]
    for step in range(spec.max_steps):
        resp = await llm.chat(msgs, role=spec.model_role, tools=tool_schemas(spec.tools), temperature=0)
        ctx.emit(spec.name, "llm_call", f"{spec.name}: reasoning step {step+1}")
        if not resp.tool_calls:
            try:
                out = spec.output_model.model_validate_json(extract_json(resp.text))
            except ValidationError:
                msgs.append(user("Your output was not valid JSON for the schema. Return only valid JSON.")); continue
            return validate(out, ctx)            # drops claims citing evidence not gathered in this run (I3)
        msgs.append(assistant_tool_calls(resp))
        for call in resp.tool_calls:
            ctx.emit(spec.name, "tool_call", f"{call.name}({short(call.args)})", data=call.args)
            result = await ctx.tools.call(spec.name, call.name, call.args)   # allowlist + timeout 10s
            ids = ctx.evidence.add(result.evidence)
            ctx.emit(spec.name, "tool_result", result.summary, data={"evidence_ids": ids})
            msgs.append(tool_msg(call.id, result.data))
    return fallback(ctx)                          # step cap reached, or LLM down → deterministic fallback
```

`ctx.emit` writes `trace_events` and pushes to the SSE bus (section 10). Any exception inside an agent is caught by the orchestrator, emitted as `warning`, and the stage continues with the fallback (I2).

### 8.1 Extraction Agent (`model_role="vision"`, controller loop, max 2 repairs)

Flow: rasterize PDF pages (PyMuPDF, 200 dpi, ≤3 pages) or load the image; downscale to ≤2000 px long side, JPEG q85. Call 1 returns `ExtractedBill`. Then `validate_totals` (emit tool_call/tool_result events). If `ok` → done. Else repair (≤2): send the image + the diff + mismatched line numbers, receive `{corrections, missing_lines, remove_line_nos}`, apply it, and re-validate. After the cap, mark `extraction_flag=True` on mismatched lines and continue. The Verify screen shows them; the pipeline never fails because of a mismatch.

System prompt:
> You transcribe Indian hospital bills into JSON. Rules: (1) Copy each charge row exactly as printed, keeping abbreviations and spelling. (2) One entry per printed charge row. Do NOT include department subtotals, page totals, or the grand total as lines. (3) Numbers are plain numbers: no ₹ symbol, no thousands separators. (4) If a value is unreadable or missing use null and add a note. Never guess. (5) Do not compute, correct, or reorder anything, including totals. (6) Dates in ISO 8601. (7) `stated_total` is the grand total printed on the bill; `estimate_amount` only if an admission estimate is printed. Return ONLY JSON matching the schema.

Repair prompt:
> The checksum failed: the extracted lines sum to {sum} but the bill states {stated} (difference {diff}). Rows where qty × rate ≠ amount: {mismatches}. Re-read the image. Fix ONLY what the image clearly shows: return JSON `{"corrections":[{"line_no":..,"raw_text":..,"qty":..,"unit_price":..,"amount":..}],"missing_lines":[{...BillLine...}],"remove_line_nos":[...]}`. Change nothing else.

Fallback: if the vision LLM fails entirely → look up a cached extraction for the file hash (`llm_cache`); if none → status `awaiting_verification` with an empty editable table plus a warning (manual entry).

### 8.2 Policy Agent (`model_role="agent"`, tools `search_policy, get_clause, calc_room_cap`, max_steps 4 per term)

One run per term (4 in parallel with `asyncio.gather`). Queries to seed: room cap → "room rent limit per day normal room ICU eligibility"; copay → "co-payment percentage of admissible claim"; sum insured → "sum insured amount"; proportionate → "proportionate deduction of charges linked to room rent".

System prompt:
> You extract ONE term from an insurance policy using the tools. Call `search_policy` (rephrase and retry if needed). Return ONLY JSON: `{"found": bool, "value": number|bool|null, "room_cap_kind": "absolute"|"pct_si"|null, "quote": "<text copied VERBATIM from a retrieved chunk, ≤300 chars>", "chunk_id": int, "reasoning": "<one sentence>"}`. Rules: never infer from outside knowledge; if the policy does not state it, return `found:false`. For room rent, use the limit for a normal/general (non-ICU) room. If the limit is a percentage of the sum insured, set `room_cap_kind:"pct_si"` and `value` to the percentage. If the limit is a rupee amount per day, use `"absolute"`.

**Validator (`rag/grounding.py`), MUST implement:** (a) `quote` normalized (lowercase, collapsed whitespace) is a substring of the normalized text of chunk `chunk_id` fetched in this run; (b) for numeric terms, the number (commas stripped, e.g. `5,000 → 5000`) appears in the quote's digits; for `proportionate_deduction`, the quote must contain "proportion". Failure → `status="not_found"` (the UI asks for manual entry). Success → `status="extracted"`, `page` and `similarity` copied from the retrieval, evidence `clause` registered. After extraction, if `room_cap_kind=="pct_si"` and `sum_insured` found → compute the absolute cap with `calc_room_cap` (evidence `calc`).
Fallback: any failure → `not_found` for that term.

### 8.3 Audit Agent (`model_role="agent"`, tools `search_catalog, search_policy, search_kb, get_clause, find_duplicates, lookup_reference_price, get_line_context`, max_steps 6 per line)

**Uncertain set (deterministic, `orchestrator/runner.py`)**: lines with (a) baseline findings where `uncertain=True` (R2 pharmacy exact-duplicates, R4 bundled); (b) `match_method in {"llm","unmatched"}` with `amount ≥ 500`; sorted by amount desc, **cap 10**. Run lines in parallel (semaphore 4).

Payload per line: `{bill: {hospital, room_rent_per_day, is_insured}, line, baseline_findings, confirmed_policy_terms}`.

System prompt:
> You are a careful hospital-bill investigator. A rules engine has already flagged this line or found it ambiguous. Use the tools to gather evidence, then decide: `confirm` (the flag stands), `dismiss` (the flag is probably legitimate), or `ask` (a question the patient should raise). Return ONLY JSON: `{"line_no":int,"verdict":"confirm"|"dismiss"|"ask","rationale":"≤280 chars","evidence_ids":["E3",...],"suggested_question":"..."|null}`. Rules: cite only evidence IDs returned by your own tool calls; do not state any rupee figure that is not in the evidence; use hedged language ("may", "worth asking"); never accuse the hospital of wrongdoing; you cannot change amounts or severities.

**Validator (I3/I4):** drop the proposal unless `evidence_ids` is non-empty, all IDs ∈ this line's run evidence, and every ₹/number in `rationale` appears in the cited evidence texts or the line data. **Merge rules:** `confirm` → attach `agent_note` and evidence to the existing finding (severity unchanged). `dismiss` → only if the existing finding is amber: set `dismissed=True`, `severity="info"`. `ask` → append a new Finding `A1` (kind billing, amber, origin agent, `amount_at_stake=None`, `suggested_question`). Red findings are untouchable.
Fallback: on any failure the baseline findings stand unchanged.

### 8.4 Action Agent (`model_role="agent"`, no tools, max_steps 2)

Input: structured findings, simulator result, summary numbers, hospital name, confirmed policy terms. Output JSON: `{"desk_questions":[{"priority","question","why","line_ids","amount"}], "checklist":[...]}`. `amount` values are copied from findings and code-validated against them (else set null). The letter is **built by code from a template** with a table of flagged items and amounts, then optionally polished by the LLM with this constraint: "Rewrite for a polite, firm tone. Do NOT add, remove or change any number, date, item name or placeholder." **Validator:** the set of numbers in the polished text must equal the set in the template (regex `\d[\d,\.]*`), else use the template (`generated_by="template"`).
Fallback: template letter plus templated questions (`"Please explain the charge for {item} (₹{amount}): {finding.title}"`) ranked by amount.

---

## 9. RAG (`rag/`)

- **Ingest** (`ingest.py`): PyMuPDF `page.get_text("blocks")` per page; split blocks on numbered-clause or ALL-CAPS heading patterns; merge small blocks; target 500-900 chars per chunk, overlap 100 chars; record `page`, `heading`. Embed with fastembed (`passage` mode), batch 32. Store in `chunks` with `document_id`. Text-native PDFs only; if extracted text < 200 chars per page, emit a `warning` and let the user enter terms manually.
- **Embedding** (`embed.py`): `Embedder.embed_passages(list[str])`, `Embedder.embed_query(str)`; singleton model loaded at startup; dim from config (384).
- **Retrieve** (`retrieve.py`): `search(doc_scope, query, k)`; SQL `ORDER BY embedding <=> :q LIMIT k`; `similarity = 1 - distance`. `doc_scope` is `policy:{document_id}` or `kb`. **Hybrid boost**: also run a case-insensitive keyword `ILIKE` over the distinctive query words (`room rent`, `co-pay|copayment`, `sum insured`, `proportion`) and merge the results (dedupe by chunk id; keyword hits get similarity = max(sim, 0.6)). Return top k.
- No index needed (<1,000 rows). Fallback if pgvector fails: load all chunk embeddings into numpy and compute cosine in memory.

---

## 10. Orchestrator, events, API

### 10.1 Events
`RunContext` holds: `run_id`, `session`, `evidence: EvidenceStore` (assigns `E1…`), `tools`, `emit()`, `t0`. `emit` persists a `TraceEvent` (monotonic `seq` from 1) and publishes to an in-memory `asyncio.Queue` per run (`orchestrator/events.py`). Every stage emits `stage_start`/`stage_end` with counts (e.g. "47 lines extracted", "6 policy clauses retrieved").

### 10.2 Phases (`orchestrator/runner.py`)
- **policy_ingest run** (`POST /policies`): ingest → Policy Agent (4 terms in parallel) → save `policies.terms` → status `done`. The user confirms or edits in the UI (`PUT /policies/{id}/terms`, `confirmed=true`).
- **bill_audit Phase 1** (`POST /runs`): extraction → normalizer → save `bills.extracted`, `bills.verified` (= matched lines) → status `awaiting_verification`. If `auto_confirm=true` → go straight to Phase 2.
- **Phase 2** (`PUT /runs/{id}/confirm` with edited lines and `is_insured`): rules sweep → uncertain set → Audit Agent → merge → simulator (+C1) → totals → Action Agent → build `RunResult` → `runs.result` → status `done`, emit `done` with `agent_stats` (real counts: tool calls, evidence items, LLM calls, duration).
- **Watchdog**: whole phase timeout 120 s; on timeout emit `warning` and finish with whatever stages completed (baseline result). Each stage is wrapped in try/except → `warning` event and fallback.
- Run phases as `asyncio.create_task`; single Render instance, so in-memory queues are fine.

### 10.3 API

| Method | Path | Body / notes |
|---|---|---|
| GET | `/health` | `{db, llm, embed}` statuses |
| GET | `/samples` | list `{id, kind: bill\|policy, title, description, thumb_url, insured?}` |
| POST | `/policies` | multipart `file` OR `sample_id` → `{policy_id, run_id}` |
| GET | `/policies/{id}` | terms, status |
| PUT | `/policies/{id}/terms` | `{terms: {...}, confirmed: true}`; server resolves pct→absolute and returns `ResolvedPolicy` |
| POST | `/bills` | multipart `file` OR `sample_id`, `is_insured` → `{bill_id}` |
| POST | `/runs` | `{bill_id, policy_id?, auto_confirm?: bool}` → `{run_id}` |
| GET | `/runs/{id}` | `{status, phase, lines?}` (lines present when awaiting verification) |
| PUT | `/runs/{id}/confirm` | `{lines: MatchedLine[], is_insured: bool}` → 202 |
| GET | `/runs/{id}/stream` | SSE, `event: trace`, `id: seq`, data = `TraceEvent` JSON. Backlog first (`?since=`), then live. 15 s heartbeat. |
| GET | `/runs/{id}/events?since=N` | JSON polling fallback |
| GET | `/runs/{id}/result` | `RunResult` (409 until done) |
| POST | `/demo/{sample_id}` | replay run (see 10.4) → `{run_id}` |

CORS: allow the Vercel origin + `http://localhost:5173`. Upload limit 10 MB. Static sample files served from `/static/samples/`.

### 10.4 Replay mode (`orchestrator/replay.py`)
`python -m app.scripts.record_replay <sample_id>` runs the REAL pipeline (auto_confirm) and writes `seed/replays/{sample_id}.json` = `{events:[{ts_ms,agent,type,title,data}], policy_terms, result}`. `POST /demo/{sample_id}` creates a run with `mode="replay"`, re-emits the recorded events with their original gaps (each gap capped at 1.2 s), and finally sets `runs.result` from the file. Replay needs no LLM and no DB writes beyond the run rows. The UI shows a small "Replay" badge.

---

## 11. LLM client (`llm/client.py`)

- `openai.AsyncOpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)`. Roles map to env models: `vision → LLM_MODEL_VISION`, `agent → LLM_MODEL_AGENT`, `fast → LLM_MODEL_FAST`.
- `chat(msgs, role, tools=None, temperature=0, json_mode=False)`; `vision(image_bytes_list, prompt, schema)`; both return a normalized `LLMResponse{text, tool_calls, usage}`.
- **Cache**: key = sha256(model + messages + tools + temperature). `LLM_CACHE_MODE=readwrite|readonly|off`. Images are hashed by bytes.
- **Timeouts**: vision 45 s, others 25 s. **Retry**: 1 retry on 429/5xx/timeout with 1 s backoff. **Fallback provider**: if `LLM_FALLBACK_*` is set, try it after retries fail.
- **Concurrency**: global semaphore of 4.
- **Errors**: raise `LLMUnavailable`; callers catch it and use their fallback (I2).
- Log token usage per call to feed `agent_stats`.

---

## 12. Frontend (`frontend/`)

### 12.1 Design tokens (`src/styles/tokens.css`, Tailwind theme extends these)
Font Inter. Neutral slate surfaces, ONE accent (indigo). Severity colours are used ONLY for findings.
```
--bg #F8FAFC  --surface #FFFFFF  --border #E2E8F0  --text #0F172A  --muted #64748B  --accent #4F46E5
--red #DC2626 (bg #FEF2F2)   --amber #D97706 (bg #FFFBEB)   --green #059669 (bg #ECFDF5)   --info #64748B (bg #F1F5F9)
radius 12px cards, 8px controls; shadow-sm only.
```
Dark mode: redefine tokens under `@media (prefers-color-scheme: dark)`. Mobile-first: content max-width 1200px; the result screen is 2-col ≥1024px.

### 12.2 Routes / screens (wizard with a stepper: Coverage → Bill → Analysis → Verify → Result → Action)

| Route | Purpose | Key components / behaviour |
|---|---|---|
| `/` | Hero + start | Headline "Know what you're paying for, before you pay." Buttons: "Start an audit", "Try a sample". Phone-framed preview of the result screen. Demo-mode toggle (Live/Replay) in the header. |
| `/coverage` | Policy step | `PolicyPicker` (upload PDF / 2 sample policies / "No insurance"). After upload: mini `TraceTimeline` (Policy Agent) and `PolicyTermsCard`: 4 rows, each with value input, status badge (Extracted / Manual / Not found), quote block with page and similarity, "Confirm terms" button. |
| `/bill` | Bill step | `BillDropzone` (camera capture via `<input capture>`, upload, 3 sample cards) + insured toggle if no policy. |
| `/run/:id` | Analysis | Full-width `TraceTimeline` (SSE). Groups by agent, each with status icon; rows show tool chip, summary; click to expand JSON; retrieval rows show quote + similarity. Footer shows real stats. Auto-navigates to Verify at `awaiting_verification`. |
| `/run/:id/verify` | Verify lines | `LinesEditor`: compact editable table; rows with `extraction_flag` highlighted; checksum badge ("Lines sum to stated total ✓" or "Off by ₹X"). Buttons: "Looks right, run audit" (PUT confirm). |
| `/run/:id/result` | **Hero screen** | Left: `AuditTable` (rows tinted by top severity, severity pill, ₹ at stake, filter chips). Right (sticky): `SummaryCard` (count-up ₹ "questionable", ₹ "insurer deductions", "Insurer likely pays ₹A · You pay ₹B") and `Waterfall` (Recharts stacked bar). Row click opens `WhyDrawer` (bottom sheet on mobile). Buttons: "Action pack", "View agent trace" (collapsible timeline). |
| `/run/:id/actions` | Action pack | Tabs: "Ask at the desk" (ranked questions with copy buttons), "Query letter" (editable textarea, copy, print-to-PDF), "Checklist". |

**WhyDrawer** sections: header (item, ₹) · What we found (rule title + explanation) · Evidence (clause quote block with page + similarity; catalogue reference row; calc string) · ₹ math · Confidence badge (High/Medium/Low, NEVER a percentage) · Origin badge ("Rule" or "Rule + agent-reviewed") with `agent_note` · "Ask this" with copy.

### 12.3 State and API
- `src/api/client.ts`: `fetch` wrapper adding `X-Session-Id` (UUID in `localStorage`, wrapped in try/catch), base URL `VITE_API_URL`. Types from `schema.d.ts` (`make types` runs `openapi-typescript $VITE_API_URL/openapi.json -o src/api/schema.d.ts`).
- TanStack Query for REST. `useRunStream(runId)`: `EventSource(/runs/{id}/stream?since=lastSeq)`; on error retry twice, then poll `/events?since=` every 1 s; reducer keyed by `seq` (dedupe); exposes `{events, status, connected}`.
- `VITE_USE_MOCKS=true` serves `src/mocks/*.json` (real golden output) from the client so the UI can be built before the backend exists.

### 12.4 UX rules
- Skeletons for loading; empty and error states on every screen; never a blank screen.
- Count-up animation for ₹ numbers (400-800 ms); rows fade in as findings arrive.
- Never show a bare LLM error; show "We couldn't verify this automatically; here's what the rules found."
- Print stylesheet for the letter. ARIA labels on drawer and tabs; focus trap in the drawer.
- Copy tone: plain, calm, non-accusatory (I7).

---

## 13. Fixtures (`backend/scripts/make_fixtures.py`, output to `backend/tests/fixtures/` and `app/seed/samples/`)

Generate from Python spec files (one per sample) so the planted issues and golden results are known **by construction**, independent of the engine.
- Render bills with `reportlab` (3 layouts) → rasterize with PyMuPDF to PNG. Sample C gets a "phone photo" degradation via Pillow (slight rotation, blur, noise, uneven brightness).
- Each spec produces: `bills/{id}.png` (+ `.pdf`), `golden/{id}.lines.json` (the true lines incl. catalog names), `golden/{id}.expected.json` (planted findings `[ {rule_code, line_no, at_stake} ]`, and expected `billed_total, questionable_total, insurer_deductions_total, insurer_pays, patient_pays`).

| Sample id | Layout | Policy | Planted issues |
|---|---|---|---|
| `sample-a-ortho-insured` | classic grid, ~46 lines | policy A (flat ₹5,000/day non-ICU cap, 10% co-pay, proportionate deduction, SI ₹5,00,000) | room ₹8,000 × 5 days; separate NURSING CHARGES (R4); duplicate CBC same date (R2 red); duplicate `INJ PANTOP 40MG` same date/qty (R2 amber → Audit Agent); 4-5 non-payable consumables (R3); one inflated tablet price (R5); one qty×rate≠amount line (R1); stated total consistent with printed line amounts; estimate ₹1,20,000 vs total well above (R6) |
| `sample-b-pctsi-insured` | compact, grouped by department, ~35 lines | policy B (cap "1% of sum insured per day", SI ₹5,00,000, 20% co-pay, no proportionate clause) | room ₹7,000/day × 4; 3 non-payables; 1 duplicate investigation; showcases `calc_room_cap` and the flat-cap deduction path |
| `sample-c-uninsured-photo` | pharmacy-heavy with abbreviations, phone-photo look, ~30 lines | none (uninsured) | R1, R2, R5 only; R3/simulator skipped |

**Policy PDFs** (`policies/policy-a-flat-cap.pdf`, `policy-b-pct-si.pdf`), 6-10 pages, text-native, realistic structure (definitions, coverage, exclusions, claims procedure). Must contain: the room-rent clause (with an ICU limit as a **distractor**), the co-pay clause, sum insured in a schedule table, the proportionate-deduction wording (policy A only), plus 2-3 unrelated sub-limits (cataract, maternity waiting period) as retrieval noise. Invent a fictional insurer name ("Demo Health Assure"). Never imitate a real insurer.

**Retrieval eval set** (`tests/fixtures/golden/retrieval_eval.json`): 8 queries → the expected chunk (by unique substring) → used by `scripts/eval.py` to report hit@3.

---

## 14. Config, env, deploy

`.env.example` (backend):
```
DATABASE_URL=postgresql+psycopg://billlens:billlens@localhost:5432/billlens
LLM_BASE_URL=  LLM_API_KEY=  LLM_MODEL_VISION=  LLM_MODEL_AGENT=  LLM_MODEL_FAST=
LLM_FALLBACK_BASE_URL=  LLM_FALLBACK_API_KEY=  LLM_FALLBACK_MODEL=
LLM_CACHE_MODE=readwrite
EMBED_MODEL=BAAI/bge-small-en-v1.5  EMBED_DIM=384  FASTEMBED_CACHE_PATH=/app/.fastembed
PRICE_VARIANCE_FACTOR=1.5  ESTIMATE_VARIANCE_FACTOR=1.2
ALLOWED_ORIGINS=http://localhost:5173,https://<your-app>.vercel.app
STORAGE_DIR=./storage  REPLAY_MAX_GAP_MS=1200
```
Frontend: `VITE_API_URL`, `VITE_USE_MOCKS`.

- `docker-compose.yml`: `db` (`pgvector/pgvector:pg16`, port 5432), `api` (build `./backend`, depends on db), optional `web`.
- `backend/Dockerfile`: `python:3.11-slim`; install requirements; **pre-download the fastembed model at build** (`RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"`); `CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT`. On startup: create extension, `create_all`, run the seed if `catalog_items` is empty.
- Render: Docker web service from `backend/`, env vars set, health check `/health`. Note the free tier cold start: ping it 5 minutes before demo. If memory is exceeded, switch embeddings to the API fallback and re-seed.
- Vercel: root `frontend/`, env `VITE_API_URL`, SPA rewrite in `vercel.json`.
- `Makefile`: `db` (compose up db), `seed`, `test`, `dev-api`, `dev-web`, `types`, `fixtures`, `record-replay`, `eval`, `lint`.

---

## 15. Tests (`backend/tests/`), run with `make test`

| File | Asserts |
|---|---|
| `test_simulator.py` | The two worked examples in section 6 exactly; uninsured path; cap-not-exceeded path; sum-insured cap. |
| `test_rules.py` | Each rule R1-R6 on tiny hand-built inputs (trigger and non-trigger cases); dedupe rules in totals. |
| `test_golden.py` | For each sample: load `golden/{id}.lines.json` + policy → run rules + simulator (NO LLM) → planted findings ⊆ produced findings; totals equal `expected.json`. **This is the deterministic-floor test.** |
| `test_normalizer.py` | Golden lines: ≥90% correct without the LLM step; prints the score table. LLM step mocked. |
| `test_grounding.py` | Quote-not-in-chunk rejected; number-not-in-quote rejected; valid accepted; `1%` of SI computed. |
| `test_agent_validators.py` | Proposal with unknown evidence ID dropped; `dismiss` on a red finding ignored; `ask` creates amber with `amount_at_stake=None`; letter with a changed number falls back to the template. |
| `test_pipeline_e2e.py` | Full run on `sample-a` with a **mocked LLM client** (recorded fixtures) → `RunResult` valid, trace has events for all 4 agents, seq monotonic. |
| `test_llm_down.py` | LLM raises `LLMUnavailable` everywhere → pipeline still returns a rules-based `RunResult` (I2). |

Frontend: `npm run build` (typecheck) is the gate; UI is verified in the browser at 390 px and 1280 px.

---

## 16. Failure modes and fallbacks

| Failure | Behaviour |
|---|---|
| Vision LLM down or slow | Cached extraction by file hash → else empty editable Verify table + warning |
| Extraction checksum can't be repaired | Flag lines, continue; user verifies |
| Embedding model can't load | Exact-match normalizer only; retrieval falls back to keyword `ILIKE` |
| pgvector error | In-memory numpy cosine |
| Policy term ungrounded | `not_found` → manual entry field |
| Audit Agent step cap / invalid output | Baseline findings stand |
| Action Agent fails or changes numbers | Template letter and templated questions |
| SSE blocked | Polling `/events` |
| Whole backend unavailable | Frontend `VITE_USE_MOCKS=true` demo build plus backup video |
| Replay | `POST /demo/{sample_id}` works with LLM and DB offline (aside from run rows) |
