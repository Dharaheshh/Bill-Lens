import io
import json
import logging
from typing import Any
import fitz
from PIL import Image
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas import ExtractedBill, BillLine
from app.orchestrator.events import RunContext
from app.llm.client import llm_client, LLMUnavailable

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "You transcribe Indian hospital bills into JSON. Rules: (1) Copy each charge row exactly as printed, keeping abbreviations and spelling. (2) One entry per printed charge row. Do NOT include department subtotals, page totals, or the grand total as lines. (3) Numbers are plain numbers: no ₹ symbol, no thousands separators. (4) If a value is unreadable or missing use null and add a note. Never guess. (5) Do not compute, correct, or reorder anything, including totals. (6) Dates in ISO 8601. (7) stated_total is the grand total printed on the bill; estimate_amount only if an admission estimate is printed. Return ONLY JSON matching the schema: {hospital_name, bill_date, stated_total, estimate_amount, lines: [{line_no, raw_text, qty, unit_price, amount, service_date, category_guess}], notes}"

class Correction(BaseModel):
    line_no: int
    raw_text: str | None = None
    qty: float | None = None
    unit_price: float | None = None
    amount: float | None = None

class RepairResponse(BaseModel):
    corrections: list[Correction] = []
    missing_lines: list[BillLine] = []
    remove_line_nos: list[int] = []

def process_file(file_path: str) -> list[bytes]:
    images = []
    try:
        if file_path.lower().endswith(".pdf"):
            doc = fitz.open(file_path)
            for page in doc[:3]:
                pix = page.get_pixmap(dpi=200)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                if max(img.width, img.height) > 2000:
                    img.thumbnail((2000, 2000))
                bio = io.BytesIO()
                img.save(bio, format="JPEG", quality=85)
                images.append(bio.getvalue())
        else:
            img = Image.open(file_path)
            if img.mode != "RGB":
                img = img.convert("RGB")
            if max(img.width, img.height) > 2000:
                img.thumbnail((2000, 2000))
            bio = io.BytesIO()
            img.save(bio, format="JPEG", quality=85)
            images.append(bio.getvalue())
    except Exception as e:
        logger.error(f"Image processing error: {e}")
    return images

def validate_totals_fn(lines: list[BillLine], stated_total: float | None) -> tuple[bool, float, list[dict]]:
    total = sum(l.amount for l in lines if l.amount is not None)
    diff = 0.0
    if stated_total is not None:
        diff = abs(total - stated_total)
    
    mismatches = []
    for l in lines:
        if l.qty is not None and l.unit_price is not None and l.amount is not None:
            if abs(l.qty * l.unit_price - l.amount) > 1.0:
                mismatches.append({"line_no": l.line_no, "expected": l.qty * l.unit_price, "actual": l.amount})
                
    valid = diff <= 1.0 and len(mismatches) == 0
    return valid, diff, mismatches

async def run_extraction_agent(
    file_path: str,
    file_hash: str,
    session: AsyncSession,
    ctx: RunContext,
) -> ExtractedBill:
    await ctx.emit("agent_start", {"agent": "extraction"})
    try:
        if not file_path:
            return ExtractedBill(hospital_name="Unknown", lines=[])
            
        images = process_file(file_path)
        if not images:
            return ExtractedBill(hospital_name="Unknown", lines=[])
            
        try:
            resp = await llm_client.vision(images, SYSTEM_PROMPT)
            bill = ExtractedBill.model_validate_json(resp)
        except LLMUnavailable:
            logger.warning("LLM Unavailable during extraction.")
            return ExtractedBill(hospital_name="Unknown", lines=[])
            
        for _ in range(2):
            valid, diff, mismatches = validate_totals_fn(bill.lines, bill.stated_total)
            if valid:
                break
                
            repair_prompt = f"The checksum failed: the extracted lines sum to {sum(l.amount or 0 for l in bill.lines)} but the bill states {bill.stated_total} (difference {diff}). Rows where qty × rate ≠ amount: {mismatches}. Re-read the image. Fix ONLY what the image clearly shows: return JSON {{'corrections':[{{'line_no':..,'raw_text':..,'qty':..,'unit_price':..,'amount':..}}],'missing_lines':[{{...BillLine...}}],'remove_line_nos':[...]}}. Change nothing else."
            await ctx.emit("agent_start", {"agent": "extraction_repair"})
            try:
                rep_resp = await llm_client.vision(images, repair_prompt)
                rep = RepairResponse.model_validate_json(rep_resp)
                
                # Apply corrections
                line_map = {l.line_no: l for l in bill.lines}
                for c in rep.corrections:
                    if c.line_no in line_map:
                        l = line_map[c.line_no]
                        if c.raw_text is not None: l.raw_text = c.raw_text
                        if c.qty is not None: l.qty = c.qty
                        if c.unit_price is not None: l.unit_price = c.unit_price
                        if c.amount is not None: l.amount = c.amount
                        
                for no in rep.remove_line_nos:
                    if no in line_map:
                        del line_map[no]
                        
                for ml in rep.missing_lines:
                    line_map[ml.line_no] = ml
                    
                bill.lines = sorted(line_map.values(), key=lambda x: x.line_no)
            except Exception as e:
                logger.error(f"Repair loop failed: {e}")
                break
                
        # Final validation check to set flag
        valid, _, mismatches = validate_totals_fn(bill.lines, bill.stated_total)
        if not valid:
            for l in bill.lines:
                if any(m["line_no"] == l.line_no for m in mismatches):
                    l.extraction_flag = True
                    
        return bill
    except Exception as e:
        logger.error(f"Extraction error: {e}")
        return ExtractedBill(hospital_name="Unknown", lines=[])
    finally:
        await ctx.emit("agent_end", {"agent": "extraction"})
