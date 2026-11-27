-- =====================================================================
-- 00_create_datasets.sql
-- Strictly Medallion 3-layer architecture matching New BFSI:
-- Bronze, Silver, and Gold in BigQuery
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS `offers_bronze`
OPTIONS (
  description = 'Bronze raw layer: Ingestion of raw CSVs with load metadata'
);

CREATE SCHEMA IF NOT EXISTS `offers_silver`
OPTIONS (
  description = 'Silver clean layer: Deduplicated, typed, normalized tables and quarantined records'
);

CREATE SCHEMA IF NOT EXISTS `offers_gold`
OPTIONS (
  description = 'Gold analytics & alerts layer: Analytical summaries, rule configs, and generated alerts'
);
