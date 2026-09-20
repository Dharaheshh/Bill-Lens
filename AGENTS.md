# AGENTS.md: BillLens

> Read this whole file before EVERY task. Then read the SPEC sections your task names (`docs/SPEC.md`).
> If a task prompt conflicts with the invariants in section 2, the invariants win. The task prompt wins on scope.

## 1. What we are building

**BillLens** is an agentic hospital-bill and insurance-claim auditor for Indian patients (currency: INR, ₹).

The user optionally uploads an **insurance policy PDF** and a **hospital bill** (photo or PDF). The system:

1. **Reads the policy** with RAG (chunks, embeddings, pgvector) and extracts cited terms: room-rent cap, co-pay, sum insured, proportionate-deduction clause. The user confirms them.
2. **Reads the bill** with a vision LLM into structured JSON, then self-checks it with a checksum tool and repairs itself (max 2 loops).
3. **Normalizes** each bill line to a reference catalogue (exact match, then embeddings, then constrained LLM re-rank).
4. **Audits** with deterministic rules R1-R6, then a bounded Audit Agent investigates only the ambiguous lines using tools and retrieved evidence.
5. **Simulates** the insurer payout in pure code (a waterfall: billed, non-payables, room-rent deduction, co-pay, insurer pays vs patient pays).
6. **Produces an action pack**: ranked questions to ask at the desk, a query letter, a document checklist.
7. **Shows everything live**: an agent trace panel (real events) and a "WHY" drawer per flag with quote, page, and ₹ math.

Context: 8-hour hackathon (HACKDAY 1.0, theme "Tech for a Better Tomorrow"). Judging: Problem & Impact 25, Innovation 20, Technical 25, UX 15, Feasibility 15. Submission at 5 PM: GitHub repo, deployed link, PPT. The demo is 3 minutes. **Judges must understand the value within 60 seconds.** All data in the prototype is synthetic.

## 2. Non-negotiable invariants

| # | Invariant | Why |
|---|---|---|
| I1 | **Agents investigate. Evidence verifies. Code decides.** Every ₹ figure comes from code in `engine/` or `tools/`, never from LLM text. | Trust story and judge Q&A. |
| I2 | **Deterministic floor.** With every LLM call failing, the app must still produce a full rules-based audit and simulator result from cached or verified extraction. Agents enhance; they never gate. | Demo survives API failure. |
| I3 | **Evidence-or-drop.** Any agent claim must cite evidence IDs that its own tool calls returned in this run. Uncited or unknown IDs are dropped by the validator. | Hallucination control. |
| I4 | **Agent authority is limited.** Agents may `confirm`, `dismiss` (amber findings only), or `ask` (new amber finding with `amount_at_stake=None`). Agents can never create red findings, edit amounts, or change totals. | Money is never LLM-decided. |
| I5 | **User confirms** extracted policy terms and (unless auto-confirm demo mode) verified bill lines before any money math runs. | Human-in-the-loop. |
| I6 | **The trace is real.** Every trace event is emitted by actual execution (`run.emit(...)`). Replay mode plays back recorded real events and is labelled "Replay". Never script fake events. | Honesty. |
| I7 | **Wording**: "questionable", "worth asking about", "may be deducted". Never "fraud", "overcharged", "illegal". Price benchmarks are labelled "reference benchmark, not a legal cap". | Legal and ethical safety. |
| I8 | **No secrets in git.** `.env` is gitignored; ship `.env.example`. | Security. |
| I9 | **Everything degrades gracefully.** Every external call has a timeout, one retry, and a fallback (see SPEC section 16). | Hackathon reliability. |
| I10 | **No unlabeled synthetic claims.** Reference prices use `ref_source="DEMO_REFERENCE"` unless from a cited public list. Slides state the data is synthetic. | Credibility. |

## 3. Architecture at a glance

```
React+Vite+TS+Tailwind (Vercel)  ──REST + SSE──►  FastAPI (Render, Docker)
                                                   ├─ orchestrator/  run state machine + event emitter
                                                   ├─ agents/        extraction, policy, audit, action (LLM tool loops)
                                                   ├─ tools/         deterministic tools the agents call
                                                   ├─ engine/        normalizer, rules R1-R6, simulator (pure Python)
                                                   ├─ rag/           pdf → chunks → fastembed → pgvector
                                                   └─ llm/           OpenAI-compatible client, cache, retries, fallback
                                                   Postgres + pgvector (Neon/Supabase)
```

Flow: `policy_ingest run` (Policy Agent) and `bill_audit run` = Phase 1 (extract → normalize → **pause for user verify**) then Phase 2 (rules sweep → Audit Agent → simulator → Action Agent).

## 4. Stack (do not add alternatives)

