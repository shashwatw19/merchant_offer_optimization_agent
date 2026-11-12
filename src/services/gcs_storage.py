import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union
from google.api_core import exceptions as g_exceptions
from google.cloud import storage
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from core.config import get_config
from core.exceptions import StorageError
from core.logging import logger
from core.resilience import TRANSIENT_EXCEPTIONS, classify_error
from core.time_utils import now_ist_str

_STORAGE_CLIENT: Optional[storage.Client] = None
_STORAGE_SERVICE_INSTANCE: Optional["GCSStorageService"] = None


@dataclass
class StorageResult:
    """Result of a cloud or local fallback storage operation."""
    success: bool
    uri: str
    bucket: str
    object_name: str
    content_type: str
    size_bytes: int = 0
    is_fallback: bool = False
    local_path: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None


def get_storage_client(project_id: Optional[str] = None) -> storage.Client:
    """Lazy initialize and return the official Google Cloud Storage client."""
    global _STORAGE_CLIENT
    if _STORAGE_CLIENT is not None:
        return _STORAGE_CLIENT

    config = get_config()
    target_project = project_id or getattr(config.gcp, "project_id", None)
    try:
        _STORAGE_CLIENT = storage.Client(project=target_project)
        return _STORAGE_CLIENT
    except Exception as exc:
        logger.warning(f"Could not initialize Google Cloud Storage client: {exc}")
        raise StorageError(
            f"Google Cloud Storage client initialization failed: {exc}",
            retryable=False,
            is_transient=False,
        ) from exc


def set_storage_client(client: Optional[storage.Client]) -> None:
    """Override the storage client singleton (used for tests and dependency injection)."""
    global _STORAGE_CLIENT
    _STORAGE_CLIENT = client


