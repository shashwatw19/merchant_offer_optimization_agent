---
name: medallion-lakehouse-agent
description: Universal engineering standards, directory taxonomy, and architectural patterns for Medallion AI Lakehouse agents conforming strictly to the New BFSI blueprint.
---

# Medallion AI Lakehouse Architecture Skill

This skill enforces strict adherence to the **Four Uncompromising Identity Pillars** and taxonomy of the enterprise Medallion AI Lakehouse pattern established in `C:\Code\New BFSI`.

## 1. The Four Non-Negotiable Pillars

### Pillar 1: Mathematical Data Conservation (BR-4 Invariant)
Every ingested byte must be strictly accounted for across Bronze, Silver, and Dead-Letter layers:
$$\text{rows\_bronze} = \text{rows\_silver} + \text{duplicates\_removed} + \text{rows\_rejected} \quad (\Delta \equiv 0)$$
- Valid records flow to `offers_silver.*`.
- Records failing format, value, or relational checks are quarantined to `offers_dq.rejected_records` with failure reason and payload.
- Zero records may be silently dropped in SQL `WHERE` clauses without an audit record in `rejected_records`.

### Pillar 2: Decoupled Dynamic Rules Engine & Extracted SQL Queries
- Business parameters (e.g. thresholds for R1, R2, R3) must never be hardcoded into SQL queries or application logic.
- Parameters reside in `config/rule_config.csv` and are loaded into `offers_gold.rule_config`.
- Rule definitions are stored as standalone SQL templates in `sql/rules/` (`r1_low_redemption.sql`, `r2_sudden_drop.sql`, `r3_low_acquisition.sql`) and query `offers_gold.rule_config` dynamically.
- `sql/gold/08_generate_alerts.sql` evaluates candidates joined directly against dynamic thresholds in `rule_config`.

### Pillar 3: Deterministic Cognitive AI Agents (Google ADK) & Specialized Playbooks
- Pinned `temperature: 0.0` and `seed: 42` for 100% deterministic reproducibility.
- **Centralized Configuration**: All configurations are centralized in `config/campaign.yaml`. Python modules must never mutate global `os.environ` keys.
- **Tools vs Services Separation**: `src/agents/tools/` strictly contains read-only tools callable by the agent (`bigquery_tools.py`, `policy_tools.py`). Persistence, alert management, and file transformations reside in `src/services/` (`alert_store.py`, `report_converter.py`, `run_store.py`, `evidence_service.py`, `gcs_storage.py`, `report_renderer.py`).
- **Python Prompt Functions & Playbooks**: Prompts are programmatic functions (`src/prompts/prompt_builder.py`) paired with rule-specialized playbooks in `src/agents/playbooks/` (`BasePlaybook`, `R1ThresholdPlaybook`, `R2VelocityDropPlaybook`, `R3AcquisitionPlaybook`).
- **Batched Citation Verifier**: Validates 100% of cited evidence IDs against BigQuery tables using `IN UNNEST(@ids)` before finalizing the report.
- **Programmatic Safety Override**: If red flags or severe disruption signals exist, the runtime programmatically overrides passive `KEEP` proposals to `MERCHANT_ESCALATION` or `INVESTIGATE`.
- **Preserved Invocation Metrics**: Invocation-local execution telemetry and token usage are tracked in `src/agents/metrics.py` via ADK callbacks and persisted to `offers_gold.agent_runs`.
- **Strict Forecast Guardrail**: `future_incremental_spend` must strictly remain `null`. Forward-looking predictive forecasting is forbidden.

### Pillar 4: Human-in-the-Loop (HITL) Workbench & Direct Alert Sequencing
- Pipeline execution is coordinated via `scripts/run_all.sh` which triggers `Setup` -> `Bronze` -> `Silver` -> `Gold` (direct alert generation) -> `Agent Batch`.
- Alerts are generated **directly in BigQuery SQL** during the Gold stage (`sql/gold/08_generate_alerts.sql`), tagged with a unified `batch_id`.
- Operations UI (`src/ui/app.py`) provides evidence provenance inspection, step-by-step ADK execution telemetry, and multi-action recommendations array rendering.

## 2. Canonical Directory Structure & Taxonomy

