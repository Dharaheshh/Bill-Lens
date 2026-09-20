import os
import json

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

golden_lines = [
 {"line_no":1, "raw_text":"ROOM RENT", "qty":5.0, "unit_price":8000.0, "amount":40000.0, "category":"room", "catalog_id":1, "canonical_name":"ROOM RENT", "match_method":"exact", "match_score":1.0, "service_date":"2024-01-10"},
 {"line_no":2, "raw_text":"SURGEON FEE", "qty":None, "unit_price":None, "amount":40000.0, "category":"professional_fee", "catalog_id":2, "canonical_name":"SURGEON FEE", "match_method":"exact", "match_score":1.0, "service_date":"2024-01-14"},
 {"line_no":3, "raw_text":"PHARMACY", "qty":None, "unit_price":None, "amount":30000.0, "category":"pharmacy", "catalog_id":3, "canonical_name":"PHARMACY CHARGES", "match_method":"exact", "match_score":1.0, "service_date":"2024-01-14"},
 {"line_no":4, "raw_text":"NON-PAYABLE CONSUMABLES", "qty":None, "unit_price":None, "amount":2000.0, "category":"consumable", "catalog_id":4, "canonical_name":"NON-PAYABLE CONSUMABLES", "match_method":"exact", "match_score":1.0, "service_date":"2024-01-10"},
 {"line_no":5, "raw_text":"INVESTIGATIONS", "qty":None, "unit_price":None, "amount":10000.0, "category":"investigation", "catalog_id":5, "canonical_name":"INVESTIGATIONS", "match_method":"exact", "match_score":1.0, "service_date":"2024-01-11"}
]

write_file("backend/tests/fixtures/golden/sample-a-ortho-insured.lines.json", json.dumps(golden_lines))

golden_expected = {
  "billed_total": 122000,
  "non_payable_total": 2000,
  "room_rent_deduction": 30000,
  "copay_amount": 9000,
  "insurer_pays": 81000,
  "patient_pays": 41000,
  "insurer_deductions_total": 32000,
  "planted_findings": [
    {"rule_code": "R3", "line_ids": [4]},
    {"rule_code": "C1"}
  ]
}

write_file("backend/tests/fixtures/golden/sample-a-ortho-insured.expected.json", json.dumps(golden_expected))
