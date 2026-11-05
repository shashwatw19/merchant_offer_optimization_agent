# Merchant Offer Optimization Agent

An enterprise-grade, evidence-led campaign investigation and optimization system built using the **Google Agent Development Kit (ADK) 2.13.0**, **Python 3.14**, **Google Cloud BigQuery**, and **Gemini**.

The system automates the investigation of underperforming merchant campaigns, establishes auditable facts from structured BigQuery data and unstructured feedback, evaluates root-cause hypotheses, and simulates policy-compliant spend threshold adjustments without human bias or unauthorized changes.

---

## 1. System Architecture

```
                                    +------------------------------+
                                    |        campaign.yaml         |
                                    | (Policy, Tools, Guardrails)  |
                                    +--------------+---------------+
                                                   |
                                                   v
+------------------------+             +-----------+------------+             +------------------------+
|    alert.py (CLI)      |             |     src/core/config    |             |  BigQuery: offers_gold |
| Deterministic Rules    +------------>|  Pydantic AppConfig    |<----------->| - gold_campaign_results|
| R1, R2, R3             |             +-----------+------------+             | - gold_merchant_profile|
+------------------------+                         |                          | - alerts               |
                                                   v                          +------------------------+
+--------------------------------------------------+---------------------------------------------------+
|                           Google ADK 2.13.0 Orchestration Engine                                      |
|                                                                                                      |
|   +------------------------------------+          +----------------------------------------------+   |
|   |   LlmAgent (gemini-2.5-flash)      |          |     InMemoryRunner & SessionManager          |   |
|   |   - Strict System Instruction      |<-------->|     - Deterministic Session Isolation        |   |
|   |   - Bounded Function Calling       |          |     - Lifecycle Event Stream Processing      |   |
|   +-----------------+------------------+          +----------------------+-----------------------+   |
|                     |                                                    |                           |
|                     v                                                    v                           |
|   +-----------------+------------------+          +----------------------+-----------------------+   |
|   |    9 Bounded Read-Only Tools       |          |         ExecutionTracer                      |   |
|   | 1. get_campaign_terms              |          | - Appends JSONL audit traces to              |   |
|   | 2. get_campaign_performance        |          |   logs/traces/trace_YYYYMMDD.jsonl           |   |
|   | 3. get_spend_distribution          |          +----------------------------------------------+   |
|   | 4. get_customer_reviews            |                                 |                           |
|   | 5. get_merchant_feedback           |                                 v                           |
|   | 6. get_delivery_metrics            |          +----------------------+-----------------------+   |
|   | 7. get_comparable_campaigns        |          |        InvestigationReport Validator         |   |
|   | 8. validate_proposal               |          | - Pydantic Contract Enforcement              |   |
|   | 9. simulate_campaign_change        |          | - human_approval_required = True             |   |
|   +------------------------------------+          +----------------------------------------------+   |
+------------------------------------------------------------------------------------------------------+
```

---

## 2. Deterministic Alert Rules

Alerts serve as investigation triggers computed deterministically in SQL/Python:

| Rule | Metric | Threshold | Business Meaning & Target Scenario |
|---|---|---|---|
| **R1** | `redemption_rate` | `< 5.0%` | Low redemption friction (e.g. *Spice Route Kitchen*: median bill ₹750 vs. ₹2,000 threshold). |
| **R2** | `period_redemption_drop_pct` | `>= 50% drop` (or `< 0.50 * baseline`) | Sudden collapse in redemptions between comparable periods (e.g. *Glow Salon*: renovation/closure). |
| **R3** | `existing_customer_share_pct` | `>= 75.0%` | Low customer acquisition in new-customer campaigns (e.g. *Urban Threads*: existing customer dominance or wrong-city targeting). |

---

## 3. The 9 Bounded Agent Tools

All tools are read-only, strongly typed, and return source evidence references:

