import csv
import os

os.makedirs('app/seed', exist_ok=True)

categories = [
    ("room", ["ROOM RENT", "ICU CHARGES", "AC ROOM"]),
    ("nursing", ["NURSING CHARGES", "RMO CHARGES", "CARE CHARGES"]),
    ("professional_fee", ["CONSULTATION", "SURGEON FEE", "ANESTHETIST FEE"]),
    ("procedure", ["SURGERY", "OPERATION THEATRE CHARGES", "OT CHARGES"]),
    ("pharmacy", ["INJ PANTOP 40MG", "PARACETAMOL 650MG", "NS 500ML", "RL 500ML", "AUGMENTIN 625MG", "CEFTRIAXONE 1G INJ", "PAN 40", "PCM 500", "TAB PCM", "SYP PCM"]),
    ("consumable", ["GLOVES", "MASK", "SYRINGE", "IV SET", "COTTON", "BANDAGE", "ADMISSION KIT", "HAND SANITIZER", "THERMOMETER", "BP CUFF DISPOSABLE", "TOILETRIES", "SHOE COVERS", "CAPS"]),
    ("investigation", ["CBC", "X-RAY", "MRI", "CT SCAN", "BLOOD SUGAR", "LIPID PROFILE", "ECG", "KFT", "LFT", "URINE ROUTINE"]),
    ("implant", ["STENT", "SCREW", "PLATE", "PACEMAKER"]),
    ("other", ["REGISTRATION FEE", "DIET CHARGES", "BIOMEDICAL WASTE", "SERVICE CHARGE"])
]

rows = []
for cat, items in categories:
    for item in items:
        # non_payable logic
        non_payable = 1 if cat == "consumable" or cat == "other" else 0
        reason = "Commonly listed as non-payable consumable in standard insurer exclusion lists (verify against the official list before production use)" if non_payable else ""
        bundled_in = "room_rent" if cat == "nursing" else ""
        max_per_day = 1 if cat in ["room", "nursing", "professional_fee"] else ""
        rows.append([item, cat, item, non_payable, reason, bundled_in, max_per_day, 100, 5000, "INR", "DEMO_REFERENCE"])

# Multiply rows to reach ~200
base_len = len(rows)
target_len = 200
for i in range(base_len, target_len):
    cat, items = categories[i % len(categories)]
    item = f"{items[i % len(items)]} VARIANT {i}"
    non_payable = 1 if cat == "consumable" or cat == "other" else 0
    reason = "Commonly listed as non-payable consumable in standard insurer exclusion lists (verify against the official list before production use)" if non_payable else ""
    bundled_in = "room_rent" if cat == "nursing" else ""
    max_per_day = 1 if cat in ["room", "nursing", "professional_fee"] else ""
    rows.append([item, cat, item, non_payable, reason, bundled_in, max_per_day, 100, 5000, "INR", "DEMO_REFERENCE"])

with open('app/seed/catalog.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(["canonical_name", "category", "synonyms", "non_payable", "non_payable_reason", "bundled_in", "max_per_day", "ref_price_low", "ref_price_high", "ref_unit", "ref_source"])
    writer.writerows(rows)
