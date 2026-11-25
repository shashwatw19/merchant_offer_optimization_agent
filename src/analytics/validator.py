"""Read-only SQL validation, allowlisting, and result-limit enforcement."""

import re
from typing import Iterable, List, Optional, Set, Tuple

from analytics.models import SQLValidationResult


FORBIDDEN_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "MERGE",
    "TRUNCATE",
    "CREATE",
    "ALTER",
    "DROP",
    "EXECUTE",
    "CALL",
    "PROCEDURE",
    "FUNCTION",
    "GRANT",
    "REVOKE",
    "ASSERT",
    "EXPORT",
    "LOAD",
    "INFORMATION_SCHEMA",
)
FORBIDDEN_PATTERNS = tuple(
    (keyword, re.compile(rf"\b{re.escape(keyword)}\b", re.IGNORECASE))
    for keyword in FORBIDDEN_KEYWORDS
)
REPLACE_DDL_PATTERN = re.compile(
    r"\bREPLACE\s+(?:TABLE|VIEW|PROCEDURE)\b",
    re.IGNORECASE,
)
TABLE_PATTERN = re.compile(
    r"\b(?:FROM|JOIN)\s+(?:`(?P<quoted>[^`]+)`|(?P<unquoted>[A-Za-z0-9_.$-]+))",
    re.IGNORECASE,
)
LIMIT_PATTERN = re.compile(r"\bLIMIT\s+(\d+)(?:\s+OFFSET\s+\d+)?\s*$", re.IGNORECASE)
SCALAR_FROM_PATTERN = re.compile(r"\b(EXTRACT|TRIM|SUBSTRING)\s*\(", re.IGNORECASE)


def _strip_comments(sql: str) -> str:
    """Remove SQL comments while preserving quoted text and line boundaries."""
    output: List[str] = []
    index = 0
    quote: Optional[str] = None
    while index < len(sql):
        char = sql[index]
        if quote:
            output.append(char)
            if char == "\\" and quote != "`" and index + 1 < len(sql):
                index += 1
                output.append(sql[index])
            elif char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 1
                    output.append(sql[index])
                else:
                    quote = None
        elif char in ("'", '"', "`"):
            quote = char
            output.append(char)
        elif sql.startswith("--", index) or char == "#":
            while index < len(sql) and sql[index] not in "\r\n":
                index += 1
            if index < len(sql):
                output.append(sql[index])
        elif sql.startswith("/*", index):
            index += 2
            while index < len(sql) and not sql.startswith("*/", index):
                if sql[index] in "\r\n":
                    output.append(sql[index])
                index += 1
            index = min(index + 2, len(sql))
            output.append(" ")
            continue
        else:
            output.append(char)
        index += 1
    return "".join(output).strip()


def _analysis_sql(sql: str) -> str:
    """Blank string literals without changing offsets; keep quoted identifiers."""
    result = list(sql)
    index = 0
    while index < len(sql):
        if sql[index] not in ("'", '"'):
            index += 1
            continue
        quote = sql[index]
        result[index] = " "
        index += 1
        while index < len(sql):
            char = sql[index]
            result[index] = "\n" if char in "\r\n" else " "
            if char == "\\" and index + 1 < len(sql):
                index += 1
                result[index] = "\n" if sql[index] in "\r\n" else " "
            elif char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 1
                    result[index] = " "
                else:
                    index += 1
                    break
            index += 1
    return "".join(result)


def _mask_scalar_functions(sql: str) -> str:
    """Mask 'FROM' keyword inside scalar functions like EXTRACT, TRIM, SUBSTRING."""
    result = list(sql)
    for match in SCALAR_FROM_PATTERN.finditer(sql):
        depth = 1
        i = match.end()
        start = i
        while i < len(result) and depth > 0:
            if result[i] == "(":
                depth += 1
            elif result[i] == ")":
                depth -= 1
            i += 1
        segment = "".join(result[start : max(start, i - 1)])
        for from_match in re.finditer(r"\bFROM\b", segment, re.IGNORECASE):
            for idx in range(start + from_match.start(), start + from_match.end()):
                result[idx] = " "
    return "".join(result)


def _split_statements(sql: str) -> List[str]:
    """Split on semicolons outside strings and quoted identifiers."""
    statements: List[str] = []
    start = 0
    quote: Optional[str] = None
    index = 0
    while index < len(sql):
        char = sql[index]
        if quote:
            if char == "\\" and quote != "`":
                index += 1
            elif char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 1
                else:
                    quote = None
        elif char in ("'", '"', "`"):
            quote = char
        elif char == ";":
            statements.append(sql[start:index].strip())
            start = index + 1
        index += 1
    statements.append(sql[start:].strip())
    return [statement for statement in statements if statement]


