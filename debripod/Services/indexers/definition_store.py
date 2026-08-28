from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

import requests
import yaml

from .cardigann.schema import CardigannDefinition


class DefinitionStore:
    def __init__(self, repo_root: str | Path | None = None, *, package_url: str = "https://indexers.prowlarr.com/master/11/package.zip", schema_version: int = 11, session: Any = requests):
        self.repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[3]
        self.tracked_root = self.repo_root / "indexer-definitions"
        self.official_dir = self.tracked_root / "official"
        self.custom_dir = self.tracked_root / "custom"
        self.manifest_path = self.tracked_root / "manifest.json"
        self.runtime_root = self.repo_root / "data" / "indexer-definitions"
        self.staging_dir = self.runtime_root / "staging"
        self.backups_dir = self.runtime_root / "backups"
        self.package_url = package_url
        self.schema_version = int(schema_version)
        self.session = session

    def load_manifest(self) -> dict[str, Any]:
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    @staticmethod
    def _yaml_files(path: Path) -> list[Path]:
        return sorted([*path.rglob("*.yml"), *path.rglob("*.yaml")]) if path.is_dir() else []

    def _load_source(self, path: Path, origin: str) -> tuple[dict[str, CardigannDefinition], list[dict[str, str]]]:
        output: dict[str, CardigannDefinition] = {}
        errors: list[dict[str, str]] = []
        for file_path in self._yaml_files(path):
            try:
                definition = CardigannDefinition.from_yaml(file_path.read_text(encoding="utf-8"), origin=origin)
                if definition.id in output:
                    raise ValueError(f"duplicate definition id {definition.id}")
                output[definition.id] = definition
            except Exception as exc:
                errors.append({"file": str(file_path.relative_to(path)), "origin": origin, "error": str(exc)})
        return output, errors

    def list_active_definitions(self) -> list[CardigannDefinition]:
        official, official_errors = self._load_source(self.official_dir, "official")
        custom, custom_errors = self._load_source(self.custom_dir, "custom")
        official.update(custom)
        for index, error in enumerate(official_errors + custom_errors):
            ident = f"__parse_error_{index}"
            official[ident] = CardigannDefinition(ident, error["file"], "invalid", [], [], {}, {}, {}, {}, {}, [], {}, [], origin=error["origin"], parse_error=error["error"])
        return sorted(official.values(), key=lambda item: (item.name.casefold(), item.id))

    def load_definition(self, definition_id: str) -> CardigannDefinition | None:
        return next((item for item in self.list_active_definitions() if item.id == definition_id), None)

    @staticmethod
    def _safe_extract(payload: bytes, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        resolved = destination.resolve()
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for member in archive.infolist():
                target = (destination / member.filename).resolve()
                if target != resolved and resolved not in target.parents:
                    raise ValueError(f"unsafe package path: {member.filename}")
            archive.extractall(destination)

    def stage_upstream_package(self, package_bytes: bytes | None = None, *, revision: str = "") -> dict[str, Any]:
        if package_bytes is None:
            response = self.session.get(self.package_url, timeout=60)
            response.raise_for_status()
            package_bytes = bytes(response.content)
            revision = revision or str(response.headers.get("ETag") or response.headers.get("Last-Modified") or "")
        digest = hashlib.sha256(package_bytes).hexdigest()
        temp_root = Path(tempfile.mkdtemp(prefix="stage-", dir=str(self.runtime_root.mkdir(parents=True, exist_ok=True) or self.runtime_root)))
        try:
            extracted = temp_root / "definitions"
            self._safe_extract(package_bytes, extracted)
            candidates = self._yaml_files(extracted)
            if not candidates:
                raise ValueError("definition package contains no YAML files")
            if self.staging_dir.exists():
                shutil.rmtree(self.staging_dir)
            self.staging_dir.mkdir(parents=True)
            official = self.staging_dir / "official"
            official.mkdir()
            for source in candidates:
                shutil.copy2(source, official / source.name)
            metadata = {"schema_version": self.schema_version, "revision": revision, "package_sha256": digest, "staged_at": time.time()}
            (self.staging_dir / "staging.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            return metadata
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def validate_staging(self) -> dict[str, Any]:
        official = self.staging_dir / "official"
        definitions, errors = self._load_source(official, "official")
        metadata_path = self.staging_dir / "staging.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
        if int(metadata.get("schema_version") or 0) != self.schema_version:
            errors.append({"file": "staging.json", "origin": "staging", "error": "schema version mismatch"})
        result = {**metadata, "valid": not errors and bool(definitions), "definition_count": len(definitions), "errors": errors}
        (self.staging_dir / "validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    def _backup_current(self) -> Path:
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        backup = self.backups_dir / time.strftime("%Y%m%d-%H%M%S")
        suffix = 1
        while backup.exists():
            backup = self.backups_dir / (time.strftime("%Y%m%d-%H%M%S") + f"-{suffix}")
            suffix += 1
        backup.mkdir()
        if self.official_dir.exists():
            shutil.copytree(self.official_dir, backup / "official")
        if self.manifest_path.exists():
            shutil.copy2(self.manifest_path, backup / "manifest.json")
        backups = self.list_backups()
        for stale in backups[5:]:
            shutil.rmtree(stale["path"], ignore_errors=True)
        return backup

    def activate_staging(self) -> dict[str, Any]:
        validation = self.validate_staging()
        if not validation["valid"]:
            raise ValueError("staged definitions are not valid")
        backup = self._backup_current()
        incoming = self.staging_dir / "official"
        replacement = self.tracked_root / ".official-replacement"
        if replacement.exists():
            shutil.rmtree(replacement)
        shutil.copytree(incoming, replacement)
        old = self.tracked_root / ".official-old"
        if old.exists():
            shutil.rmtree(old)
        if self.official_dir.exists():
            os.replace(self.official_dir, old)
        os.replace(replacement, self.official_dir)
        shutil.rmtree(old, ignore_errors=True)
        manifest = self.load_manifest()
        manifest.update({"schema_version": self.schema_version, "active_revision": validation.get("revision", ""), "package_sha256": validation.get("package_sha256", ""), "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        temp_manifest = self.manifest_path.with_suffix(".json.tmp")
        temp_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        os.replace(temp_manifest, self.manifest_path)
        return {"activated": True, "backup": backup.name, "manifest": manifest}

    def list_backups(self) -> list[dict[str, Any]]:
        if not self.backups_dir.is_dir():
            return []
        return [{"name": path.name, "path": path, "created_at": path.stat().st_mtime} for path in sorted((item for item in self.backups_dir.iterdir() if item.is_dir()), key=lambda item: item.stat().st_mtime, reverse=True)]

    def rollback_last_activation(self) -> dict[str, Any]:
        backups = self.list_backups()
        if not backups:
            raise ValueError("no definition backup is available")
        backup = backups[0]["path"]
        source_official = backup / "official"
        if self.official_dir.exists():
            shutil.rmtree(self.official_dir)
        shutil.copytree(source_official, self.official_dir)
        shutil.copy2(backup / "manifest.json", self.manifest_path)
        return {"rolled_back": True, "backup": backup.name, "manifest": self.load_manifest()}

    def discard_staging(self) -> None:
        shutil.rmtree(self.staging_dir, ignore_errors=True)


def default_definition_store() -> DefinitionStore:
    return DefinitionStore()
