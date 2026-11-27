# Merchant Offer Optimization Agent & Medallion Lakehouse Platform

An enterprise-grade, deterministic, and auditable Autonomous AI Agent coupled with a Medallion Lakehouse Architecture on Google Cloud BigQuery. Built using the **Google Agent Development Kit (ADK) 2.13.0**, **Python 3.14**, **FastAPI**, and **Gemini 2.5 Flash / Pro**.

The system automates the end-to-end ingestion, normalization, dynamic rule evaluation, investigation, and policy-compliant optimization of merchant card-linked offer campaigns.

---

## 1. System Architecture: Medallion AI Lakehouse Pattern

The platform strictly implements the **Four Engineering Identity Pillars**:
1. **Mathematical Data Conservation (BR-4)**: $\Delta = \text{Bronze} - (\text{Silver} + \text{Rejected}) = 0$. Every ingested byte is strictly tracked.
2. **Decoupled Dynamic Rules**: Rule thresholds (R1, R2, R3) live in control tables (`offers_gold.rule_config` / `config/rule_config.csv`), not hardcoded in SQL or prompts.
3. **Deterministic Cognitive Agents**: Read-only tools, parallel retrieval, 100% cited facts, and programmatic safety override invariants.
4. **Human-In-The-Loop (HITL) Workbench**: High-fidelity dashboard for reviewing dossiers, verifying citations, and 1-click approvals.

