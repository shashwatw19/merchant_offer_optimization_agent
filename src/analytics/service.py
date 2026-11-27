"""Natural-language analytics orchestration for Merchant Offer BigQuery data."""

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types

from analytics.catalog import MetadataCatalog, get_metadata_catalog
from analytics.client import AnalyticsBigQueryClient, sanitize_pii
from analytics.models import (
    AnalystChatRequest,
    AnalystChatResponse,
    ClarificationOption,
)
from analytics.prompts import (
    INTENT_DETECTION_SYSTEM_PROMPT,
    RESULT_SYNTHESIS_SYSTEM_PROMPT,
    SQL_GENERATION_SYSTEM_PROMPT,
)
from core.config import get_config

logger = logging.getLogger("analytics.service")


class AnalystChatService:
    """Routes analyst questions, validates SQL, queries BigQuery, and summarizes rows."""

    def __init__(
        self,
        bq_client: Optional[AnalyticsBigQueryClient] = None,
        catalog: Optional[MetadataCatalog] = None,
        model_name: Optional[str] = None,
        genai_client: Optional[Any] = None,
    ):
        self.config = get_config()
        self.bq_client = bq_client or AnalyticsBigQueryClient()
        self.catalog = catalog or get_metadata_catalog()
        configured_model = getattr(getattr(self.config, "agent", None), "model", "gemini-2.5-flash")
        self.model_name = os.environ.get("GEMINI_MODEL", model_name or configured_model)
        self.genai_client = genai_client if genai_client is not None else self._init_genai_client()

    def _init_genai_client(self) -> Optional[Any]:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        try:
            if api_key:
                return genai.Client(api_key=api_key)
            use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() == "true"
            project = self.bq_client.project_id or getattr(
                getattr(self.config, "gcp", None),
                "project_id",
                None,
            )
            if use_vertex and project:
                location = os.environ.get("GOOGLE_CLOUD_LOCATION") or getattr(
                    getattr(self.config, "gcp", None),
                    "location",
                    "us-central1",
                )
                return genai.Client(
                    vertexai=True,
                    project=project,
                    location=location,
                )
            return None
        except Exception as exc:
            logger.warning("Gemini client initialization failed: %s", sanitize_pii(str(exc)))
            return None

    def process_question(self, request: AnalystChatRequest) -> AnalystChatResponse:
        start = time.perf_counter()
        question = request.question.strip()
        recent_history = (request.history or [])[-5:]
        conversation_context = ""
        if recent_history:
            conversation_context = "\n".join(
                f"{'User' if msg.role == 'user' else 'Assistant'}: {msg.content.strip()}"
                for msg in recent_history
                if msg.content and msg.content.strip()
            )

        intent_info = self._detect_intent(question, conversation_context=conversation_context)
        intent = str(intent_info.get("intent", "DATABASE_QUERY")).upper()

        if intent == "CLARIFICATION" or intent_info.get("is_ambiguous"):
            clarification = intent_info.get("clarification_question") or (
                "Please specify which business entity you mean."
            )
            options = []
            raw_options = intent_info.get("clarification_options", [])
            if isinstance(raw_options, list):
                for option in raw_options:
                    try:
                        options.append(ClarificationOption(**option))
                    except (TypeError, ValueError):
                        logger.warning("Ignoring malformed clarification option from intent response.")
            return AnalystChatResponse(
                status="CLARIFICATION_NEEDED",
                intent="CLARIFICATION",
                user_question=question,
                business_summary=clarification,
                clarification_question=clarification,
                clarification_options=options,
                execution_time_ms=self._elapsed_ms(start),
            )

        if intent == "DIRECT_ANSWER":
            direct_answer = intent_info.get("direct_response") or self._generate_direct_response(question)
            return AnalystChatResponse(
                status="DIRECT_RESPONSE",
                intent="DIRECT_ANSWER",
                user_question=question,
                business_summary=str(direct_answer),
                result_highlights=["No database query was needed."],
                execution_time_ms=self._elapsed_ms(start),
            )

        combined_text = f"{conversation_context}\n{question}" if conversation_context else question
        schema_context = self.catalog.get_schema_prompt_context(combined_text)
        generated_sql = self._generate_sql(question, schema_context, conversation_context=conversation_context)
        try:
            rows, validation, metric = self.bq_client.execute_readonly_query(
                sql=generated_sql,
                user_question=question,
                request_limit=request.max_rows or 100,
            )
        except PermissionError as exc:
            logger.warning("Analytics SQL was rejected: %s", sanitize_pii(str(exc)))
            return self._error_response(question, str(exc), start, sql=generated_sql)
        except Exception as query_error:
            corrected_sql = self._correct_sql_with_error(
                question,
                generated_sql,
                sanitize_pii(str(query_error)),
            )
            if not corrected_sql or corrected_sql == generated_sql:
                logger.error("Analytics query failed: %s", sanitize_pii(str(query_error)))
                return self._error_response(question, str(query_error), start, sql=generated_sql)
            try:
                rows, validation, metric = self.bq_client.execute_readonly_query(
                    sql=corrected_sql,
                    user_question=question,
                    request_limit=request.max_rows or 100,
                )
                generated_sql = validation.sanitized_sql
            except Exception as retry_error:
                logger.error("Analytics query retry failed: %s", sanitize_pii(str(retry_error)))
                return self._error_response(question, str(retry_error), start, sql=generated_sql)

        synthesis = self._synthesize_results(question, validation.sanitized_sql, rows)
        columns = list(rows[0].keys()) if rows else []
        return AnalystChatResponse(
            status="SUCCESS",
            intent="DATABASE_QUERY",
            user_question=question,
            business_summary=synthesis["business_summary"],
            result_highlights=synthesis["result_highlights"],
            detailed_data=rows,
            data_columns=columns,
            generated_sql=validation.sanitized_sql if request.include_sql else None,
            execution_time_ms=self._elapsed_ms(start),
            rows_count=len(rows),
            tables_accessed=validation.tables_accessed,
            bytes_processed=metric.bytes_processed,
        )

    @staticmethod
    def _elapsed_ms(start: float) -> float:
        return round((time.perf_counter() - start) * 1000, 2)

    def _error_response(
        self,
        question: str,
        error: str,
        start: float,
        sql: Optional[str] = None,
    ) -> AnalystChatResponse:
        return AnalystChatResponse(
            status="ERROR",
            intent="DATABASE_QUERY",
            user_question=question,
            business_summary="I could not complete that analysis. Please try rephrasing or check the query details.",
            generated_sql=sql,
            execution_time_ms=self._elapsed_ms(start),
            error_message=sanitize_pii(error),
        )

    def _detect_intent(self, question: str, conversation_context: str = "") -> Dict[str, Any]:
        lowered = question.lower().strip()
        greeting = bool(re.match(r"^(?:hello|hi|hey)\b", lowered))
        capability_question = any(
            phrase in lowered
            for phrase in ("help", "what can you do", "what questions can i ask")
        )
        data_terms = (
            "campaign",
            "merchant",
            "customer",
            "transaction",
            "redemption",
            "review",
            "alert",
            "revenue",
            "spend",
            "cashback",
        )
        if (greeting or capability_question) and not any(
            term in lowered for term in data_terms
        ):
            return {"intent": "DIRECT_ANSWER"}

        ambiguous_revenue = re.search(
            r"\b(?:revenue|spend)\s+(?:for|of)\s+(?!merchant\b|customer\b)([A-Za-z0-9_-]+)\b",
            question,
            re.IGNORECASE,
        )
        if ambiguous_revenue:
            entity = ambiguous_revenue.group(1)
            return {
                "intent": "CLARIFICATION",
                "is_ambiguous": True,
                "clarification_question": f"Does '{entity}' refer to a merchant or a customer?",
                "clarification_options": [
                    {
                        "label": f"Merchant {entity}",
                        "value": f"Show spend for merchant {entity}",
                        "description": "Merchant transaction volume and ticket size",
                    },
                    {
                        "label": f"Customer {entity}",
                        "value": f"Show transactions for customer {entity}",
                        "description": "Customer transaction activity",
                    },
                ],
            }

        if self.genai_client is not None:
            try:
                classify_contents = f"Classify this analyst question:\n{question}"
                if conversation_context:
                    classify_contents = (
                        f"Recent conversation context:\n{conversation_context}\n\n"
                        f"Classify this analyst question:\n{question}"
                    )
                response = self.genai_client.models.generate_content(
                    model=self.model_name,
                    contents=classify_contents,
                    config=types.GenerateContentConfig(
                        system_instruction=INTENT_DETECTION_SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        temperature=0.0,
                    ),
                )
                parsed = self._parse_json_response(response.text or "")
                if parsed and parsed.get("intent") in {
                    "DATABASE_QUERY",
                    "DIRECT_ANSWER",
                    "CLARIFICATION",
                }:
                    return parsed
            except Exception as exc:
                logger.info("Intent detection fallback: %s", sanitize_pii(str(exc)))
        return {"intent": "DATABASE_QUERY", "is_ambiguous": False}

    @staticmethod
    def _parse_json_response(text: str) -> Optional[Dict[str, Any]]:
        cleaned = text.strip()
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.IGNORECASE)
        if match:
            cleaned = match.group(1).strip()
        try:
            parsed = json.loads(cleaned)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    def _generate_sql(self, question: str, schema_context: str, conversation_context: str = "") -> str:
        if self.genai_client is not None:
            try:
                contents = f"Business Question: {question}\n\nGoogleSQL Query:"
                if conversation_context:
                    contents = (
                        f"Recent Conversation Context:\n{conversation_context}\n\n"
                        f"Current Business Question: {question}\n\nGoogleSQL Query:"
                    )
                response = self.genai_client.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=SQL_GENERATION_SYSTEM_PROMPT.format(
                            schema_context=schema_context
                        ),
                        temperature=0.0,
                    ),
                )
                response_text = getattr(response, "text", "")
                generated = self._extract_sql(response_text) if isinstance(response_text, str) else ""
                if generated and re.match(r"^\s*(?:SELECT|WITH)\b", generated, re.IGNORECASE):
                    return generated
            except Exception as exc:
                logger.warning("Gemini SQL generation fallback: %s", sanitize_pii(str(exc)))
        return self._heuristic_sql_generator(question)

    @staticmethod
    def _extract_sql(text: str) -> str:
        match = re.search(r"```(?:sql)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
        return (match.group(1) if match else text).strip().rstrip(";")

    def _project_table(self, dataset_table: str) -> str:
        project = getattr(getattr(self.config, "gcp", None), "project_id", None)
        if project:
            return f"`{project}.{dataset_table}`"
        return f"`{dataset_table}`"

    def _heuristic_sql_generator(self, question: str) -> str:
        """Generate safe, common Merchant Offer analytics queries without Gemini."""
        lowered = question.lower()
        merchant_id = self._extract_identifier(question, "merchant")
        customer_id = self._extract_identifier(question, "customer")

        top_match = re.search(r"\btop\s+(\d+)\b", lowered)
        limit = min(max(int(top_match.group(1)), 1), 100) if top_match else 10
        spend_table = self._project_table("offers_gold.gold_merchant_spend_profile")

        if ("top" in lowered or "highest" in lowered) and any(
            word in lowered for word in ("merchant", "revenue", "spend", "ticket", "sales")
        ):
            measure = "avg_txn_amount" if any(
                word in lowered for word in ("average", "avg", "ticket")
            ) else "posted_amount_total"
            return (
                f"SELECT merchant_id, merchant_name, merchant_category, merchant_city, "
                f"{measure} FROM {spend_table} "
                f"ORDER BY {measure} DESC LIMIT {limit}"
            )

        if any(word in lowered for word in ("alert", "alerts", "rule", "violation")):
            where = f"WHERE merchant_id = '{merchant_id}' " if merchant_id else ""
            return (
                "SELECT alert_id, campaign_id, merchant_id, rule_id, metric_name, "
                "metric_value, threshold_value, status, created_at "
                f"FROM {self._project_table('offers_gold.alerts')} "
                f"{where}ORDER BY created_at DESC LIMIT {limit}"
            )

        if any(word in lowered for word in ("review", "reviews", "rating")):
            review_table = self._project_table("offers_silver.customer_reviews")
            where = "WHERE rating <= 2.5 " if "negative" in lowered or "low" in lowered else ""
            if merchant_id:
                where += ("AND " if where else "WHERE ") + f"merchant_id = '{merchant_id}' "
            return (
                f"SELECT review_id, merchant_id, review_date, rating, review_text "
                f"FROM {review_table} {where}ORDER BY review_date DESC LIMIT {limit}"
            )

        if any(word in lowered for word in ("campaign", "redemption", "cashback")):
            where = f"WHERE campaign_id = '{self._extract_identifier(question, 'campaign')}' " \
                if self._extract_identifier(question, "campaign") else ""
            return (
                "SELECT campaign_id, merchant_id, campaign_status, targeted_customer_count, "
                "delivered_customer_count, redeeming_customer_count, redemption_rate_pct, "
                "cashback_amt_awarded, posted_txn_count, posted_txn_amount "
                f"FROM {self._project_table('offers_gold.gold_campaign_results')} "
                f"{where}ORDER BY measurement_end_date DESC LIMIT {limit}"
            )

        if customer_id and any(
            word in lowered for word in ("transaction", "purchase", "spend", "history")
        ):
            return (
                "SELECT txn_id, customer_id, merchant_id, txn_ts, amount, txn_status "
                f"FROM {self._project_table('offers_silver.transactions')} "
                f"WHERE customer_id = '{customer_id}' ORDER BY txn_ts DESC LIMIT {limit}"
            )

        if customer_id or "customer" in lowered or "cardholder" in lowered:
            where = f"WHERE customer_id = '{customer_id}' " if customer_id else ""
            return (
                "SELECT customer_id, city, segment, marketing_eligible, card_status "
                f"FROM {self._project_table('offers_silver.customers')} "
                f"{where}ORDER BY customer_id LIMIT {limit}"
            )

        if merchant_id or "merchant" in lowered:
            where = f"WHERE merchant_id = '{merchant_id}' " if merchant_id else ""
            return (
                "SELECT merchant_id, merchant_name, merchant_category, merchant_city, "
                "posted_txn_count, posted_amount_total, avg_txn_amount, median_txn_amount "
                f"FROM {spend_table} {where}ORDER BY period_end DESC LIMIT {limit}"
            )

        return (
            "SELECT alert_id, campaign_id, merchant_id, rule_id, metric_name, "
            "metric_value, threshold_value, status, created_at "
            f"FROM {self._project_table('offers_gold.alerts')} "
            f"ORDER BY created_at DESC LIMIT {limit}"
        )

    @staticmethod
    def _extract_identifier(question: str, entity: str) -> Optional[str]:
        patterns = {
            "customer": r"\b(?:CUST[-_]?\d+|C\d{3,5})\b",
            "merchant": r"\b(?:MERCH(?:ANT)?[-_][A-Za-z0-9]+|M[-_]\d+)\b",
            "campaign": r"\b(?:CMP[-_]?[A-Za-z0-9]+|CAMPAIGN[-_][A-Za-z0-9]+)\b",
        }
        match = re.search(patterns[entity], question, re.IGNORECASE)
        if match:
            return match.group(0).upper()
        named = re.search(
            rf"\b{entity}\s+(?:id\s*[:#=]\s*|[:#=]\s*)([A-Za-z0-9_-]+)\b",
            question,
            re.IGNORECASE,
        )
        if named:
            value = named.group(1)
            if value.isupper() or any(char.isdigit() for char in value) or "_" in value or "-" in value:
                return value.upper()
        return None

    def _correct_sql_with_error(self, question: str, failed_sql: str, error_message: str) -> str:
        if self.genai_client is None:
            return ""
        try:
            context = self.catalog.get_schema_prompt_context(question)
            response = self.genai_client.models.generate_content(
                model=self.model_name,
                contents=(
                    f"Business Question: {question}\n"
                    f"Failed SQL:\n{failed_sql}\n"
                    f"BigQuery error: {error_message}\n"
                    "Return only a corrected SQL query."
                ),
                config=types.GenerateContentConfig(
                    system_instruction=SQL_GENERATION_SYSTEM_PROMPT.format(
                        schema_context=context
                    ),
                    temperature=0.0,
                ),
            )
            return self._extract_sql(response.text or "")
        except Exception as exc:
            logger.warning("SQL correction failed: %s", sanitize_pii(str(exc)))
            return ""

    def _synthesize_results(
        self,
        question: str,
        sql: str,
        rows: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not rows:
            return {
                "business_summary": (
                    "No matching records were found in the Merchant Offer datasets for these criteria."
                ),
                "result_highlights": ["0 records returned."],
            }
        if self.genai_client is not None:
            try:
                response = self.genai_client.models.generate_content(
                    model=self.model_name,
                    contents=(
                        f"Question: {question}\nExecuted SQL: {sql}\n"
                        f"Result rows: {json.dumps(rows[:10], default=str)}"
                    ),
                    config=types.GenerateContentConfig(
                        system_instruction=RESULT_SYNTHESIS_SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        temperature=0.0,
                    ),
                )
                response_text = getattr(response, "text", "")
                parsed = self._parse_json_response(response_text) if isinstance(response_text, str) else None
                if parsed and isinstance(parsed.get("business_summary"), str):
                    highlights = parsed.get("result_highlights", [])
                    return {
                        "business_summary": parsed["business_summary"],
                        "result_highlights": [
                            str(item) for item in highlights if isinstance(item, (str, int, float))
                        ],
                    }
                if isinstance(response_text, str) and response_text.strip():
                    return {
                        "business_summary": response_text.strip(),
                        "result_highlights": [],
                    }
            except Exception as exc:
                logger.info("Result synthesis fallback: %s", sanitize_pii(str(exc)))
        return self._heuristic_synthesis(rows)

    @staticmethod
    def _heuristic_synthesis(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        first = rows[0]
        count = len(rows)
        highlights = [f"Records returned: {count}."]
        if "alert_id" in first:
            summary = f"Found {count} campaign alert(s) matching the requested criteria."
            if first.get("rule_id"):
                highlights.append(f"Latest listed alert rule: {first['rule_id']}.")
            if first.get("status"):
                highlights.append(f"Status: {first['status']}.")
        elif "redemption_rate_pct" in first:
            campaign_id = first.get("campaign_id", "Campaign")
            summary = f"Retrieved campaign performance for {count} matching record(s), including redemption rate and cashback."
            if first.get("redemption_rate_pct") is not None:
                highlights.append(
                    f"{campaign_id} redemption rate: {first['redemption_rate_pct']}%."
                )
        elif "posted_amount_total" in first:
            summary = f"Retrieved spend profiles for {count} merchant record(s)."
            if first.get("merchant_name"):
                highlights.append(f"Merchant: {first['merchant_name']}.")
            if first.get("posted_amount_total") is not None:
                highlights.append(f"Posted amount: {first['posted_amount_total']}.")
        else:
            summary = f"Query returned {count} record(s) matching the requested criteria."
            identifiers = [
                f"{key}: {first[key]}"
                for key in ("campaign_id", "merchant_id", "customer_id")
                if first.get(key) is not None
            ]
            highlights.extend(identifiers[:2])
        return {"business_summary": summary, "result_highlights": highlights}

    @staticmethod
    def _generate_direct_response(question: str) -> str:
        return (
            "I can analyze campaign performance, merchant spend, customer transactions, "
            "offer redemptions, reviews, and campaign alerts from the configured Silver and Gold datasets."
        )
