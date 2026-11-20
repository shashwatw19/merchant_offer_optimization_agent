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

### Pillar 2: Decoupled Dynamic Rules Engine
- Business parameters (e.g. thresholds for R1, R2, R3) must never be hardcoded into SQL queries or application logic.
- Parameters reside in `config/rule_config.csv` and are loaded into `offers_gold.rule_config`.
- Rule views query `offers_gold.rule_config` dynamically.

### Pillar 3: Deterministic Cognitive AI Agents (Google ADK 2.13.0)
- Pinned `temperature: 0.0` and `seed: 42` for 100% deterministic reproducibility.
- Turn 1 Parallel Retrieval Protocol: Emits all baseline read queries in parallel to minimize latency.
- 9 Read-Only Atomic Tools: No DDL/DML tools are exposed to the agent.
- Batched Citation Verifier: Validates 100% of cited evidence IDs against BigQuery tables using `IN UNNEST(@ids)` before finalizing the report.
- Programmatic Safety Override: If red flags or severe disruption signals exist, the runtime programmatically overrides passive `KEEP` proposals to `MERCHANT_ESCALATION` or `INVESTIGATE`.
- Strict Forecast Guardrail: `future_incremental_spend` must strictly remain `null`. Forward-looking predictive forecasting is forbidden.

### Pillar 4: Human-in-the-Loop (HITL) Workbench & Direct Alert Sequencing
- Pipeline execution is coordinated via `scripts/run_all.sh` which triggers `Setup` -> `Bronze` -> `Silver` -> `Gold` (direct alert generation) -> `Agent Batch`.
- Alerts are generated **directly in BigQuery SQL** during the Gold stage (`sql/gold/08_generate_alerts.sql`), tagged with a unified `batch_id`.
- Operations UI provides evidence provenance inspection, step-by-step ADK execution telemetry, and multi-action recommendations array rendering.

## 2. Canonical Directory Structure & Taxonomy

```
merchant_offer_optimization_agent/
├── config/
│   ├── project_config.yaml
│   ├── agent_config.yaml
│   └── rule_config.csv
├── scripts/
│   ├── run_all.sh
│   ├── run_bronze.sh
│   ├── run_silver.sh
│   ├── run_gold.sh
│   └── run_agent.sh
├── sql/
│   ├── setup/
│   │   ├── 00_create_datasets.sql
│   │   └── 01_create_watermark_tables.sql
│   ├── bronze/
│   ├── silver/
│   ├── gold/
│   │   ├── 04_seed_rule_config.sql
│   │   ├── load_rule_config.py
│   │   └── 08_generate_alerts.sql
│   └── dq/
│       ├── 01_rejected_records.sql
│       └── 02_dq_reconciliation.sql
├── src/
│   ├── core/
│   ├── pipeline/
│   │   └── watermark_service.py
│   ├── agents/
│   │   ├── investigator/
│   │   ├── orchestration/
│   │   ├── prompts/
│   │   ├── schemas/
│   │   ├── tools/
│   │   └── validation/
│   └── ui/
└── tests/
```