```
                              [ Google Cloud Storage (Delta CSVs) ]
                                                │
                                                ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ BRONZE LAYER (offers_bronze)                                                                     │
│ Raw external & partitioned ingestion: campaigns_raw, transactions_raw, merchants_raw, etc.       │
└────────────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                                 │
                                                 ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ SILVER LAYER (offers_silver & offers_dq)                                                         │
│ Type normalization, deduplication & foreign-key topological hierarchy:                           │
│ merchants -> customers -> campaigns -> transactions -> sends -> redemptions -> feedback          │
│ Quarantined rows routed to: `offers_silver.invalid_records` & `offers_dq.rejected_records`       │
└────────────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                                 │
                                                 ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ GOLD LAYER & DIRECT ALERTS (offers_gold)                                                         │
│ - Analytical Marts: gold_campaign_results, gold_campaign_profile, gold_merchant_spend_profile    │
│ - Decoupled Rules: config/rule_config.csv -> offers_gold.rule_config                             │
│ - Direct SQL Alert Generator: evaluates R1, R2, R3 -> offers_gold.alerts                         │
│ - BR-4 Conservation Auditor: offers_dq.v_conservation_audit                                      │
└────────────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                                 │
                                                 ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ COGNITIVE AI AGENT INVESTIGATOR (Google ADK 2.13.0 + Gemini 2.5)                                 │
│ - Dispatches bounded read-only investigation tools                                               │
│ - Evaluates root causes, policy checks, & historical replay simulations                          │
│ - Emits structured dossiers with multi-action recommendations & cited facts                      │
│ - Enforces Safety Invariant Guardrails & Citation Verifiers                                     │
└────────────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                                 │
                                                 ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ HUMAN-IN-THE-LOOP (HITL) WORKBENCH (FastAPI + Jinja2)                                            │
│ - Real-time Alert Queue & Status Counts                                                          │
│ - Deep-Dive Dossier Viewer, Citation Inspector (/api/evidence/verify)                           │
│ - Operational Admin Panel (/admin) for Model Latencies, Tool Durations, and Token Costs          │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Directory Structure

```
merchant_offer_optimization_agent/
│
├── config/                         # System, agent & dynamic rule configuration
│   ├── project_config.yaml         # Cloud storage, dataset names, credentials
│   ├── agent_config.yaml           # Model (gemini-2.5-flash), temperature, max_tool_calls
│   └── rule_config.csv             # Decoupled business rule parameters (R1, R2, R3)
│
├── scripts/                        # Operational bash scripts for Cloud Shell / VM
│   ├── run_all.sh                  # Master end-to-end orchestrator trigger
│   ├── run_bronze.sh               # Bronze delta ingestion trigger
│   ├── run_silver.sh               # Silver normalization (strict topological order)
│   ├── run_gold.sh                 # Gold analytical marts & direct alert generator
│   └── run_agent.sh                # Autonomous cognitive investigation batch trigger
│
├── sql/                            # Canonical BigQuery SQL DDLs & transformations
│   ├── setup/                      # Dataset creation & setup scripts
│   ├── bronze/                     # Raw extraction & staging loaders
│   ├── silver/                     # Cleansing, reference mapping, & dimension loaders
│   ├── gold/                       # Analytical marts, rule config sync, & alert generator
│   └── dq/                         # Quarantine tables & BR-4 mathematical audit views
│
├── src/                            # Production Python application code
│   ├── agents/                     # Google ADK agent, tools, prompts, & validation
│   │   ├── investigator/           # Cognitive investigator agent implementation
│   │   ├── orchestration/          # Batch runner & session state management
│   │   ├── prompts/                # System instructions & domain playbooks (R1, R2, R3)
│   │   ├── schemas/                # Dossier contracts & multi-action recommendations
│   │   ├── tools/                  # 9 Bounded read-only tools & simulation replay
│   │   └── validation/             # Citation verifiers & safety invariant override
│   ├── core/                       # BigQuery thread-safe client, logging, & YAML config
│   ├── domain/                     # Business policy invariants, rules, & replay logic
│   ├── pipeline/                   # Pipeline services
│   ├── services/                   # Storage, markdown rendering, & evidence services
│   └── ui/                         # FastAPI interactive HITL workbench & admin panel
│       ├── static/css/             # Modern stylesheet matching New BFSI layout
│       └── templates/              # HTML templates (dashboard, report, admin, base)
│
├── tests/                          # 68+ Automated unit & regression test suites
├── campaign.yaml                   # Core platform configuration & policy allowlists
└── pyproject.toml                  # Project metadata & Python dependencies
```

---

## 3. Deterministic Alert Rules (Decoupled Dynamic Rules)

Alert rules evaluate campaign performance metrics against dynamic thresholds loaded from `config/rule_config.csv` into `offers_gold.rule_config`:

| Rule ID | Metric Evaluated | Default Threshold | Business Meaning & Scenario |
|---|---|---|---|
| **R1** | `redemption_rate` | `< 5.0%` | **Low Redemption Friction**: Audience is reached, but spend requirement is higher than average ticket size (e.g. median bill ₹750 vs ₹2,000 threshold). |
| **R2** | `period_redemption_drop_pct` | `>= 50.0% drop` | **Sudden Velocity Collapse**: Redemptions drop significantly in the 2nd half compared to baseline (e.g. merchant renovation, store closure, operational outage). |
| **R3** | `existing_customer_share_pct` | `>= 75.0%` | **Audience Cannibalization / Acquisition Failure**: New-customer campaign (`ACQUIRE_NEW`) is dominated by repeat patrons due to geographic or segmentation mismatch. |

---

## 4. The 9 Bounded Agent Tools

All tools are **strictly read-only**, thread-safe, return auditable facts with source citations, and enforce safety invariants:

1. **`get_campaign_terms(campaign_id)`**: Retrieves configured minimum spend, cashback percent, cap, and budget from `offers_silver.campaigns`.
2. **`get_campaign_performance(campaign_id)`**: Fetches targeted reach, sends, redemptions, and budget burn from `offers_gold.gold_campaign_results`.
3. **`get_spend_distribution(merchant_id)`**: Returns merchant ticket percentiles (p25, p50, p75, p90) and average order value from `offers_gold.gold_merchant_spend_profile`.
4. **`get_customer_reviews(merchant_id, limit)`**: Fetches dated customer reviews, star ratings, and sentiment issues from `offers_silver.customer_reviews`.
5. **`get_merchant_feedback(merchant_id, limit)`**: Retrieves relationship manager notes and operational incident logs from `offers_silver.merchant_feedback`.
6. **`get_delivery_metrics(campaign_id)`**: Computes notification delivery success rates and audience-outlet city mismatches from `offers_silver.offer_sends`.
7. **`get_comparable_campaigns(campaign_id, limit)`**: Benchmarks redemption velocity against peer merchant campaigns in the same merchant category.
8. **`validate_proposal(proposed_min_spend, cashback_pct, cashback_cap)`**: Programmatically validates proposed parameter modifications against policy allowlists and budget ceilings in `campaign.yaml`.
9. **`simulate_campaign_change(campaign_id, min_spend)`**: Executes a retrospective historical replay simulation strictly across *targeted customers' posted card transactions*. Verifies merchant liability and budget impact without speculative predictive forecasting.

---

## 5. End-to-End Execution on Google Cloud Shell

### Prerequisites
- Access to Google Cloud Project: `prj-imp-act-campaign`
- Default Location: `asia-south1`
- Cloud Shell terminal with Python 3.10+ and Google Cloud SDK (`bq`, `gcloud`)

### Step 1: Clone and Set Up Environment
```bash
# Navigate to workspace
cd ~/merchant_offer/merchant_offer_optimization_agent

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Configure Environment Variables
```bash
export GCP_PROJECT="prj-imp-act-campaign"
export BQ_LOCATION="asia-south1"
export PYTHONPATH="src"

# Optional: If running with Gemini API Key rather than Vertex AI default credentials:
# export GEMINI_API_KEY="your-api-key"
```

