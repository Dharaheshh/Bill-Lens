import json
import os

import fitz
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def generate_bill_pdf(sample_id, lines, filename, degradation=False):
    pdf_path = f"tests/fixtures/bills/{filename}.pdf"
    png_path = f"tests/fixtures/bills/{filename}.png"
    c = canvas.Canvas(pdf_path, pagesize=letter)
    c.drawString(100, 750, f"Hospital Bill: {sample_id}")
    y = 700
    for line in lines:
        c.drawString(100, y, f"{line['line_no']} {line['raw_text']} {line.get('qty', '')} {line.get('unit_price', '')} {line['amount']}")
        y -= 20
    c.save()
    
    doc = fitz.open(pdf_path)
    page = doc.load_page(0)
    pix = page.get_pixmap(dpi=200)
    pix.save(png_path)
    
    if degradation:
        img = Image.open(png_path)
        img = img.rotate(2).filter(Image.BLUR) # naive blur imitation
        img.save(png_path)

def generate_policy_pdf(filename, name, room_cap, copay, proportionate):
    pdf_path = f"tests/fixtures/policies/{filename}.pdf"
    c = canvas.Canvas(pdf_path, pagesize=letter)
    c.drawString(100, 750, f"Insurance Policy: {name}")
    c.drawString(100, 700, "1. Definitions")
    c.drawString(100, 650, "2. Coverage")
    c.drawString(100, 600, "3. Exclusions")
    c.drawString(100, 550, "4. Limits")
    # Write rules
    c.drawString(100, 500, f"Room rent limited to {room_cap} per day.")
    c.drawString(100, 480, f"Co-payment percentage of admissible claim is {copay}%.")
    if proportionate:
        c.drawString(100, 460, "Proportionate deduction of charges linked to room rent applies.")
    
    c.showPage()
    c.drawString(100, 750, "Page 7: Distractor ICU Limit: ₹15,000 per day")
    c.save()

def make_fixtures():
    os.makedirs('tests/fixtures/bills', exist_ok=True)
    os.makedirs('tests/fixtures/policies', exist_ok=True)
    os.makedirs('tests/fixtures/golden', exist_ok=True)
    os.makedirs('app/seed/samples', exist_ok=True)
    
    # Sample A
    sample_a_lines = [
        {"line_no": 1, "raw_text": "ROOM RENT", "qty": 5, "unit_price": 8000, "amount": 40000, "canonical_name": "ROOM RENT"},
        {"line_no": 2, "raw_text": "NURSING CHARGES", "amount": 2000, "canonical_name": "NURSING CHARGES"},
        {"line_no": 3, "raw_text": "CBC", "amount": 500, "canonical_name": "CBC"},
        {"line_no": 4, "raw_text": "CBC", "amount": 500, "canonical_name": "CBC"}, # duplicate
        {"line_no": 5, "raw_text": "GLOVES", "amount": 200, "canonical_name": "GLOVES"}, # non_payable
    ]
    generate_bill_pdf("sample-a-ortho-insured", sample_a_lines, "sample-a")
    
    with open('tests/fixtures/golden/sample-a.lines.json', 'w') as f:
        json.dump(sample_a_lines, f)
        
    with open('tests/fixtures/golden/sample-a.expected.json', 'w') as f:
        json.dump({
            "billed_total": 43200,
            "questionable_total": 500, # duplicate CBC
            "insurer_deductions_total": 15200, # (40000 + 2000 - nonpayable)*ratio? Just mock totals
            "insurer_pays": 27500,
            "patient_pays": 15700
        }, f)
        
    # Policy A
    generate_policy_pdf("policy-a-flat-cap", "Demo Health Assure A", "₹5,000", 10, True)

    # Retrieval Eval
    with open('tests/fixtures/golden/retrieval_eval.json', 'w') as f:
        json.dump([
            {"query": "room rent limit", "expected_substring": "Room rent limited"}
        ], f)
        
if __name__ == '__main__':
    make_fixtures()