- **Backend**: Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2.x async with `psycopg` (v3), `pgvector`, `fastembed` (`BAAI/bge-small-en-v1.5`, 384-dim), `pymupdf`, `openai` SDK (OpenAI-compatible base URL), `sse-starlette`, `reportlab` and `pillow` (fixtures only), `pytest`, `ruff`.
- **Frontend**: React 18, Vite, TypeScript (strict), Tailwind, React Router, TanStack Query, Recharts, lucide-react, `openapi-typescript`.
- **Infra**: Postgres+pgvector (Docker locally, Neon/Supabase deployed), Docker, Vercel (frontend), Render (backend).
- **No** LangGraph/LangChain, Kafka, Redis, Celery, microservices, ORMs other than SQLAlchemy, or extra UI kits. Add a dependency only if SPEC lists it or you justify it in one line in `docs/DECISIONS.md`.

## 5. Repo layout

```
billlens/
├─ AGENTS.md  Makefile  docker-compose.yml  .env.example  .gitignore
├─ docs/  SPEC.md  PHASES.md  DECISIONS.md   (append-only log of judgment calls)
├─ backend/
│  ├─ Dockerfile  requirements.txt  pytest.ini
│  ├─ app/
│  │  ├─ main.py config.py db.py models.py schemas.py
│  │  ├─ api/        health.py policies.py bills.py runs.py demo.py samples.py
│  │  ├─ llm/        client.py prompts.py
│  │  ├─ rag/        ingest.py embed.py retrieve.py grounding.py
│  │  ├─ agents/     base.py extraction.py policy.py audit.py action.py
│  │  ├─ tools/      registry.py bill_tools.py catalog_tools.py policy_tools.py calc_tools.py
│  │  ├─ engine/     normalizer.py rules.py simulator.py totals.py
│  │  ├─ orchestrator/  runner.py events.py replay.py
│  │  ├─ seed/       seed.py catalog.csv kb/*.md samples/ replays/
│  │  └─ scripts/    smoke.py record_replay.py eval.py make_fixtures.py
│  └─ tests/  fixtures/{bills,policies,golden}  test_*.py
└─ frontend/
   └─ src/ api/ (client.ts, schema.d.ts generated) hooks/ components/ pages/ mocks/ styles/
```

## 6. Coding conventions

- Python: type hints everywhere, Pydantic models for every boundary, `async def` for I/O, `ruff format` and `ruff check` clean. No bare `except:`. Money values are `float` rounded to 2 dp; compare with tolerance `abs(a-b) <= 1.0` (₹1).
- TypeScript: `strict`, no `any`, function components, Tailwind only (no CSS files except tokens), no inline magic colors (use tokens).
- API types are generated from FastAPI OpenAPI (`make types`). Never hand-write a type that exists in `schema.d.ts`.
- Every LLM call goes through `llm/client.py`. Never call an SDK directly elsewhere.
- Every agent runs through `agents/base.py::run_agent`. Never write a custom loop elsewhere.
- Log with `logging`, not `print` (except scripts).
- Small commits, message prefix `phase-N:`.

## 7. Working protocol (every task)

1. Read this file, then the SPEC sections named in the task.
2. Write a short plan (files to touch, tests to add). Keep it under 15 lines.
3. Implement. Stay inside the files your lane owns (see `docs/PHASES.md` lane table). If you need a change in someone else's file, write it in `docs/DECISIONS.md` and stop.
4. Run the acceptance commands in the task. Fix until green. Never claim success without running them.
5. If the spec is ambiguous: choose the simplest option that preserves the invariants, append one line to `docs/DECISIONS.md`, continue. Do not stop to ask unless blocked for more than 5 minutes.
6. Commit with `phase-N: <what>`.

## 8. Definition of done (any task)

- Acceptance commands pass; `make test` still green; `ruff` and `npm run build` clean.
- No new TODOs without a `docs/DECISIONS.md` entry.
- Failure path implemented: what happens if the LLM/DB/retrieval fails?
- UI work: verified at 390px (mobile) and 1280px (desktop) widths, in light and dark.

## 9. Never do

- Never let an LLM output become a ₹ number without a code path that computes or validates it.
- Never create a red finding from an agent. Never mutate `schemas.py` after tag `contracts-v1` unless you are the schemas owner.
- Never hardcode API keys, sample outputs into production code paths, or fake trace events.
- Never build: auth/accounts, payments, real insurer/hospital integrations, bill history dashboards, admin panels, model training, multi-language UI, bounding-box overlays on bills.
- Never over-engineer: no abstract base classes beyond `agents/base.py`, no plugin systems, no generic frameworks.

## 10. Glossary

- **TPA**: third-party administrator that processes insurance claims.
- **IRDAI**: Indian insurance regulator; publishes standard non-payable (excluded) item lists.
- **Non-payable**: items an insurer typically refuses (e.g. certain consumables like gloves and masks).
- **Room-rent cap**: policy limit on room charge per day (absolute ₹ or % of sum insured).
- **Proportionate deduction**: if the room rent exceeds the cap, other room-linked charges are cut by `cap / actual_rent`.
- **Co-pay**: percentage of the admissible claim the patient pays.
- **Sum insured (SI)**: the policy's maximum cover.
- **RMO**: resident medical officer. **INJ**: injection. **NS**: normal saline.
- **Deterministic floor**: the LLM-free audit path (I2).
- **Evidence**: a record `{id, type, text, meta}` created by a tool call. Findings and agent claims cite evidence IDs.