1. **`get_campaign_terms(campaign_id)`**: Retrieves configured minimum spend, cashback percent, cap, and budget from `offers_silver.campaigns`.
2. **`get_campaign_performance(campaign_id)`**: Retrieves targeted, delivered, and awarded redemptions from `offers_gold.gold_campaign_results`.
3. **`get_spend_distribution(merchant_id)`**: Retrieves merchant ticket size percentiles, average bill, and median spend from `offers_gold.gold_merchant_spend_profile`.
4. **`get_customer_reviews(merchant_id, limit)`**: Retrieves dated customer reviews with review IDs and ratings from `offers_silver.customer_reviews`.
5. **`get_merchant_feedback(merchant_id, limit)`**: Retrieves relationship manager notes and incident logs from `offers_silver.merchant_feedback`.
6. **`get_delivery_metrics(campaign_id)`**: Computes notification delivery success rates and customer-outlet city mismatch percentages from `offers_silver.offer_sends`.
7. **`get_comparable_campaigns(campaign_id, limit)`**: Benchmarks campaign performance against peer merchants in the same category.
8. **`validate_proposal(proposed_min_spend, cashback_pct, cashback_cap)`**: Checks proposed changes against policy allowlists and budget ceilings defined in `campaign.yaml`.
9. **`simulate_campaign_change(campaign_id, min_spend)`**: Replays proposed spend thresholds strictly against *targeted customers' historical posted card payments*. Computes retrospective liability deltas and budget safety without forecasting future uplift.

---

## 4. Guardrails & Compliance

- **No Unauthorized Updates:** All tools are strictly read-only. The agent cannot edit BigQuery campaign records or contact customers.
- **Deterministic Pre-Validation:** `simulate_campaign_change` rejects non-allowlisted thresholds before executing BigQuery replay queries.
- **Targeted Cohort Constraint:** Replay simulations only count card transactions belonging to customers who actually received campaign notifications (`offer_sends`).
- **No Predictive Revenue Claims:** The agent prompt and Pydantic validator strictly forbid representing historical replays as future forecasting (`future_incremental_spend = null`).
- **Human in the Loop:** Every generated report requires human review and sign-off before operational changes are enacted (`human_approval_required = true`).

---

## 5. Output Contract

Investigations emit a validated JSON report adhering to this contract:

```json
{
  "alert_id": "A1001",
  "campaign_id": "CMP131",
  "status": "COMPLETE",
  "findings": [
    {
      "observation": "Redemption rate is 4.0% against 150 targeted customers.",
      "evidence": ["bq:prj-imp-act-campaign.offers_gold.gold_campaign_results:CMP131"]
    },
    {
      "observation": "Median merchant card ticket size is ₹750 against a ₹2,000 threshold.",
      "evidence": ["bq:prj-imp-act-campaign.offers_gold.gold_merchant_spend_profile:M001"]
    }
  ],
  "hypotheses": [
    {
      "text": "The ₹2,000 minimum spend creates excessive friction for typical dining bills.",
      "status": "SUPPORTED",
      "rationale": "Over 70% of historical transactions are under ₹1,200."
    }
  ],
  "proposal": {
    "type": "TEST",
    "min_spend": 1500,
    "cashback_pct": 10,
    "cashback_cap": 200,
    "rationale": "Historical replay at ₹1,500 qualifies 12 additional transactions with total liability of ₹3,600, well within the ₹40,000 budget."
  },
  "simulation_type": "HISTORICAL_REPLAY",
  "future_incremental_spend": null,
  "human_approval_required": true,
  "summary": "Recommend pilot test at ₹1,500 minimum spend with human manager sign-off."
}
```

---

## 6. Execution & Verification

### Running Automated Tests
```bash
pytest -v
```
All 33 unit and workflow tests validate configuration loading, deterministic rule logic, proposal allowlists, replay arithmetic, tool schemas, and agent session isolation.

### Detecting Alerts (CLI)
```bash
# Dry run detection without modifying BigQuery
python alert.py --dry-run

# Run a specific rule
python alert.py --rule R1 --dry-run

# Execute against BigQuery and insert alerts into offers_gold.alerts
python alert.py --project prj-imp-act-campaign
```

### Running the Batch Investigation Pipeline
```bash
# Process up to 5 pending alerts and save JSON reports
python src/agents/run_alert_pipeline.py --limit 5 --output-dir output

# Dry run mode (does not update BigQuery alert status)
python src/agents/run_alert_pipeline.py --limit 2 --dry-run
```

---

## 7. Configuration Reference (`campaign.yaml`)

```yaml
policy:
  allowed_thresholds: [1000, 1500, 2000]
  cashback_percent: 10
  cashback_cap: 200
  budget_ceiling: 40000

investigation:
  max_tool_calls: 10
  evidence_required: true
  citations_required: true

guardrails:
  read_only_tools: true
  no_campaign_updates: true
  no_customer_contact: true
  no_future_uplift_predictions: true
```
