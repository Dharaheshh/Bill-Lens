import os
import json

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

runner_py = open("backend/app/orchestrator/runner.py").read()
if "run_policy_ingest" not in runner_py:
    policy_ingest_code = '''
async def run_policy_ingest(run_id: str, pdf_path: str, policy_id: str, document_id: str | None, session_id: str) -> None:
    async with AsyncSessionLocal() as session:
        ctx = RunContext(run_id=run_id, session=session)
        await _update_run(session, run_id, status="ingesting")
        try:
            async with asyncio.timeout(WATCHDOG_TIMEOUT):
                if not document_id: doc_id = await ingest_pdf(session, pdf_path, kind="policy", name=Path(pdf_path).name, session_id=session_id)
                else: doc_id = document_id
                terms = await run_policy_agent(session, str(doc_id), ctx)
                terms_dict = {k: v.model_dump() for k, v in terms.items()}
                await session.execute(update(Policy).where(Policy.id == policy_id).values(terms=terms_dict))
                await session.commit()
                await _update_run(session, run_id, status="done")
        except Exception as e:
            await _update_run(session, run_id, status="failed", error=str(e))
        finally:
            drop_queue(run_id)
'''
    with open("backend/app/orchestrator/runner.py", "a") as f:
        f.write(policy_ingest_code)

main_py = open("backend/app/main.py").read()
if "import json" not in main_py:
    main_py = "import json\nfrom fastapi import HTTPException\n" + main_py
    # need to implement the main.py fixes
    main_py = main_py.replace(
        "async def create_bill(file: UploadFile = File(...)) -> dict:",
        "async def create_bill(file: UploadFile = File(None), sample_id: str = Form(None)) -> dict:"
    )
    with open("backend/app/main.py", "w") as f:
        f.write(main_py)

print("Main patched.")