```
merchant_offer_optimization_agent/
├── config/
│   ├── campaign.yaml                     # Sole centralized configuration file
│   └── rule_config.csv                   # Decoupled business rule parameters (R1, R2, R3)
├── scripts/
│   ├── run_all.sh                        # End-to-end lakehouse & agent orchestrator
│   ├── run_bronze.sh
│   ├── run_silver.sh
│   ├── run_gold.sh
│   └── run_agent.sh
├── sql/
│   ├── setup/
│   │   ├── 00_create_datasets.sql
│   │   └── 01_create_watermark_tables.sql
│   ├── bronze/                           # External table definitions & loading
│   ├── silver/                           # Silver marts, dedup, and SCD logic
│   ├── gold/
│   │   ├── 04_seed_rule_config.sql       # Seed / merge rule_config table
│   │   ├── 08_generate_alerts.sql        # Direct alert generation
│   │   ├── create_rule_config.sql        # Rule config table DDL
│   │   ├── gold_campaign_profile.sql
│   │   ├── gold_campaign_results.sql
│   │   ├── gold_merchant_weekly.sql
│   │   └── load_rule_config.py           # Syncs rule_config.csv to BigQuery
│   ├── rules/                            # Extracted standalone rule queries
│   │   ├── r1_low_redemption.sql         # Dynamic R1 query against rule_config
│   │   ├── r2_sudden_drop.sql            # Dynamic R2 query against rule_config
│   │   └── r3_low_acquisition.sql        # Dynamic R3 query against rule_config
│   └── dq/
│       ├── 01_rejected_records.sql       # Dead-letter quarantine table
│       └── 02_dq_reconciliation.sql      # Mathematical conservation audit
├── src/
│   ├── agents/
│   │   ├── playbooks/                    # Typed Python playbooks
│   │   │   ├── base.py                   # BasePlaybook (principles & contract)
│   │   │   ├── r1_threshold.py           # R1 Spend Friction Playbook
│   │   │   ├── r2_drop.py                # R2 Velocity Drop Playbook
│   │   │   ├── r3_acquisition.py         # R3 Acquisition Cannibalization Playbook
│   │   │   └── resolver.py               # Playbook factory
│   │   ├── schemas/                      # Dossier & evidence Pydantic contracts
│   │   ├── tools/                        # PURE AGENT TOOLS ONLY (callable by LLM)
│   │   │   ├── bigquery_tools.py         # 8 BigQuery inspection & simulation tools
│   │   │   └── policy_tools.py           # validate_proposal tool
│   │   ├── validation/                   # CitationVerifier & Safety Scorecard
│   │   ├── agent.py                      # Clean runner (zero os.environ mutations)
│   │   ├── metrics.py                    # Invocation-local telemetry & token tracker
│   │   ├── run_alert_detection.py        # Python alert detection engine & CLI
│   │   ├── run_alert_pipeline.py         # Batch alert pipeline orchestrator
│   │   └── tracer.py                     # Tool execution tracer
│   ├── core/
│   │   ├── bigquery_client.py            # BigQuery client & resilient retry runner
│   │   ├── config.py                     # Centralized config loader (no os.environ side-effects)
│   │   ├── exceptions.py
│   │   ├── logging.py
│   │   ├── resilience.py
│   │   └── time_utils.py
│   ├── domain/
│   │   ├── contracts.py                  # Public domain contract re-exports
│   │   ├── policy.py                     # Policy rule validation logic
│   │   ├── rules.py                      # Alert parsing & loader for sql/rules/*.sql
│   │   └── simulator.py                  # Historical replay simulator
│   ├── pipeline/
│   │   └── watermark_service.py          # Watermark state manager
│   ├── prompts/
│   │   ├── __init__.py                   # Re-exports programmatic prompt functions
│   │   └── prompt_builder.py             # Python prompt generation functions
│   ├── services/                         # APPLICATION & PERSISTENCE SERVICES
│   │   ├── alert_store.py                # Alert CRUD & status updates
│   │   ├── evidence_service.py           # BigQuery evidence resolver
│   │   ├── gcs_storage.py                # Cloud Storage uploader/downloader
│   │   ├── report_converter.py           # Markdown report converter & GCS uploader
│   │   ├── report_renderer.py            # Report rendering
│   │   └── run_store.py                  # Agent run audit persistence
│   └── ui/                               # Operations dashboard & HITL workbench
└── tests/                                # Pytest test suite
```
