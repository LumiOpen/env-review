-- consulting_target_intake
-- The case ID comes from the task prompt; the intake ID is discovered in state.
SELECT intake_id, case_id, process_id, validation_status, validation_outcome,
       change_version, cohort_case_count, validated_rework_case_count
FROM intake_requests
WHERE case_id = 'RFP-2024-000731';

-- consulting_history
SELECT r.rework_id, r.intake_id, r.rework_reason_code,
       r.validation_status, r.resolution_status, r.resubmission_number,
       r.validated_case_count, r.opened_ts, r.resolved_ts
FROM intake_rework_items AS r
JOIN intake_requests AS i ON i.intake_id = r.intake_id
WHERE i.case_id = 'RFP-2024-000731'
ORDER BY r.resubmission_number, r.opened_ts, r.rework_id;

-- consulting_case_count
-- Row count is evidence-history count; distinct case count and declared
-- validated_case_count separately check the case-level interpretation.
SELECT COUNT(*) AS validated_history_rows,
       COUNT(DISTINCT i.case_id) AS distinct_reportable_cases,
       SUM(r.validated_case_count) AS recorded_validated_case_total
FROM intake_requests AS i
JOIN intake_rework_items AS r ON r.intake_id = i.intake_id
WHERE i.case_id = 'RFP-2024-000731'
  AND i.change_version = 'pre_change'
  AND r.validation_status = 'validated';

-- ecommerce_dated_high_value
-- High-value means an order-band lower bound of at least $1,500.00.
-- Completed-sales scope and non-summary flag exclude dashboard totals.
SELECT s.sales_date, COUNT(*) AS source_cohort_rows,
       SUM(s.completed_transaction_count) AS completed_transactions
FROM sales_cohort_ledger AS s
JOIN merchant_accounts AS m ON m.merchant_id = s.merchant_id
WHERE m.legal_name = 'Northstar Outdoor Commerce, Inc.'
  AND s.processor_id = m.processor_id
  AND s.sales_date >= '2025-09-01'
  AND s.sales_date < '2025-10-01'
  AND s.cohort_scope = 'completed_sales'
  AND s.is_summary_row = 0
  AND s.order_amount_band_lower_cents >= 150000
GROUP BY s.sales_date
ORDER BY completed_transactions DESC, s.sales_date;

-- ecommerce_summary_control
SELECT s.cohort_scope, s.is_summary_row, s.order_amount_band_lower_cents,
       COUNT(*) AS rows, SUM(s.completed_transaction_count) AS reported_transactions
FROM sales_cohort_ledger AS s
JOIN merchant_accounts AS m ON m.merchant_id = s.merchant_id
WHERE m.legal_name = 'Northstar Outdoor Commerce, Inc.'
  AND s.sales_date >= '2025-09-01'
  AND s.sales_date < '2025-10-01'
GROUP BY s.cohort_scope, s.is_summary_row, s.order_amount_band_lower_cents
ORDER BY s.cohort_scope, s.order_amount_band_lower_cents;