### Step 3: Run the Master End-to-End Pipeline
Execute all 5 stages in one unified orchestrator:
```bash
bash scripts/run_all.sh
```

---

## 6. Running Individual Pipeline Stages

You can also run any pipeline stage independently:

### Stage 1: Setup & Quarantine Tables
Creates schemas (`offers_setup`, `offers_reference`, `offers_bronze`, `offers_silver`, `offers_gold`, `offers_dq`) and quarantine tables:
```bash
bq query --project_id="$GCP_PROJECT" --location="$BQ_LOCATION" --use_legacy_sql=false < sql/setup/00_create_datasets.sql
bq query --project_id="$GCP_PROJECT" --location="$BQ_LOCATION" --use_legacy_sql=false < sql/dq/01_rejected_records.sql
```

### Stage 2: Bronze Ingestion
Loads raw delta files into `offers_bronze.*`:
```bash
bash scripts/run_bronze.sh
```

### Stage 3: Silver Cleansing & Topological Normalization
Executes silver transformations strictly in foreign-key dependency order:
```bash
bash scripts/run_silver.sh
```

### Stage 4: Gold Marts, Rule Sync & Direct Alert Generation
Syncs `config/rule_config.csv` into `offers_gold.rule_config`, builds analytical marts, generates alerts directly into `offers_gold.alerts`, and audits BR-4 data conservation:
```bash
bash scripts/run_gold.sh
```

### Stage 5: AI Investigation Agent Batch
Dispatches the cognitive agent to investigate all pending alerts in `offers_gold.alerts`:
```bash
bash scripts/run_agent.sh

# Or run directly with Python:
python -m agents.run_alert_pipeline --batch-id "B_$(date +'%y%m%d_%H%M')"
```

---

## 7. Starting the Interactive Web Workbench & Admin Panel

Launch the FastAPI application:
```bash
uvicorn ui.app:app --host 0.0.0.0 --port 8080 --reload
```

### UI Features:
- **Alert Queue (`/`)**: Real-time filtering by status (`OPEN`, `RESOLVED`, `PROCESSING`), search by Campaign ID / Merchant ID, rule badge pills, and direct "Investigate" action triggers.
- **Evidence Dossier (`/reports/{alert_id}`)**:
  - Executive summary and root-cause determination.
  - Multi-action recommendations (type, rationale, parameters, confidence score).
  - Hypothesis validation status (`SUPPORTED`, `REFUTED`, `INCONCLUSIVE`).
  - Cited fact cards with one-click live verification via `/api/evidence/verify`.
  - Human-in-the-loop review actions (Approve / Reject / Request Modification).
  - One-click Markdown export (`/reports/{alert_id}/markdown`).
- **Admin Panel (`/admin`)**:
  - Model token usage and execution latency metrics.
  - Per-tool call duration benchmarks and call-frequency statistics.
  - Historical run key search and execution traces.
- **Health Check (`/health`)**: Service probe returning JSON status.

---

## 8. Automated Testing & Verification

Run the full synchronous unit test suite covering rules, policy allowlists, simulator replays, evidence services, storage, and CLI:
```bash
python -m pytest tests/test_simulator.py tests/test_rules.py tests/test_policy.py \
                 tests/test_report_renderer.py tests/test_report_tool.py \
                 tests/test_evidence_service.py tests/test_gcs_storage.py \
                 tests/test_metrics.py tests/test_prompts.py tests/test_tools.py \
                 tests/test_two_tier_resilience.py tests/test_contracts.py \
                 tests/test_error_handling.py tests/test_alert_cli.py tests/test_config.py -v
```
*(All 68 tests pass with 100% assertion coverage).*

---

## 9. Safety Invariants & Guardrails

- **Zero Direct Mutation**: All agent investigation tools are strictly read-only.
- **Policy Allowlist Validation**: The agent cannot recommend spend thresholds outside allowlisted values (e.g. ₹500, ₹1000, ₹1500, ₹2000) or exceeding budget ceilings.
- **Mandatory Human-in-the-Loop**: Every dossier output enforces `human_approval_required: true`. No campaign change is deployed autonomously.
- **Citation Guardrail**: Every claim in the findings must cite a verified source identifier (e.g. `bq:campaigns`, `bq:customer_reviews:REV101`). Uncited or fabricated facts are automatically flagged by the `CitationVerifier`.
