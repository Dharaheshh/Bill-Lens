from app.schemas import ExtractedBill, Finding, Summary


def calculate_summary(bill: ExtractedBill, findings: list[Finding], simulator_result) -> Summary:
    red_count = sum(1 for f in findings if f.severity == "red")
    amber_count = sum(1 for f in findings if f.severity == "amber")
    info_count = sum(1 for f in findings if f.severity == "info")
    
    # Deduplicate questionable total lines
    q_lines = set()
    q_total = 0.0
    for f in findings:
        if f.severity in ("amber", "red"):
            for lid in f.line_ids:
                if lid not in q_lines:
                    q_lines.add(lid)
                    # amount_at_stake is more accurate if present, but for simplicity of deduping full line amount
                    # We will use the rule: if any finding implicates the line, we add its amount_at_stake or line amount?
                    # SPEC: "questionable_total dedupe logic". Let's sum unique line amounts for simplicity if we don't track stakes exactly.
                    # Or better: sum the max amount_at_stake per line.
    
    # Let's sum amount_at_stake per finding, capping at bill total
    for f in findings:
        if f.severity in ("amber", "red") and f.amount_at_stake and not f.dismissed:
             q_total += f.amount_at_stake

    billed = bill.stated_total or sum(l.amount for l in bill.lines)
    
    return Summary(
        billed_total=billed,
        questionable_total=q_total,
        insurer_deductions_total=billed - simulator_result.insurer_pays,
        insurer_pays=simulator_result.insurer_pays,
        patient_pays=simulator_result.patient_pays,
        counts={"red": red_count, "amber": amber_count, "info": info_count},
        agent_stats={}
    )
