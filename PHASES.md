# PHASES.md: BillLens phase-wise build plan (for you + your Antigravity agents)

Times assume a **09:00 start** and a **16:50 submission**. If you are already behind, shift every time by the same amount and apply Cut Ladder items 1-3 (section 9) before you begin.

---

## 0. How to drive Antigravity for this project

(Antigravity's exact UI may differ from what I describe; adapt the intent, not the button names.)

1. **Put the docs in the repo first**: `AGENTS.md` at the repo root, `SPEC.md` and `PHASES.md` in `docs/`, plus an empty `docs/DECISIONS.md`. Many agentic IDEs auto-read `AGENTS.md`. If yours doesn't, add a workspace rule: *"Before any task, read AGENTS.md and the docs/SPEC.md sections named in the task."*
2. **One agent per lane, disjoint files** (table below). Run Lane A and Lane B as parallel agents/conversations. Parallel agents editing the same file is the number one way to lose an hour.
3. **Contract-first**: the backend agent finishes `schemas.py` and the OpenAPI stubs first; tag `contracts-v1`. Then the frontend agent generates TS types and builds against mocks. After the tag, only Lane A edits `schemas.py`.
4. **Prompt = copy from this file**, one phase prompt at a time. Each prompt names the SPEC sections, the files, the acceptance commands and what NOT to do. Agents work best with a bounded task and a runnable pass/fail check.
5. **Use planning mode for Phase 0-1 and the orchestrator (Phase 4)**; use fast mode for polish. Skim the agent's plan before approving. Reject plans that add frameworks (LangChain/LangGraph), extra services, or abstractions.
6. **Git discipline**: commit at every gate and tag it (`git tag phase-2-gate`). If an agent wrecks something, `git reset --hard <tag>` costs 30 seconds instead of 30 minutes.
7. **Let agents run the tests and the app** (terminal + browser agent) and show you results. Your review job is: run `make test`, click through the UI at phone width, read the trace.
8. **Bug prompt template**: *"Reproduce with a failing test first. Then fix. Then run `make test` and `ruff check`. Do not change unrelated files. Explain the root cause in two lines."*
9. **Keys**: put them in `.env` yourself. Never paste keys into prompts or commit them.

### Lane ownership

| Lane | Owns | Never touches |
|---|---|---|
| **A: backend / AI** | `backend/app/**` (except seed data and fixtures), `backend/tests/test_*.py`, `Makefile`, `docker-compose.yml` | `frontend/**` |
| **B: frontend** | `frontend/**` | `backend/**` |
| **C: data / fixtures / docs / PPT** | `backend/app/seed/catalog.csv`, `backend/app/seed/kb/**`, `backend/scripts/make_fixtures.py`, `backend/tests/fixtures/**`, `docs/**`, slides | `backend/app/{agents,engine,tools,rag,llm,orchestrator}/**` |
| **Shared rule** | `schemas.py` = Lane A only | |

Solo? Run the lanes one after another in the order A, B, C within each phase, and apply the cut ladder early.

---

## Phase 0: Foundations (09:00-09:35)

**Goal:** the skeleton runs locally and is deployed; DB, pgvector and the LLM all answer.

**You do (10 min, before prompting):**
- Neon (or Supabase) project → `CREATE EXTENSION vector;` → copy the connection string with `sslmode=require`.
- Get the LLM API key(s) and note base URL + model names for vision / agent / fast roles.
- Create the GitHub repo, a Vercel project and a Render account. Copy `.env.example` to `.env` and fill it.

**Prompt P0-A (Lane A, planning mode):**
```text
Read AGENTS.md and docs/SPEC.md sections 2, 11, 14.
Create the backend scaffold under backend/:
- FastAPI app (app/main.py) with CORS from ALLOWED_ORIGINS, config.py (pydantic-settings, all env vars in SPEC §14), db.py (async SQLAlchemy 2.x, psycopg v3), models.py with ALL tables in SPEC §2, startup that runs CREATE EXTENSION IF NOT EXISTS vector and create_all.
- GET /health returning {db, llm, embed} booleans.
- llm/client.py exactly per SPEC §11: chat(), vision(), tool-calling support, sha256 cache in llm_cache, 1 retry, fallback provider, semaphore(4), LLMUnavailable.
- rag/embed.py: fastembed singleton with embed_passages()/embed_query().
- scripts/smoke.py: prints PASS/FAIL for (1) DB connect, (2) vector insert+cosine query, (3) embedder returns 384 dims, (4) one text LLM call, (5) one vision LLM call using a tiny Pillow-generated image with text "TOTAL 1234".
- Dockerfile (pre-download the fastembed model at build), docker-compose.yml (pgvector/pgvector:pg16 + api), .env.example, .gitignore, Makefile with targets db, seed, test, dev-api, dev-web, types, fixtures, record-replay, eval, lint.
Do NOT implement agents, rules or endpoints beyond /health.
Acceptance: `make db && python -m app.scripts.smoke` prints 5 PASS; `uvicorn app.main:app` serves /health 200; `ruff check` clean.
```

**Prompt P0-B (Lane B, parallel):**
```text
Read AGENTS.md and docs/SPEC.md section 12.
Create frontend/ with Vite + React 18 + TypeScript strict + Tailwind + React Router + TanStack Query + Recharts + lucide-react + openapi-typescript.
- Design tokens from SPEC §12.1 (light + prefers-color-scheme dark), Inter font, Tailwind theme extended with the tokens.
- App shell: header (logo "BillLens", Live/Replay toggle stored in localStorage with try/catch), a Stepper (Coverage, Bill, Analysis, Verify, Result, Action), route stubs for every route in SPEC §12.2 showing a titled placeholder card.
- src/api/client.ts (fetch wrapper, X-Session-Id header, VITE_API_URL), src/hooks/useRunStream.ts (stub matching SPEC §12.3), env handling for VITE_USE_MOCKS.
- vercel.json SPA rewrite. npm script "gen:types".
Acceptance: `npm run build` passes; the app runs at 390px and 1280px widths with a working stepper and no console errors; dark mode works.
```

**Deploy (you or agent, after both prompts):**
- Render: New Web Service → Docker → `backend/`, add env vars, health check `/health`. Vercel: import repo, root `frontend/`, set `VITE_API_URL`.
- Add both deployed origins to `ALLOWED_ORIGINS`.

**Gate 09:35 (tag `phase-0-gate`):** both URLs live; `/health` all true on Render; smoke PASS locally. If Render's build runs out of memory with fastembed, note it in `DECISIONS.md` and switch to API embeddings for the deployed build later; do not stall here.

---

## Phase 1: Contracts + fixtures (09:35-10:35)

**Goal:** frozen data contracts, seeded reference data, and test fixtures with known planted issues. This is the most valuable non-code hour: everything after it is tested against it.

**Prompt P1-A (Lane A):**
```text
Read AGENTS.md and docs/SPEC.md sections 1, 2, 3, 10.3.
1) Write backend/app/schemas.py EXACTLY per SPEC §1. If you find a contradiction, fix it minimally and log it in docs/DECISIONS.md.
2) Implement seed/seed.py (idempotent): loads catalog.csv into catalog_items (embedding = fastembed of canonical_name + synonyms) and kb/*.md into documents(kind='kb') + chunks (split on '## ' headings). Include a tiny placeholder catalog.csv (10 rows) until Lane C delivers the real one.
3) Add ALL routes from SPEC §10.3 as stubs that return valid example payloads built from schemas (so OpenAPI is complete). GET /samples returns the 5 sample entries (ids from SPEC §13) with placeholder thumbs.
4) Verify /openapi.json contains RunResult, TraceEvent, PolicyTerm, Finding.
Acceptance: `make seed` works twice with no duplicates; `curl /openapi.json` contains those schemas; `ruff check` clean. Commit and tag `contracts-v1`.
```

**Prompt P1-B (Lane B, start after tag `contracts-v1`; until then read SPEC §1 and build the components):**
```text
Read AGENTS.md and docs/SPEC.md section 12 and the RunResult models in section 1.
1) After tag contracts-v1 run `npm run gen:types` (openapi-typescript against the running backend or a saved openapi.json) and use ONLY generated types.
2) Hand-write src/mocks/run-a.json: a valid RunResult (about 12 lines, 6 findings mixing red/amber/info from both origins, 8 evidence rows including a clause with page 7 and similarity, the waterfall from the SPEC §6 worked example: billed 122000, non_payable 2000, room_rent 30000, copay 9000, insurer 81000, patient 41000, a full action_pack). Also src/mocks/trace-a.json (about 40 TraceEvents across all 4 agents).
3) Build the reusable components against the mocks: SeverityPill, MoneyCountUp, AuditTable, SummaryCard, Waterfall (Recharts), WhyDrawer (bottom sheet on mobile), TraceTimeline (grouped by agent, expandable rows), PolicyTermsCard, LinesEditor, ActionPack tabs. Follow SPEC §12.2 and §12.4.
4) Mount the result screen at /run/mock/result using mocks when VITE_USE_MOCKS=true.
Acceptance: `npm run build`; /run/mock/result looks like a modern fintech product at 390px and 1280px, light and dark; drawer shows clause quote + page + similarity + calc; no `any`.
```

**Prompt P1-C (Lane C):**
```text
Read AGENTS.md and docs/SPEC.md sections 3 and 13.
1) Author backend/app/seed/catalog.csv (180-220 rows) per SPEC §3.1 with ref_source=DEMO_REFERENCE unless copied from a cited public list. Include the specific rows the planted issues need (ROOM RENT, NURSING CHARGES bundled_in=room_rent, CBC, INJ PANTOP 40MG, PARACETAMOL 650MG, non-payable consumables, etc.).
2) Author the 4 KB markdown files in backend/app/seed/kb/ per SPEC §3.2.
3) Write backend/scripts/make_fixtures.py that generates from per-sample Python specs: bill PNG/PDF (reportlab, 3 layouts, degrade sample C like a phone photo), golden/{id}.lines.json, golden/{id}.expected.json (planted findings + expected totals computed independently by simple arithmetic in the generator), and the two policy PDFs (fictional insurer "Demo Health Assure", distractor ICU limit and unrelated sub-limits per SPEC §13). Also golden/retrieval_eval.json (8 queries).
4) Copy generated sample bills and policies to backend/app/seed/samples/ with thumbnails.
Acceptance: `make fixtures` regenerates everything deterministically; open each PNG/PDF and visually check that it looks like a real bill/policy; expected.json totals are internally consistent (billed = sum of line amounts).
```

**Gate 10:35 (tag `phase-1-gate`):** `contracts-v1` exists; `make seed` fills the catalogue and KB; fixtures exist; the mock result screen renders.

---

## Phase 2: Deterministic core + extraction (10:35-12:05)

**Goal:** the LLM-free audit works and is tested; the Extraction Agent reads a bill. This is the **deterministic floor**.

**Prompt P2-A1 (Lane A):**
```text
Read AGENTS.md and docs/SPEC.md sections 4, 5, 6, 15.
Implement engine/normalizer.py, engine/rules.py (R1-R6), engine/totals.py, engine/simulator.py exactly as specified, as pure functions with no LLM or DB inside the rules and simulator (the normalizer takes an injected catalogue + embedder + optional llm re-ranker).
Write tests: test_simulator.py (both worked examples EXACTLY, plus uninsured, cap-not-exceeded, sum-insured cap), test_rules.py (trigger and non-trigger for every rule), test_golden.py (load tests/fixtures/golden/*.lines.json + the policy terms → run rules + simulator with NO LLM → planted findings must be present; totals equal expected.json), test_normalizer.py (>=90% correct without the LLM step on golden lines; print the score table so I can tune thresholds).
Acceptance: `make test` is fully green. Report the normalizer accuracy and the thresholds you tuned in docs/DECISIONS.md.
```

**Prompt P2-A2 (Lane A, after P2-A1):**
```text
Read AGENTS.md and docs/SPEC.md sections 7, 8.0, 8.1, 10.1.
Implement tools/registry.py (ToolResult, allowlists, JSON schemas from Pydantic args, 10s timeout), tools/bill_tools.py (validate_totals), orchestrator/events.py (RunContext, EvidenceStore, emit -> DB + asyncio queue), agents/base.py (run_agent exactly as SPEC §8.0), and agents/extraction.py per §8.1 (rasterize, downscale, vision call, validate_totals, <=2 repairs, fallbacks).
Add scripts to run it: `python -m app.scripts.extract <sample_id>` printing lines, checksum result and the emitted trace.
Tests: test_extraction_checksum.py with a mocked LLM (a) checksum OK first time, (b) mismatch then repaired, (c) still mismatched after 2 repairs -> lines flagged, (d) LLM down -> empty editable table + warning.
Acceptance: run the script on all three sample bills LIVE and paste the results in docs/DECISIONS.md (line counts vs golden, checksum result, tokens/latency). `make test` green.
```

**Prompt P2-B (Lane B):**
```text
Read AGENTS.md and docs/SPEC.md section 12.
Build /bill (BillDropzone with camera capture via <input type="file" accept="image/*,application/pdf" capture>, 3 sample cards from GET /samples, insured toggle), /run/:id/verify (LinesEditor: editable compact table, extraction_flag rows highlighted, checksum badge computed client-side, 'Looks right, run audit' calls PUT /runs/:id/confirm), and finish /run/:id/result (filters by severity, row click opens WhyDrawer, summary counters count up). Still against mocks unless the backend is up.
Acceptance: `npm run build`; walk Bill -> Verify -> Result on mocks at 390px and 1280px with no console errors.
```

**Prompt P2-C (Lane C):** tune the catalogue so the golden bills match well (add synonyms for misses reported in DECISIONS.md), write `docs/PPT_OUTLINE.md` skeleton (section 8 below), and draft the letter template text and the checklist lines the Action Agent fallback will use (plain, non-accusatory; put them in `backend/app/seed/templates/letter.md` and `checklist.md` with `{{placeholders}}`).

**Gate 12:05 (tag `phase-2-gate`):** `make test` green, especially `test_golden.py` with **no LLM**. The Extraction Agent has been run live on all three bills. The result screen renders on mocks.

---

## Phase 3: RAG + Policy Agent (12:05-13:20)

**Goal:** upload a policy PDF → cited, confirmed terms. This is the RAG centrepiece.

**Prompt P3-A (Lane A):**
```text
Read AGENTS.md and docs/SPEC.md sections 7 (search_policy, search_kb, get_clause, calc_room_cap), 8.2, 9, 10.3 (policy endpoints).
Implement rag/ingest.py, rag/retrieve.py (dense + keyword hybrid boost, numpy fallback), rag/grounding.py (validator exactly as specified), tools/policy_tools.py + calc_tools.py + catalog_tools.py, agents/policy.py (4 terms in parallel via run_agent), and the real POST /policies, GET /policies/{id}, PUT /policies/{id}/terms endpoints (PUT resolves pct_si -> absolute cap and returns ResolvedPolicy). Policy ingest runs as a background run of kind policy_ingest that emits trace events.
Tests: test_grounding.py (all cases in SPEC §15). Script `python -m app.scripts.eval` prints hit@3 over golden/retrieval_eval.json and, for both sample policies, the four extracted terms with page + similarity.
Acceptance: policy-a yields room cap 5000/day (absolute), copay 10, SI 500000, proportionate true, each grounded with page + quote; policy-b yields cap kind pct_si 1% -> 5000 via calc_room_cap, copay 20, proportionate not found or false. Report hit@3 in DECISIONS.md. `make test` green.
```

**Prompt P3-B (Lane B):**
```text
Read AGENTS.md and docs/SPEC.md section 12.
Build /coverage: PolicyPicker (upload PDF, 2 sample policies, 'No insurance'), after start show a compact TraceTimeline fed by useRunStream, then PolicyTermsCard with the 4 terms: value input, status badge (Extracted / Manual / Not found), the verbatim quote block with page and similarity, 'Confirm terms' calling PUT /policies/:id/terms. Not-found terms show a manual input. Implement the real useRunStream (EventSource with since=, retry twice, polling fallback, reducer deduped by seq). Turn off mocks for policy endpoints.
Acceptance: uploading policy-a.pdf shows the 4 terms filling in live with quotes; killing the SSE (block the endpoint) still updates through polling.
```

**Prompt P3-C (Lane C):** extend the KB if retrieval misses (`eval` output), run the policy PDFs through the ingest and check the chunks look sane (headings and pages), and prepare 3 phone-photo variants of sample C in case the live camera demo is attempted.

**Gate 13:20 (tag `phase-3-gate`):** both sample policies produce grounded, confirmable terms; record hit@3 (this becomes a real number for your slide).

---

## Integration checkpoint + lunch (13:20-13:45)

Run this path by hand: choose policy-a → confirm terms → choose sample A → verify → (audit stage may still be partial). Fix breakages found before lunch is over. Commit. Eat.

---

## Phase 4: Orchestration, Audit Agent, Action Agent, trace (13:45-15:00)

**Goal:** the full agentic pipeline with live trace, end to end.

**Prompt P4-A (Lane A, planning mode):**
```text
Read AGENTS.md and docs/SPEC.md sections 7 (remaining tools), 8.3, 8.4, 10.1-10.4.
Implement: tools/catalog_tools.py extras (lookup_reference_price), bill_tools.py extras (find_duplicates, get_line_context), agents/audit.py (uncertain-set selection, per-line run_agent in parallel with a semaphore of 4, proposal validator, merge rules exactly as specified: confirm/dismiss(amber only)/ask), agents/action.py (structured questions + checklist, code-built letter template, optional LLM polish with the number-equality check, template fallback), orchestrator/runner.py (policy_ingest, Phase 1, Phase 2, watchdog 120s, every stage wrapped with fallback -> warning event), the real POST /bills, POST /runs, GET /runs/{id}, PUT /runs/{id}/confirm, GET /runs/{id}/stream (sse-starlette, backlog then live, heartbeat), GET /runs/{id}/events, GET /runs/{id}/result, and orchestrator/replay.py + scripts/record_replay.py + POST /demo/{sample_id}.
Simulator stage must emit the C1 finding with clause + calc evidence. Summary.agent_stats must contain REAL counts.
Tests: test_agent_validators.py, test_pipeline_e2e.py (mocked LLM), test_llm_down.py (rules-only result when every LLM call fails).
Acceptance: `python -m app.scripts.record_replay sample-a-ortho-insured` completes live in <=60s and writes the replay file; the trace contains events from extraction, policy, audit, action; `make test` green.
```

**Prompt P4-B (Lane B):**
```text
Read AGENTS.md and docs/SPEC.md section 12.
Wire the whole flow to the real API: Coverage -> Bill -> /run/:id (full-width TraceTimeline using useRunStream, group by agent, status icons, expandable payloads, retrieval rows with quote + similarity, footer with real agent_stats) -> auto-navigate to Verify when status is awaiting_verification -> after confirm, keep streaming the audit phase -> auto-navigate to Result when done. Finish Waterfall, SummaryCard counters and ActionPack (ranked questions with copy, editable letter with copy + print stylesheet, checklist). Add 'View agent trace' collapsible on the Result screen. Implement the Live/Replay toggle: Replay calls POST /demo/:sample_id instead of the live endpoints. Remove mocks from the default path (keep VITE_USE_MOCKS).
Acceptance: full run for sample A from the UI in <=60s in Live mode; Replay mode works with the LLM key removed from the backend env; 390px and 1280px verified; no console errors.
```

**Prompt P4-C (Lane C):** build the PPT from `docs/PPT_OUTLINE.md` with placeholders, capture screenshots of the Coverage terms card, the trace, the result table + waterfall and the WhyDrawer as soon as B's wiring works, and script the 3-minute demo in `docs/DEMO_SCRIPT.md` (section 7 below).

**Gate 15:00 (tag `phase-4-gate`):** end to end works live in ≤60 s, replay recorded for all three samples (`make record-replay`), `make test` green. If the Audit Agent isn't stable, apply Cut Ladder item 4 now.

---

## Phase 5: Polish + FREEZE (15:00-15:30)

- Responsive pass on every screen (390 / 768 / 1280); dark mode sanity; empty, error and loading states; focus and ARIA on the drawer/tabs.
- Landing hero copy and the phone-framed preview using a real screenshot.
- README with the architecture diagram, run instructions, the trust model (I1-I4), and a short "what's synthetic" note.
- Add a Live/Replay explanation tooltip; add "Synthetic demo data" footer.
- **15:30 FEATURE FREEZE.** After this: bug fixes only.

---

## Phase 6: Hardening (15:30-16:10)

1. Run each sample end to end in Live mode twice (the second run hits the LLM cache) and once in Replay. Fix defects only.
2. Run `python -m app.scripts.eval` and a findings check against the golden files. Record the measured numbers: extraction line accuracy on 3 bills, retrieval hit@3, planted-issue recall/precision. **Use only numbers you measured** on the slide.
3. Test one live phone-camera capture at the demo venue's lighting, plus the pre-tested backup photo.
4. Final deploy (Render + Vercel), warm the Render instance, confirm `/health` and one full Replay on the deployed URL.
5. Record a **backup screen-recording** of the full 3-minute flow. Push the repo (no secrets; check `git log -p | grep -i key`).
6. Confirm `docker compose up` works from a clean clone (README steps).

---

## Phase 7: PPT + submission form (16:10-16:35)

PPT (8 slides, `docs/PPT_OUTLINE.md`): (1) The problem at the discharge desk. (2) The insight: audit from the insurer's point of view before paying. (3) Demo screenshots (result + waterfall). (4) Architecture: 4 agents + tools + RAG + engine. (5) Trust model: "Agents investigate. Evidence verifies. Code decides." with the I1-I4 guardrails. (6) Measured results (from Phase 6, labelled synthetic). (7) Scalability and roadmap: TPAs, employer benefit desks, ombudsman helpers, on-device OCR + PII redaction, official list sync. (8) Team + links (GitHub, deployed URL, video).
Submission form: team details, title "BillLens: Agentic Hospital Bill & Claim Auditor", GitHub URL, deployed URL, PPT.

---

## Phase 8: Rehearse + submit (16:35-16:50)

Three full run-throughs of the 3-minute demo using the script below, once with the network off (Replay). **Submit by 16:50**, not 16:59. After submitting, leave the deployed URL untouched.

---

## 7. The 3-minute demo script

1. **(0:00-0:20) Problem**: "At discharge, families get a 47-line bill full of abbreviations and minutes to pay. Weeks later the insurer deducts items nobody warned them about."
2. **(0:20-0:50) Policy**: choose the sample policy; the Policy Agent's trace runs; the terms card fills with the quote and page: "Room rent limited to ₹5,000 per day, page 7". Confirm.
3. **(0:50-1:30) Bill → trace**: upload the bill; show the four agents working live, the checksum tool call, the retrieval rows with similarity, the Audit Agent investigating two ambiguous lines. Say "these events are real, not animation".
4. **(1:30-2:20) Result**: rows tint red/amber/green, counters climb. Open a red room-rent flag → quote, page, ₹ math. Open an amber duplicate → the agent's cited rationale.
5. **(2:20-2:45) Waterfall**: billed → non-payables → room-rent deduction → co-pay → "insurer likely pays ₹A, you pay ₹B".
6. **(2:45-3:00) Action + close**: desk questions and the letter. "Agents investigate. Evidence verifies. Code decides."

**Likely judge questions (prepare answers):** why agents instead of a pipeline (conditional tool use; extraction self-correction; show the trace) · what stops a hallucinated clause (quote must exist in a retrieved chunk, number must be in the quote, user confirms) · what if retrieval is wrong (quote + page are shown; manual entry; measured hit@3) · are prices legal caps (no: reference benchmarks, amber, labelled) · privacy (synthetic now; production: on-device OCR + redaction, consent, TTL) · business model (TPAs, employer benefits, insurer pre-claim checks) · what if the LLM is down (deterministic floor + replay).

---

## 8. `docs/PPT_OUTLINE.md` (seed for Lane C)

Slide titles as in Phase 7, each with: one headline sentence, one visual (screenshot or diagram), and at most 3 bullets. Slide 4's diagram is the architecture from `AGENTS.md` section 3. Keep fonts large; no paragraph text.

---

## 9. Cut ladder (cut in this order when behind; never cut the "never" list)

1. Claim-strategy/checklist tab.
2. pgvector → in-memory numpy cosine (SPEC §9 fallback).
3. Action Agent LLM → template-only letter and questions.
4. Audit Agent tool loop → single structured call over pre-retrieved evidence (still validated, still cited).
5. Policy upload → the two sample policies only.
6. Verify screen → read-only with `auto_confirm` default.
7. Live camera capture → sample bills + one pre-shot photo.

**NEVER cut:** the deterministic floor (I2) and `test_golden.py`, the WhyDrawer with evidence, the waterfall, the trace (Replay-only is acceptable), the grounding validator, the Live/Replay toggle.

## 10. Risk watchlist (check at each gate)

- **Render memory / cold start** (fastembed): warm the instance before demoing; fallback to API embeddings.
- **Vision extraction quality on the phone-photo sample**: keep the checksum repair loop bounded; the user verify step is the safety net.
- **Retrieval picking the ICU clause instead of the normal-room clause**: the distractor is planted on purpose; tune queries and the hybrid boost, and log it in DECISIONS.md.
- **Agent merge bugs turning amber to red or altering ₹**: covered by `test_agent_validators.py`. Do not remove it.
- **Time**: if a phase overruns by more than 20 minutes, apply the next item on the cut ladder immediately rather than at the next gate.