class SQLSafetyValidator:
    """Validates one read-only query against the Merchant Silver/Gold catalog."""

    def __init__(
        self,
        max_allowed_limit: int = 200,
        default_limit: int = 100,
        allowed_tables: Optional[Iterable[str]] = None,
        project_id: Optional[str] = None,
    ):
        self.max_allowed_limit = max_allowed_limit
        self.default_limit = default_limit
        self.allowed_tables: Optional[Set[str]] = (
            {name.lower() for name in allowed_tables} if allowed_tables is not None else None
        )
        self.project_id = project_id.lower() if project_id else None

    def strip_comments(self, sql: str) -> str:
        return _strip_comments(sql)

    def extract_tables(self, sql: str) -> List[str]:
        analysis = _mask_scalar_functions(_analysis_sql(sql))
        cte_names = {
            match.group(1).lower()
            for match in re.finditer(
                r"(?:\bWITH\b|,)\s*(?:RECURSIVE\s+)?([A-Za-z_][A-Za-z0-9_]*)\s+AS\s*\(",
                analysis,
                re.IGNORECASE,
            )
        }
        tables: Set[str] = set()
        for match in TABLE_PATTERN.finditer(analysis):
            name = (match.group("quoted") or match.group("unquoted") or "").strip()
            if not name or name.upper() == "UNNEST":
                continue
            parts = [part.strip("`").lower() for part in name.split(".")]
            if len(parts) == 1 and parts[0] in cte_names:
                continue
            if len(parts) == 3:
                project, dataset, table = parts
                if self.project_id and project != self.project_id:
                    tables.add(f"{project}.{dataset}.{table}")
                else:
                    tables.add(f"{dataset}.{table}")
            elif len(parts) == 2:
                tables.add(f"{parts[0]}.{parts[1]}")
            elif len(parts) == 1:
                tables.add(parts[0])
            else:
                tables.add(name.lower())
        return sorted(tables)

    def validate(self, sql: str, request_limit: Optional[int] = 100) -> SQLValidationResult:
        if not sql or not sql.strip():
            return SQLValidationResult(
                is_valid=False,
                sanitized_sql="",
                violation_reasons=["SQL query cannot be empty."],
                is_readonly=False,
            )

        cleaned_sql = self.strip_comments(sql)
        statements = _split_statements(cleaned_sql)
        if len(statements) != 1:
            return SQLValidationResult(
                is_valid=False,
                sanitized_sql="",
                violation_reasons=["Multiple SQL statements are forbidden."],
                is_readonly=False,
            )
        cleaned_sql = statements[0]
        analysis = _analysis_sql(cleaned_sql)
        first_token_match = re.match(r"^\s*([A-Za-z]+)", analysis)
        if not first_token_match or first_token_match.group(1).upper() not in ("SELECT", "WITH"):
            token = first_token_match.group(1).upper() if first_token_match else "UNKNOWN"
            return SQLValidationResult(
                is_valid=False,
                sanitized_sql="",
                violation_reasons=[f"Only SELECT or WITH statements are allowed (found {token})."],
                is_readonly=False,
            )

        violations = [
            f"Forbidden keyword '{keyword}' detected."
            for keyword, pattern in FORBIDDEN_PATTERNS
            if pattern.search(analysis)
        ]
        if REPLACE_DDL_PATTERN.search(analysis):
            violations.append("Forbidden REPLACE DDL operation detected.")
        tables = self.extract_tables(cleaned_sql)
        if self.allowed_tables is not None:
            for table in tables:
                if table not in self.allowed_tables:
                    violations.append(f"Table '{table}' is outside the permitted catalog.")

        if violations:
            return SQLValidationResult(
                is_valid=False,
                sanitized_sql="",
                tables_accessed=tables,
                violation_reasons=violations,
                is_readonly=False,
            )

        limit_match = LIMIT_PATTERN.search(analysis)
        has_limit = limit_match is not None
        injected_limit: Optional[int] = None
        effective_limit = min(
            request_limit if request_limit is not None else self.default_limit,
            self.max_allowed_limit,
        )
        if limit_match:
            current_limit = int(limit_match.group(1))
            if current_limit > self.max_allowed_limit:
                cleaned_sql = LIMIT_PATTERN.sub(f"LIMIT {self.max_allowed_limit}", cleaned_sql)
                injected_limit = self.max_allowed_limit
        else:
            cleaned_sql = f"{cleaned_sql.rstrip().rstrip(';')}\nLIMIT {effective_limit}"
            injected_limit = effective_limit

        return SQLValidationResult(
            is_valid=True,
            sanitized_sql=cleaned_sql,
            tables_accessed=tables,
            has_limit=has_limit,
            injected_limit=injected_limit,
            is_readonly=True,
        )