class GCSStorageService:
    """Enterprise storage service managing report persistence to GCS with local fallback."""

    def __init__(
        self,
        bucket_name: Optional[str] = None,
        project_id: Optional[str] = None,
        client: Optional[storage.Client] = None,
        config: Optional[Any] = None,
    ):
        self.config = config or get_config()
        self.project_id = project_id or getattr(self.config.gcp, "project_id", None)
        
        # Resolve bucket name from argument, config storage, or fallback
        configured_bucket = None
        if hasattr(self.config, "storage") and hasattr(self.config.storage, "bucket_name"):
            configured_bucket = self.config.storage.bucket_name
        self.bucket_name = bucket_name or configured_bucket or f"{self.project_id}-reports"
        
        self._custom_client = client
        self.prefix = getattr(getattr(self.config, "storage", None), "reports_prefix", "reports")
        self.local_dir = Path(getattr(getattr(self.config, "storage", None), "local_fallback_dir", "output"))
        self.enabled = getattr(getattr(self.config, "storage", None), "enabled", True)

    @property
    def client(self) -> storage.Client:
        """Return the active storage client or custom override."""
        if self._custom_client is not None:
            return self._custom_client
        return get_storage_client(self.project_id)

    def build_object_path(
        self,
        category: str,
        execution_id: str,
        extension: str,
        date: Optional[datetime] = None,
    ) -> str:
        """Construct standard partitioned path: reports/<category>/YYYY/MM/DD/<execution_id>.<ext>."""
        dt = date or datetime.now(timezone.utc)
        clean_ext = extension.lstrip(".")
        return f"{self.prefix}/{category}/{dt.year:04d}/{dt.month:02d}/{dt.day:02d}/{execution_id}.{clean_ext}"

    def _clean_path(self, path_or_uri: str) -> str:
        """Normalize a gs:// URI or relative path into an object name."""
        if path_or_uri.startswith("gs://"):
            parts = path_or_uri[5:].split("/", 1)
            return parts[1] if len(parts) > 1 else ""
        return path_or_uri.lstrip("/")

    def _write_local_fallback(
        self,
        data: bytes,
        relative_path: str,
        metadata: Optional[Dict[str, str]] = None,
        error_msg: Optional[str] = None,
    ) -> StorageResult:
        """Safely buffer report to local filesystem when GCS is unreachable or disabled."""
        local_target = (self.local_dir / relative_path).resolve()
        local_target.parent.mkdir(parents=True, exist_ok=True)

        with open(local_target, "wb") as f:
            f.write(data)

        # Write sidecar metadata if present
        if metadata:
            meta_file = local_target.with_suffix(local_target.suffix + ".meta.json")
            try:
                with open(meta_file, "w", encoding="utf-8") as mf:
                    json.dump(metadata, mf, indent=2)
            except Exception as meta_exc:
                logger.warning(f"Failed writing local metadata sidecar {meta_file}: {meta_exc}")

        logger.info(
            f"Persisted report to local fallback buffer: {local_target}",
            extra={"local_path": str(local_target), "is_fallback": True},
        )

        return StorageResult(
            success=True,
            uri=local_target.as_uri(),
            bucket="local_filesystem",
            object_name=relative_path,
            content_type="application/octet-stream",
            size_bytes=len(data),
            is_fallback=True,
            local_path=str(local_target),
            metadata=metadata or {},
            error=error_msg,
        )

    def upload_bytes(
        self,
        data: bytes,
        destination_path: str,
        content_type: str = "application/octet-stream",
        metadata: Optional[Dict[str, str]] = None,
        allow_fallback: bool = True,
    ) -> StorageResult:
        """Upload raw bytes to GCS with Tenacity exponential retry and local fallback."""
        clean_path = self._clean_path(destination_path)
        gcs_uri = f"gs://{self.bucket_name}/{clean_path}"

        if not self.enabled:
            logger.info(f"GCS storage disabled via config. Using local fallback for {clean_path}")
            return self._write_local_fallback(
                data=data,
                relative_path=clean_path,
                metadata=metadata,
                error_msg="GCS storage disabled via configuration",
            )

        max_retries = getattr(getattr(self.config, "storage", None), "retry_count", 3)
        timeout_sec = getattr(getattr(self.config, "storage", None), "timeout_sec", 15.0)

        retryer = Retrying(
            stop=stop_after_attempt(max_retries),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=2.0),
            retry=retry_if_exception_type(TRANSIENT_EXCEPTIONS),
            reraise=True,
        )

        try:
            client = self.client
            bucket = client.bucket(self.bucket_name)
            blob = bucket.blob(clean_path)

            if metadata:
                blob.metadata = metadata

            for attempt in retryer:
                with attempt:
                    blob.upload_from_string(
                        data=data,
                        content_type=content_type,
                        timeout=timeout_sec,
                    )

            logger.info(f"Successfully uploaded {clean_path} to {gcs_uri} ({len(data)} bytes)")
            return StorageResult(
                success=True,
                uri=gcs_uri,
                bucket=self.bucket_name,
                object_name=clean_path,
                content_type=content_type,
                size_bytes=len(data),
                is_fallback=False,
                metadata=metadata or {},
            )

        except Exception as exc:
            is_transient = classify_error(exc)
            logger.error(
                f"Failed uploading {clean_path} to GCS ({gcs_uri}): {exc} (transient={is_transient})",
                extra={"gcs_uri": gcs_uri, "error": str(exc)},
            )
            if allow_fallback:
                return self._write_local_fallback(
                    data=data,
                    relative_path=clean_path,
                    metadata=metadata,
                    error_msg=f"GCS upload failed: {exc}",
                )
            raise StorageError(
                f"Failed uploading object to {gcs_uri}: {exc}",
                retryable=is_transient,
                is_transient=is_transient,
            ) from exc

    def upload_json(
        self,
        report_data: Union[Dict[str, Any], str],
        execution_id: str,
        alert_id: Optional[str] = None,
        campaign_id: Optional[str] = None,
        date: Optional[datetime] = None,
        custom_path: Optional[str] = None,
    ) -> StorageResult:
        """Upload canonical JSON report to GCS under partitioned path."""
        if isinstance(report_data, str):
            json_str = report_data
        else:
            json_str = json.dumps(report_data, indent=2, default=str)

        dest_path = custom_path or self.build_object_path(
            category="json",
            execution_id=execution_id,
            extension="json",
            date=date,
        )

        metadata = {
            "execution_id": execution_id,
            "report_type": "INVESTIGATION_JSON",
            "created_at": now_ist_str(),
        }
        if alert_id:
            metadata["alert_id"] = str(alert_id)
        if campaign_id:
            metadata["campaign_id"] = str(campaign_id)

        return self.upload_bytes(
            data=json_str.encode("utf-8"),
            destination_path=dest_path,
            content_type="application/json",
            metadata=metadata,
        )

    def upload_markdown(
        self,
        markdown_text: str,
        execution_id: str,
        alert_id: Optional[str] = None,
        campaign_id: Optional[str] = None,
        date: Optional[datetime] = None,
        custom_path: Optional[str] = None,
    ) -> StorageResult:
        """Upload human-readable Markdown report to GCS under partitioned path."""
        dest_path = custom_path or self.build_object_path(
            category="markdown",
            execution_id=execution_id,
            extension="md",
            date=date,
        )

        metadata = {
            "execution_id": execution_id,
            "report_type": "INVESTIGATION_MARKDOWN",
            "created_at": now_ist_str(),
        }
        if alert_id:
            metadata["alert_id"] = str(alert_id)
        if campaign_id:
            metadata["campaign_id"] = str(campaign_id)

        return self.upload_bytes(
            data=markdown_text.encode("utf-8"),
            destination_path=dest_path,
            content_type="text/markdown; charset=utf-8",
            metadata=metadata,
        )

    def object_exists(self, destination_path_or_uri: str) -> bool:
        """Check whether an object exists in GCS or local fallback storage."""
        clean_path = self._clean_path(destination_path_or_uri)
        if not self.enabled:
            return (self.local_dir / clean_path).exists()

        try:
            client = self.client
            bucket = client.bucket(self.bucket_name)
            blob = bucket.blob(clean_path)
            return blob.exists()
        except Exception as exc:
            logger.warning(f"Error checking GCS object existence for {clean_path}: {exc}")
            # Check local fallback
            return (self.local_dir / clean_path).exists()

    def download_text(self, destination_path_or_uri: str) -> str:
        """Download text content from GCS or local fallback."""
        clean_path = self._clean_path(destination_path_or_uri)

        # Check local fallback file first if GCS is disabled or file exists locally
        local_target = self.local_dir / clean_path
        if not self.enabled and local_target.exists():
            with open(local_target, "r", encoding="utf-8") as f:
                return f.read()

        try:
            client = self.client
            bucket = client.bucket(self.bucket_name)
            blob = bucket.blob(clean_path)
            return blob.download_as_text(encoding="utf-8")
        except Exception as exc:
            if local_target.exists():
                logger.info(f"Retrieved {clean_path} from local fallback buffer.")
                with open(local_target, "r", encoding="utf-8") as f:
                    return f.read()
            raise StorageError(f"Failed downloading object {clean_path}: {exc}") from exc

    def download_json(self, destination_path_or_uri: str) -> Dict[str, Any]:
        """Download and parse JSON document from GCS or local fallback."""
        text = self.download_text(destination_path_or_uri)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise StorageError(f"Downloaded object {destination_path_or_uri} is not valid JSON: {exc}") from exc


def get_storage_service(
    bucket_name: Optional[str] = None,
    project_id: Optional[str] = None,
) -> GCSStorageService:
    """Return the global GCS storage service instance."""
    global _STORAGE_SERVICE_INSTANCE
    if _STORAGE_SERVICE_INSTANCE is None:
        _STORAGE_SERVICE_INSTANCE = GCSStorageService(
            bucket_name=bucket_name,
            project_id=project_id,
        )
    return _STORAGE_SERVICE_INSTANCE
