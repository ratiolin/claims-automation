#!/usr/bin/env python3
"""Write one mined candidate pattern into the Dify candidate knowledge base.

Defaults are for the current claims-automation project. The script skips creating
a duplicate document when the target name already exists.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any


DEFAULT_CANDIDATE_DATASET_ID = "84595bdf-aa20-4cd8-9a56-0fead9284e1a"


def request_json(method: str, url: str, *, body: dict[str, Any] | None = None, headers: dict[str, str], timeout: int = 240):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"error": raw}
        return exc.code, parsed


def list_documents(base: str, dataset_id: str, headers: dict[str, str]):
    status, payload = request_json("GET", f"{base}/v1/datasets/{dataset_id}/documents?limit=100", headers=headers)
    if status >= 400:
        raise RuntimeError(f"list documents failed: HTTP {status} {payload}")
    return payload.get("data") or []


def get_metadata_map(base: str, dataset_id: str, headers: dict[str, str]):
    status, payload = request_json("GET", f"{base}/v1/datasets/{dataset_id}/metadata", headers=headers)
    if status >= 400:
        raise RuntimeError(f"get metadata failed: HTTP {status} {payload}")
    return {item["name"]: item for item in payload.get("doc_metadata") or []}


def create_document(base: str, dataset_id: str, headers: dict[str, str], *, name: str, text: str):
    body = {
        "name": name,
        "text": text,
        "indexing_technique": "high_quality",
        "doc_form": "text_model",
        "doc_language": "Chinese",
    }
    status, payload = request_json("POST", f"{base}/v1/datasets/{dataset_id}/document/create-by-text", body=body, headers=headers)
    if status >= 400:
        raise RuntimeError(f"create document failed: HTTP {status} {payload}")
    return payload["document"]


def update_metadata(base: str, dataset_id: str, headers: dict[str, str], document_id: str, metadata_map: dict[str, dict[str, Any]], pattern: dict[str, Any]):
    def entry(name: str, value: Any):
        meta = metadata_map.get(name)
        if not meta:
            return None
        return {"id": meta["id"], "name": name, "value": value}

    metadata_list = [
        entry("priority", int(pattern.get("priority") or 15)),
        entry("severity", pattern.get("severity") or "medium"),
        entry("category", pattern.get("category") or "自动挖掘"),
        entry("status", pattern.get("status") or "pending_review"),
        entry("occurrence_count", int(pattern.get("occurrence_count") or len(pattern.get("sample_claim_ids") or []) or 1)),
    ]
    metadata_list = [item for item in metadata_list if item]
    body = {"operation_data": [{"document_id": document_id, "partial_update": True, "metadata_list": metadata_list}]}
    status, payload = request_json("POST", f"{base}/v1/datasets/{dataset_id}/documents/metadata", body=body, headers=headers, timeout=300)
    if status >= 400:
        raise RuntimeError(f"update metadata failed: HTTP {status} {payload}")
    return payload


def pattern_to_text(pattern: dict[str, Any]) -> str:
    sample_ids = ", ".join(pattern.get("sample_claim_ids") or [])
    return "\n".join(
        [
            f"# {pattern.get('title') or '候选错误模式'}",
            "",
            f"类别：{pattern.get('category') or '自动挖掘'}",
            f"优先级：{pattern.get('priority') or 15}",
            f"状态：{pattern.get('status') or 'pending_review'}",
            f"出现次数：{pattern.get('occurrence_count') or len(pattern.get('sample_claim_ids') or []) or 1}",
            "",
            f"问题描述：{pattern.get('description') or pattern.get('evidence_summary') or ''}",
            "",
            f"缓解建议：{pattern.get('mitigation') or pattern.get('suggestion') or '人工确认后入正式错误模式库'}",
            "",
            f"样本 claim_id：{sample_ids}",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dify-base", default=os.getenv("DIFY_BASE", "https://dify.metratio.com"))
    parser.add_argument("--dataset-key", default=os.getenv("DIFY_DATASET_API_KEY", ""))
    parser.add_argument("--candidate-dataset-id", default=os.getenv("DIFY_CANDIDATE_DATASET_ID", DEFAULT_CANDIDATE_DATASET_ID))
    parser.add_argument("--pattern-json", required=True, help="JSON object or JSON array; first item is written")
    parser.add_argument("--name", default="")
    args = parser.parse_args()
    if not args.dataset_key:
        raise SystemExit("DIFY_DATASET_API_KEY is required")

    parsed = json.loads(args.pattern_json)
    pattern = parsed[0] if isinstance(parsed, list) else parsed
    title = str(pattern.get("title") or "候选错误模式").strip()
    safe_title = title.replace("/", "-").replace("\\", "-").replace(":", "-")[:80]
    name = args.name or f"ERR-CANDIDATE-{int(time.time())}-{safe_title}.md"

    headers = {"Authorization": f"Bearer {args.dataset_key}", "Content-Type": "application/json"}
    docs = list_documents(args.dify_base, args.candidate_dataset_id, headers)
    for doc in docs:
        if doc.get("name") == name:
            print(json.dumps({"result": "skipped_existing", "document_id": doc.get("id"), "name": name}, ensure_ascii=False))
            return 0

    document = create_document(args.dify_base, args.candidate_dataset_id, headers, name=name, text=pattern_to_text(pattern))
    metadata_map = get_metadata_map(args.dify_base, args.candidate_dataset_id, headers)
    update_metadata(args.dify_base, args.candidate_dataset_id, headers, document["id"], metadata_map, pattern)
    print(json.dumps({"result": "created", "document_id": document["id"], "name": name}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
