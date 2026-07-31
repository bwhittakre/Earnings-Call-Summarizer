"""Durable storage primitives for the earnings monitor.

The module deliberately has no dependency on the rest of the service.  Callers
may pass mappings, dataclasses, pydantic models, or simple objects as records.
Optional dependencies (pandas/pyarrow and boto3) are imported only when used.
"""
from __future__ import annotations

import csv
import dataclasses
import hashlib
import io
import json
import os
import re
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator, Mapping, Sequence


class StorageError(RuntimeError):
    """Base storage error."""


class ImmutableArtifactError(StorageError):
    """Raised when an existing artifact would be changed."""


class UnsafeArtifactKey(StorageError, ValueError):
    """Raised for absolute or parent-traversing artifact keys."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def record_to_dict(record: Any) -> dict[str, Any]:
    """Convert a loose duck-typed record into a plain dictionary."""
    if isinstance(record, Mapping):
        return dict(record)
    if dataclasses.is_dataclass(record) and not isinstance(record, type):
        return dataclasses.asdict(record)
    for method_name in ("model_dump", "dict", "to_dict"):
        method = getattr(record, method_name, None)
        if callable(method):
            value = method()
            if isinstance(value, Mapping):
                return dict(value)
    attrs = getattr(record, "__dict__", None)
    if isinstance(attrs, Mapping):
        return {key: value for key, value in attrs.items() if not key.startswith("_")}
    raise TypeError(f"Unsupported record type: {type(record).__name__}")


def normalize_company_quarter_record(record: Any) -> dict[str, Any]:
    """Normalize identifiers while preserving all source fields."""
    row = record_to_dict(record)
    ticker = row.get("ticker", row.get("symbol", row.get("company")))
    period = row.get(
        "fiscal_period",
        row.get("fiscal_quarter", row.get("quarter", row.get("period"))),
    )
    if ticker is None or not str(ticker).strip():
        raise ValueError("company-quarter record requires ticker/symbol/company")
    if period is None or not str(period).strip():
        raise ValueError("company-quarter record requires fiscal_period/quarter/period")
    row["ticker"] = str(ticker).strip().upper()
    row["fiscal_period"] = str(period).strip().upper()
    return {str(key): _json_default(value) for key, value in row.items()}


def _safe_key(key: str) -> str:
    cleaned = str(key).replace("\\", "/").strip("/")
    path = PurePosixPath(cleaned)
    if not cleaned or path.is_absolute() or ".." in path.parts:
        raise UnsafeArtifactKey(f"Unsafe artifact key: {key!r}")
    return path.as_posix()


@dataclass(frozen=True)
class ArtifactRef:
    key: str
    uri: str
    size: int
    sha256: str
    created_at: str
    metadata: Mapping[str, str] = field(default_factory=dict)


class ArtifactStore(ABC):
    """Small immutable object-store interface shared by local and S3 backends."""

    @abstractmethod
    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        metadata: Mapping[str, str] | None = None,
    ) -> ArtifactRef:
        raise NotImplementedError

    @abstractmethod
    def get_bytes(self, key: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def exists(self, key: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def list(self, prefix: str = "") -> Iterable[ArtifactRef]:
        raise NotImplementedError

    def put_text(
        self,
        key: str,
        text: str,
        *,
        metadata: Mapping[str, str] | None = None,
    ) -> ArtifactRef:
        return self.put_bytes(key, text.encode("utf-8"), metadata=metadata)

    def get_text(self, key: str) -> str:
        return self.get_bytes(key).decode("utf-8")

    def put_json(
        self,
        key: str,
        value: Any,
        *,
        metadata: Mapping[str, str] | None = None,
    ) -> ArtifactRef:
        payload = json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            default=_json_default,
            separators=(",", ":"),
        )
        return self.put_text(key, payload, metadata=metadata)

    def get_json(self, key: str) -> Any:
        return json.loads(self.get_text(key))


class LocalArtifactStore(ArtifactStore):
    """Filesystem-backed immutable artifact store.

    Repeating a write with identical bytes is idempotent.  Writing different
    bytes to an existing key raises :class:`ImmutableArtifactError`.
    """

    _META_SUFFIX = ".artifact-meta.json"

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / _safe_key(key)).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise UnsafeArtifactKey(f"Artifact escapes store root: {key!r}") from exc
        return path

    def _metadata_path(self, path: Path) -> Path:
        return path.with_name(path.name + self._META_SUFFIX)

    def _ref(self, key: str, path: Path) -> ArtifactRef:
        payload = path.read_bytes()
        meta_path = self._metadata_path(path)
        metadata: dict[str, str] = {}
        created_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(
            timespec="seconds"
        )
        if meta_path.is_file():
            try:
                sidecar = json.loads(meta_path.read_text(encoding="utf-8"))
                metadata = {
                    str(k): str(v) for k, v in sidecar.get("metadata", {}).items()
                }
                created_at = str(sidecar.get("created_at", created_at))
            except (OSError, ValueError, TypeError):
                metadata = {}
        return ArtifactRef(
            key=key,
            uri=path.as_uri(),
            size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            created_at=created_at,
            metadata=metadata,
        )

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        metadata: Mapping[str, str] | None = None,
    ) -> ArtifactRef:
        key = _safe_key(key)
        if not isinstance(data, bytes):
            raise TypeError("data must be bytes")
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(data).hexdigest()
        try:
            with path.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            existing = path.read_bytes()
            if hashlib.sha256(existing).hexdigest() != digest:
                raise ImmutableArtifactError(f"Artifact already exists with different bytes: {key}")
            return self._ref(key, path)

        sidecar = {
            "key": key,
            "sha256": digest,
            "size": len(data),
            "created_at": _utc_now(),
            "metadata": {str(k): str(v) for k, v in (metadata or {}).items()},
        }
        meta_path = self._metadata_path(path)
        try:
            with meta_path.open("x", encoding="utf-8") as handle:
                json.dump(sidecar, handle, sort_keys=True, separators=(",", ":"))
        except FileExistsError:
            pass
        return self._ref(key, path)

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def list(self, prefix: str = "") -> Iterator[ArtifactRef]:
        normalized_prefix = str(prefix).replace("\\", "/").strip("/")
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.name.endswith(self._META_SUFFIX):
                continue
            key = path.relative_to(self.root).as_posix()
            if not normalized_prefix or key.startswith(normalized_prefix):
                yield self._ref(key, path)


class S3ArtifactStore(ArtifactStore):
    """S3-compatible immutable store using a duck-typed boto3-style client."""

    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "",
        client: Any | None = None,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        region_name: str = "auto",
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        if client is None:
            try:
                import boto3  # type: ignore
            except ImportError as exc:
                raise RuntimeError("boto3 is required when no S3 client is supplied") from exc
            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                region_name=region_name,
            )
        self.client = client

    def _object_key(self, key: str) -> str:
        key = _safe_key(key)
        return f"{self.prefix}/{key}" if self.prefix else key

    def _logical_key(self, object_key: str) -> str:
        if self.prefix and object_key.startswith(self.prefix + "/"):
            return object_key[len(self.prefix) + 1 :]
        return object_key

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        metadata: Mapping[str, str] | None = None,
    ) -> ArtifactRef:
        logical_key = _safe_key(key)
        object_key = self._object_key(logical_key)
        digest = hashlib.sha256(data).hexdigest()
        object_metadata = {str(k): str(v) for k, v in (metadata or {}).items()}
        object_metadata.update({"sha256": digest, "created-at": _utc_now()})
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=data,
                Metadata=object_metadata,
                IfNoneMatch="*",
            )
        except Exception as exc:
            # S3 implementations differ in exception classes.  Verify content
            # after any conditional-put failure; only identical content is safe.
            try:
                existing = self.get_bytes(logical_key)
            except Exception:
                raise StorageError(f"Unable to write s3://{self.bucket}/{object_key}") from exc
            if hashlib.sha256(existing).hexdigest() != digest:
                raise ImmutableArtifactError(
                    f"Artifact already exists with different bytes: {logical_key}"
                ) from exc
        return ArtifactRef(
            key=logical_key,
            uri=f"s3://{self.bucket}/{object_key}",
            size=len(data),
            sha256=digest,
            created_at=object_metadata["created-at"],
            metadata={k: v for k, v in object_metadata.items() if k not in {"sha256", "created-at"}},
        )

    def get_bytes(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=self._object_key(key))
        body = response["Body"]
        return body.read() if hasattr(body, "read") else bytes(body)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._object_key(key))
            return True
        except Exception:
            return False

    def list(self, prefix: str = "") -> Iterator[ArtifactRef]:
        object_prefix = self._object_key(prefix) if prefix else (
            self.prefix + "/" if self.prefix else ""
        )
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "Bucket": self.bucket,
                "Prefix": object_prefix,
            }
            if token:
                kwargs["ContinuationToken"] = token
            response = self.client.list_objects_v2(**kwargs)
            for item in response.get("Contents", []):
                object_key = str(item["Key"])
                logical_key = self._logical_key(object_key)
                head = self.client.head_object(Bucket=self.bucket, Key=object_key)
                metadata = dict(head.get("Metadata", {}))
                yield ArtifactRef(
                    key=logical_key,
                    uri=f"s3://{self.bucket}/{object_key}",
                    size=int(item.get("Size", head.get("ContentLength", 0))),
                    sha256=metadata.pop("sha256", ""),
                    created_at=metadata.pop(
                        "created-at",
                        str(item.get("LastModified", "")),
                    ),
                    metadata=metadata,
                )
            token = response.get("NextContinuationToken")
            if not token:
                break


@dataclass(frozen=True)
class EventPublication:
    manifest: ArtifactRef
    artifacts: tuple[ArtifactRef, ...]


class CompletedEventArtifactPublisher:
    """Publish immutable completed-event artifacts and a final marker.

    Content objects are uploaded first under a fingerprinted event prefix. The
    manifest is written last, so its presence means the publication is complete.
    Repeating a partially completed publication is safe because every write uses
    the immutable :class:`ArtifactStore` contract.
    """

    def __init__(self, store: ArtifactStore, repo_root: str | os.PathLike[str]) -> None:
        self.store = store
        self.repo_root = Path(repo_root).resolve()

    @staticmethod
    def _segment(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
        return cleaned or "unknown"

    def publish(
        self,
        *,
        event: Any,
        fingerprint: str,
        workflow_result: Mapping[str, Any],
        completed_at: str,
    ) -> EventPublication:
        base = PurePosixPath(
            "events",
            self._segment(str(event.ticker)),
            self._segment(str(event.fiscal_period)),
            self._segment(str(event.provider_event_id)),
            self._segment(fingerprint),
        )
        metadata = {
            "ticker": str(event.ticker),
            "fiscal-period": str(event.fiscal_period),
            "provider-event-id": str(event.provider_event_id),
            "fingerprint": fingerprint,
        }
        artifacts: list[ArtifactRef] = []
        source_paths: list[Path] = []
        transcript_path = workflow_result.get("transcript_path")
        if transcript_path:
            source_paths.append(Path(str(transcript_path)).resolve())
        # Workflows may explicitly identify outputs produced for this event.
        # Never infer them by walking a company directory: those directories
        # contain historical quarters that are unrelated to this publication.
        artifact_paths = workflow_result.get("artifact_paths") or ()
        if isinstance(artifact_paths, (str, bytes)) or not isinstance(
            artifact_paths, Sequence
        ):
            raise StorageError("workflow_result artifact_paths must be a sequence")
        source_paths.extend(Path(str(path)).resolve() for path in artifact_paths)
        for path in dict.fromkeys(source_paths):
            try:
                relative = path.relative_to(self.repo_root)
            except ValueError as exc:
                raise StorageError(f"Artifact is outside repository: {path}") from exc
            if path.suffix.lower() in {".sqlite", ".sqlite3", ".db", ".db-wal", ".db-shm"}:
                raise StorageError(f"Refusing to publish live database artifact: {path}")
            if not path.is_file():
                raise StorageError(f"Completed event artifact is missing: {path}")
            artifacts.append(
                self.store.put_bytes(
                    (base / "files" / relative.as_posix()).as_posix(),
                    path.read_bytes(),
                    metadata=metadata,
                )
            )

        result_payload = {
            "schema": "earnings-monitor/completed-workflow/v1",
            "provider_event_id": event.provider_event_id,
            "ticker": event.ticker,
            "fiscal_period": event.fiscal_period,
            "fingerprint": fingerprint,
            "completed_at": completed_at,
            "workflow_result": dict(workflow_result),
        }
        artifacts.append(
            self.store.put_json(
                (base / "workflow-result.json").as_posix(),
                result_payload,
                metadata=metadata,
            )
        )
        manifest_payload = {
            "schema": "earnings-monitor/event-publication/v1",
            "provider_event_id": event.provider_event_id,
            "ticker": event.ticker,
            "fiscal_period": event.fiscal_period,
            "fingerprint": fingerprint,
            "completed_at": completed_at,
            "artifacts": [
                {
                    "key": ref.key,
                    "uri": ref.uri,
                    "size": ref.size,
                    "sha256": ref.sha256,
                }
                for ref in artifacts
            ],
        }
        manifest = self.store.put_json(
            (base / "complete.json").as_posix(),
            manifest_payload,
            metadata=metadata,
        )
        return EventPublication(manifest=manifest, artifacts=tuple(artifacts))


@dataclass(frozen=True)
class DatasetWriteResult:
    requested_path: Path
    data_path: Path
    manifest_path: Path
    format: str
    row_count: int
    fallback_reason: str | None = None


def _parquet_available() -> bool:
    try:
        import pyarrow  # noqa: F401
        import pandas  # noqa: F401
    except ImportError:
        return False
    return True


def _ordered_rows(records: Iterable[Any]) -> list[dict[str, Any]]:
    rows = [normalize_company_quarter_record(record) for record in records]
    rows.sort(
        key=lambda row: (
            row["ticker"],
            row["fiscal_period"],
            str(row.get("dimension", "")),
            str(row.get("source_path", "")),
        )
    )
    return rows


def write_company_quarter_dataset(
    path: str | os.PathLike[str],
    records: Iterable[Any],
    *,
    metadata: Mapping[str, Any] | None = None,
    prefer_parquet: bool = True,
) -> DatasetWriteResult:
    """Write normalized records to Parquet or an explicit JSONL fallback.

    The fallback never writes JSON under a ``.parquet`` name.  A manifest beside
    the requested path records the actual format/path so readers cannot confuse
    the two encodings.
    """
    requested = Path(path)
    requested.parent.mkdir(parents=True, exist_ok=True)
    rows = _ordered_rows(records)
    fallback_reason: str | None = None
    data_path = requested
    data_format = "parquet"

    if prefer_parquet and _parquet_available():
        try:
            import pandas as pd  # type: ignore

            frame = pd.DataFrame(rows)
            with tempfile.NamedTemporaryFile(
                dir=requested.parent,
                prefix=requested.name + ".",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
            try:
                frame.to_parquet(temporary, index=False, engine="pyarrow")
                os.replace(temporary, requested)
            finally:
                temporary.unlink(missing_ok=True)
        except Exception as exc:
            fallback_reason = f"{type(exc).__name__}: {exc}"
            data_format = "jsonl"
            data_path = requested.with_suffix(".jsonl")
    else:
        data_format = "jsonl"
        data_path = requested.with_suffix(".jsonl")
        if prefer_parquet:
            fallback_reason = "pyarrow/pandas unavailable"

    if data_format == "jsonl":
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=data_path.parent,
            prefix=data_path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            for row in rows:
                handle.write(
                    json.dumps(
                        row,
                        sort_keys=True,
                        ensure_ascii=False,
                        default=_json_default,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
        os.replace(temporary, data_path)

    manifest_path = requested.with_suffix(".manifest.json")
    manifest = {
        "schema": "earnings-monitor/company-quarter/v1",
        "created_at": _utc_now(),
        "format": data_format,
        "requested_path": requested.name,
        "data_path": data_path.name,
        "row_count": len(rows),
        "columns": sorted({key for row in rows for key in row}),
        "fallback_reason": fallback_reason,
        "metadata": dict(metadata or {}),
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )
    return DatasetWriteResult(
        requested_path=requested,
        data_path=data_path,
        manifest_path=manifest_path,
        format=data_format,
        row_count=len(rows),
        fallback_reason=fallback_reason,
    )


def read_company_quarter_dataset(
    path: str | os.PathLike[str],
) -> list[dict[str, Any]]:
    """Read a dataset using its manifest, with safe legacy path detection."""
    requested = Path(path)
    manifest_path = requested.with_suffix(".manifest.json")
    data_path = requested
    data_format = "parquet"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        data_path = manifest_path.parent / manifest["data_path"]
        data_format = manifest["format"]
    elif not requested.is_file() and requested.with_suffix(".jsonl").is_file():
        data_path = requested.with_suffix(".jsonl")
        data_format = "jsonl"
    elif requested.suffix.lower() in {".jsonl", ".ndjson"}:
        data_format = "jsonl"
    elif requested.suffix.lower() == ".csv":
        data_format = "csv"

    if data_format == "parquet":
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                f"Cannot read Parquet dataset {data_path}; install pandas and pyarrow"
            ) from exc
        return [
            {str(key): _json_default(value) for key, value in row.items()}
            for row in pd.read_parquet(data_path).to_dict(orient="records")
        ]
    if data_format == "csv":
        with data_path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    if data_format != "jsonl":
        raise ValueError(f"Unsupported dataset format: {data_format}")
    rows: list[dict[str, Any]] = []
    with data_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


class CompanyQuarterDataset:
    """Convenience wrapper around normalized dataset read/write functions."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def write(
        self,
        records: Iterable[Any],
        *,
        metadata: Mapping[str, Any] | None = None,
        prefer_parquet: bool = True,
    ) -> DatasetWriteResult:
        return write_company_quarter_dataset(
            self.path,
            records,
            metadata=metadata,
            prefer_parquet=prefer_parquet,
        )

    def read(self) -> list[dict[str, Any]]:
        return read_company_quarter_dataset(self.path)


# Short aliases for service code and older plan drafts.
LocalStore = LocalArtifactStore
S3Store = S3ArtifactStore
write_dataset = write_company_quarter_dataset
read_dataset = read_company_quarter_dataset
