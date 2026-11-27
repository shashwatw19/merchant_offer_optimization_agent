"""Request, response, catalog, validation, and query metric models."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ColumnMetadata(BaseModel):
    name: str
    data_type: str
    description: str
    is_partition_key: bool = False
    is_clustering_key: bool = False
    sample_values: Optional[List[str]] = None


class TableMetadata(BaseModel):
    table_id: str
    dataset_id: str
    full_table_name: str
    description: str
    business_name: str
    columns: List[ColumnMetadata]
    business_synonyms: List[str] = Field(default_factory=list)
    common_joins: Optional[List[str]] = None


class SQLValidationResult(BaseModel):
    is_valid: bool
    sanitized_sql: str
    tables_accessed: List[str] = Field(default_factory=list)
    has_limit: bool = False
    injected_limit: Optional[int] = None
    violation_reasons: List[str] = Field(default_factory=list)
    is_readonly: bool = True


class QueryExecutionMetric(BaseModel):
    query_id: str
    user_question: str
    sql: str
    validation_status: str
    tables_accessed: List[str]
    execution_time_ms: float
    rows_returned: int
    bytes_processed: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().astimezone().isoformat())
    error: Optional[str] = None


class ClarificationOption(BaseModel):
    label: str
    value: str
    description: Optional[str] = None


class ChatMessage(BaseModel):
    role: str = Field(description="Role of the sender: 'user' or 'assistant'")
    content: str = Field(description="Text content of the message")


class AnalystChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000, description="Natural-language question")
    session_id: Optional[str] = Field(default=None, max_length=128)
    include_sql: bool = True
    max_rows: Optional[int] = Field(default=100, ge=1, le=500)
    history: List[ChatMessage] = Field(default_factory=list, description="Recent conversation messages for context")


class AnalystChatResponse(BaseModel):
    status: Literal["SUCCESS", "CLARIFICATION_NEEDED", "DIRECT_RESPONSE", "ERROR"]
    intent: str
    user_question: str
    business_summary: str
    result_highlights: List[str] = Field(default_factory=list)
    detailed_data: List[Dict[str, Any]] = Field(default_factory=list)
    data_columns: List[str] = Field(default_factory=list)
    generated_sql: Optional[str] = None
    clarification_question: Optional[str] = None
    clarification_options: List[ClarificationOption] = Field(default_factory=list)
    execution_time_ms: float = 0.0
    rows_count: int = 0
    tables_accessed: List[str] = Field(default_factory=list)
    bytes_processed: Optional[int] = None
    error_message: Optional[str] = None
