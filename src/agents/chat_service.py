"""Compatibility adapter for the modular analytics chatbot service."""

from typing import Any, Dict, List, Optional, Set

from analytics.catalog import BUILTIN_TABLE_CATALOG
from analytics.client import AnalyticsBigQueryClient
from analytics.models import AnalystChatRequest, AnalystChatResponse, ChatMessage
from analytics.service import AnalystChatService
from analytics.validator import SQLSafetyValidator
from core.config import get_config

ALLOWED_TABLES: Set[str] = set(BUILTIN_TABLE_CATALOG)


class SafeChatBotService:
    """Preserves the original UI-facing API while delegating to analytics modules."""

    def __init__(
        self,
        config: Optional[Any] = None,
        bq_client: Optional[Any] = None,
        ai_client: Optional[Any] = None,
    ):
        self.config = config or get_config()
        self.project_id = getattr(
            getattr(self.config, "gcp", None),
            "project_id",
            "prj-imp-act-campaign",
        )
        self.bq_client = bq_client or None
        self.analytics_client = AnalyticsBigQueryClient(base_client=bq_client)
        self.validator = self.analytics_client.validator
        model_name = getattr(getattr(self.config, "agent", None), "model", None)
        self.service = AnalystChatService(
            bq_client=self.analytics_client,
            model_name=model_name,
            genai_client=ai_client,
        )
        self.ai_client = self.service.genai_client

    def validate_sql_safety(self, sql: str) -> None:
        result = self.validator.validate(sql)
        if result.is_valid:
            return
        reason = "; ".join(result.violation_reasons)
        if any("outside the permitted catalog" in item for item in result.violation_reasons):
            raise ValueError(f"Access Denied: {reason}")
        raise ValueError(f"Safety Policy Violation: {reason}")

    def enforce_safe_limit(
        self,
        sql: str,
        default_limit: int = 100,
        max_limit: int = 200,
    ) -> str:
        validator = SQLSafetyValidator(
            max_allowed_limit=max_limit,
            default_limit=default_limit,
            allowed_tables=ALLOWED_TABLES,
            project_id=self.project_id,
        )
        result = validator.validate(sql, request_limit=default_limit)
        if not result.is_valid:
            raise ValueError("; ".join(result.violation_reasons))
        return result.sanitized_sql

    def generate_sql(self, question: str) -> str:
        context = self.service.catalog.get_schema_prompt_context(question)
        return self.service._generate_sql(question, context)

    def synthesize_grounded_answer(
        self,
        question: str,
        sql: str,
        rows: List[Dict[str, Any]],
    ) -> str:
        synthesized = self.service._synthesize_results(question, sql, rows)
        highlights = synthesized.get("result_highlights", [])
        if highlights:
            return synthesized["business_summary"] + "\n" + "\n".join(
                f"- {highlight}" for highlight in highlights
            )
        return synthesized["business_summary"]

    def correct_sql_with_error(self, question: str, failed_sql: str, error_message: str) -> str:
        return self.service._correct_sql_with_error(question, failed_sql, error_message)

    def ask(self, question: str, history: Optional[List[Any]] = None) -> Dict[str, Any]:
        cleaned_question = question.strip() if isinstance(question, str) else ""
        if not cleaned_question:
            return {
                "success": False,
                "error": "Question cannot be empty.",
                "answer": "Please ask about campaigns, merchants, customers, transactions, reviews, or alerts.",
                "sql": None,
                "records_found": 0,
                "data": [],
            }

        chat_history: List[ChatMessage] = []
        if history and isinstance(history, list):
            for item in history[-5:]:
                if isinstance(item, dict) and "role" in item and "content" in item:
                    chat_history.append(ChatMessage(role=str(item["role"]), content=str(item["content"])))
                elif isinstance(item, ChatMessage):
                    chat_history.append(item)

        response = self.service.process_question(
            AnalystChatRequest(question=cleaned_question, history=chat_history)
        )
        return self._to_legacy_response(response)

    @staticmethod
    def _to_legacy_response(response: AnalystChatResponse) -> Dict[str, Any]:
        answer = response.business_summary
        if response.result_highlights:
            answer += "\n" + "\n".join(f"- {item}" for item in response.result_highlights)
        if response.clarification_options:
            answer += "\n\nPlease choose:\n" + "\n".join(
                f"- {option.label}: {option.value}"
                for option in response.clarification_options
            )
        return {
            "success": response.status != "ERROR",
            "error": response.error_message,
            "answer": answer,
            "sql": response.generated_sql,
            "records_found": response.rows_count,
            "data": response.detailed_data[:20],
            "status": response.status,
            "intent": response.intent,
            "result_highlights": response.result_highlights,
            "data_columns": response.data_columns,
            "tables_accessed": response.tables_accessed,
            "execution_time_ms": response.execution_time_ms,
            "bytes_processed": response.bytes_processed,
            "clarification_question": response.clarification_question,
        }
