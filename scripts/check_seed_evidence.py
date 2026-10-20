"""Recheck seed findings using text parsing and our own read-only SELECT queries.

Run after `python -m eval_audit.acquire`. No corpus Python is imported or run.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import yaml

BASE = Path("env/XiaomiMiMo/MiMo-V2.6-RL-oss")
CACHE = Path("data/mimo")
REVISION = "e8e81e4945270b6212204bad99de1e598f7fb077"


def query(task, system, sql, parameters=()):
    path = CACHE / "general/envs" / task / "system" / system / "state.db"
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as connection:
        rows = connection.execute(sql, parameters).fetchall()
    return {"source": str(path.relative_to(CACHE)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "query": sql, "parameters": list(parameters), "rows": rows}


def main():
    quoted = 0
    for path in sorted((BASE / "findings").glob("*.yaml")):
        finding = yaml.safe_load(path.read_text())
        assert finding["revision"] == REVISION, "Seed checker requires its original revision"
        for evidence in finding["evidence"]:
            text = (CACHE / evidence["source"]).read_text()
            if "line_start" in evidence:
                lines = text.splitlines()
                assert 1 <= evidence["line_start"] <= evidence["line_end"] <= len(lines)
                assert "\n".join(lines[evidence["line_start"]-1:evidence["line_end"]]) == evidence["quote"]
            else:
                value = json.loads(text)
                for segment in evidence["json_pointer"].split("/")[1:]:
                    value = value[segment]
                assert evidence["quote"] in value
            quoted += 1

    finance = "s3k_0988_finance_insurance_zh_t1_rl_005"
    fairfax = "s3k_0000_accounting_audit_tax_en_t1_rl_008"
    hospitality = "s3k_1587_hospitality_fnb_zh_t4_rl_003"
    manufacturing = "s3k_2328_manufacturing_quality_zh_t3_rl_007"
    checks = [
        query(finance, "yonyou_hedge_approval", "SELECT case_id,batch_id,company_id,product_id,contract_id FROM hedge_approval_cases WHERE case_id=?", ("HAC-2025-0317-01",)),
        query(fairfax, "dealcloud_disposition_workspace", "SELECT structure_code,transaction_status FROM disposition_transactions WHERE transaction_id=? AND case_id=?", ("DC-TXN-25Q3-024", "CASE-FAIRFAX3-2025Q3")),
        query(fairfax, "dealcloud_disposition_workspace", "SELECT COUNT(*) FROM closing_requirements WHERE transaction_id=? AND active_flag=1", ("DC-TXN-25Q3-024",)),
        query(fairfax, "sharepoint_tax_governance_library", "SELECT status,decision_code FROM decision_records WHERE decision_id=? AND case_id=?", ("DEC-2025-017", "CASE-FAIRFAX3-2025Q3")),
        query(hospitality, "beverage_variance_workbench", """SELECT v.sku_id,v.sku_name,v.base_unit,v.variance_quantity_base,v.variance_cost_fen,v.quantity_threshold_base,v.amount_threshold_fen FROM reconciliation_runs r JOIN sku_variance_results v ON v.run_id=r.run_id WHERE r.period_id='PERIOD-2024-10' AND r.org_id='ORG-HIRJ-LBB' AND r.run_status='FINAL' AND ((ABS(v.variance_cost_fen)>=v.amount_threshold_fen AND ABS(v.variance_quantity_base)<v.quantity_threshold_base) OR (ABS(v.variance_quantity_base)>=v.quantity_threshold_base AND ABS(v.variance_cost_fen)<v.amount_threshold_fen)) ORDER BY v.sku_id"""),
        query(manufacturing, "avt_quality_data_mart", "SELECT COUNT(*) FROM source_reconciliation WHERE ecn_id=? AND event_date<=? AND reconciliation_result='unmatched'", ("ECN-2025-017", "2025-03-18")),
    ]
    expected = [
        [("HAC-2025-0317-01", "BATCH-2025-CU-01", "ORG_JCC_600362", "PRODUCT_CATHODE_COPPER", "SHFE-CU2509")],
        [("installment_sale", "recommended")], [(7,)], [("approved", "INSTALLMENT_ASSET_SALE")],
        [("SKU-SOFTDRINK-COCA-COLA", "可口可乐", "CAN", 1, 620, 1, 1000),
         ("SKU-SPIRIT-JW-BLACK", "黑方 Johnnie Walker Black Label", "ML", 15, 1170, 30, 1000)],
        [(0,)],
    ]
    for check, rows in zip(checks, expected):
        assert check["rows"] == rows, check["source"]
    weights = []
    for task in [fairfax, hospitality]:
        metadata = json.loads((CACHE / "general/envs" / task / "verifier_meta.json").read_text())
        substantive = sum(item.get("weight", 1) for item in metadata["items"] if item["method"] == "llm")
        sanity = sum(item.get("weight", 1) for item in metadata["items"] if item["method"] == "rule")
        assert abs(substantive - 1) < 1e-9 and sanity == 1
        weights.append({"task_id": task, "substantive_weight": substantive, "sanity_weight": sanity,
                        "score_if_substantive_zero_and_sanity_one": sanity/(substantive+sanity)})
    result = {"revision": REVISION, "method": "text comparison, read-only SQL, independent arithmetic",
              "original_grader_executed": False, "verified_quotes": quoted, "checks": checks, "weights": weights}
    Path("reports").mkdir(exist_ok=True)
    Path("reports/seed-evidence.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"Verified {quoted} quotes, {len(checks)} read-only queries, and {len(weights)} weighting calculations.")


if __name__ == "__main__":
    main()
