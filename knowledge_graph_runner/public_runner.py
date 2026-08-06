#!/usr/bin/env python3
"""Zero-cost scheduled wrapper for the portable Notion knowledge graph.

Reads canonical Notion content, builds an ephemeral local graph, and writes only a
small execution receipt to the dedicated Notion database. No graph data or page
bodies are uploaded to the public repository.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

import kg_portable as kg

RUN_DB_TITLE = "Ejecuciones del grafo derivado"
ROOT_TITLE = "Classifier"
NOTION_VERSION = os.getenv("NOTION_VERSION", "2026-03-11")


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def title_prop(text: str) -> dict[str, Any]:
    return {"title": [{"type": "text", "text": {"content": text[:2000]}}]}


def rich_prop(text: str) -> dict[str, Any]:
    return {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]}


def select_prop(name: str) -> dict[str, Any]:
    return {"select": {"name": name}}


def number_prop(value: int | float | None) -> dict[str, Any]:
    return {"number": value}


def date_prop(value: str | None) -> dict[str, Any]:
    return {"date": None if value is None else {"start": value}}


def url_prop(value: str | None) -> dict[str, Any]:
    return {"url": value}


def exact_object_id(client: kg.NotionClient, object_type: str, title: str) -> str:
    rows = client.search_all(object_type, 100000)
    matches: list[str] = []
    for row in rows:
        if kg.extract_title(row, "").strip() != title:
            continue
        object_id = kg.normalize_id(str(row.get("id") or row.get("url") or ""))
        if object_id:
            matches.append(object_id)
    matches = sorted(set(matches))
    if len(matches) != 1:
        raise kg.KGError(
            f"Se esperaba exactamente un objeto {object_type!r} llamado {title!r}; encontrados={len(matches)}."
        )
    return matches[0]


def github_run_url() -> str | None:
    server = os.getenv("GITHUB_SERVER_URL")
    repository = os.getenv("GITHUB_REPOSITORY")
    run_id = os.getenv("GITHUB_RUN_ID")
    return f"{server}/{repository}/actions/runs/{run_id}" if server and repository and run_id else None


def create_receipt(
    client: kg.NotionClient,
    data_source_id: str,
    *,
    generation: str,
    status: str,
    started_at: str,
    finished_at: str,
    nodes: int,
    edges: int,
    coverage: float,
    changes: int,
    digest: str,
    detail: str,
) -> None:
    payload = {
        "parent": {"type": "data_source_id", "data_source_id": data_source_id},
        "properties": {
            "Ejecución": title_prop(f"{generation} — {status}"),
            "Generación": rich_prop(generation),
            "Estado": select_prop(status),
            "Modo": select_prop("Automático"),
            "Nodos": number_prop(nodes),
            "Aristas": number_prop(edges),
            "Cobertura": number_prop(coverage),
            "Cambios": number_prop(changes),
            "Hash": rich_prop(digest),
            "Inicio": date_prop(started_at),
            "Fin": date_prop(finished_at),
            "Artefacto": url_prop(github_run_url()),
            "Costo USD": number_prop(0),
            "Detalle": rich_prop(detail),
        },
    }
    client.request("POST", "/pages", payload)


def main() -> int:
    started_at = now()
    token = os.getenv("NOTION_GRAPH_TOKEN") or os.getenv("NOTION_TOKEN")
    if not token:
        print(json.dumps({"status": "BLOCKED", "reason": "NOTION_TOKEN_MISSING", "cost_usd": 0}))
        return 2

    client = kg.NotionClient(token, NOTION_VERSION)
    run_source_id: str | None = None
    try:
        client.get_self()
        root_id = os.getenv("NOTION_ROOT_ID") or exact_object_id(client, "page", ROOT_TITLE)
        run_source_id = os.getenv("NOTION_RUN_DATA_SOURCE_ID") or exact_object_id(
            client, "data_source", RUN_DB_TITLE
        )
        config: dict[str, Any] = {
            "name": "Knowledge Base",
            "root_id": root_id,
            "notion_version": NOTION_VERSION,
            "output_dir": "output/notion",
            "content_mode": os.getenv("KG_CONTENT_MODE", "none"),
            "max_objects": int(os.getenv("KG_MAX_OBJECTS", "100000")),
            "max_block_pages": int(os.getenv("KG_MAX_BLOCK_PAGES", "2000")),
        }
        graph_page_url = os.getenv("NOTION_GRAPH_PAGE_URL")
        if graph_page_url:
            config["graph_page_url"] = graph_page_url

        snapshot = kg.NotionGraphBuilder(client, config).build()
        output = Path("output/notion")
        kg.write_outputs(snapshot, output)
        summary = snapshot.analysis["summary"]
        cycles = [
            item for item in snapshot.analysis.get("predicate_cycles", [])
            if item.get("predicate") in {"Parte de", "Depende de"}
        ]
        warnings = int(snapshot.statistics.get("warnings", 0))
        unreachable = int(summary.get("unreachable_from_root_count", 0))
        if cycles or unreachable:
            status = "BLOCKED"
        elif warnings:
            status = "PARTIAL"
        else:
            status = "PASS"
        coverage = 1.0 if status == "PASS" else 0.0
        finished_at = now()
        detail = (
            f"{summary['semantic_edge_count']} aristas semánticas; "
            f"{summary['weak_component_count']} componentes; "
            f"{summary['navigation_bridge_count']} puentes; "
            f"{summary['navigation_articulation_count']} articulaciones; "
            f"{warnings} advertencias; páginas canónicas sin cambios; costo adicional USD 0."
        )
        create_receipt(
            client,
            run_source_id,
            generation=snapshot.generation,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            nodes=int(summary["node_count"]),
            edges=int(summary["active_raw_edge_count"]),
            coverage=coverage,
            changes=0,
            digest=snapshot.digest,
            detail=detail,
        )
        print(json.dumps({
            "status": status,
            "generation": snapshot.generation,
            "nodes": int(summary["node_count"]),
            "raw_edges": int(summary["active_raw_edge_count"]),
            "semantic_edges": int(summary["semantic_edge_count"]),
            "components": int(summary["weak_component_count"]),
            "bridges": int(summary["navigation_bridge_count"]),
            "articulation_points": int(summary["navigation_articulation_count"]),
            "unreachable": unreachable,
            "warnings": warnings,
            "receipt": "PASS",
            "cost_usd": 0,
        }, ensure_ascii=False, sort_keys=True))
        return 0 if status == "PASS" else 2
    except Exception as exc:
        finished_at = now()
        error_name = type(exc).__name__
        if run_source_id:
            try:
                create_receipt(
                    client,
                    run_source_id,
                    generation=f"KG-PUBLIC-{started_at.replace(':', '').replace('-', '')}",
                    status="BLOCKED",
                    started_at=started_at,
                    finished_at=finished_at,
                    nodes=0,
                    edges=0,
                    coverage=0,
                    changes=0,
                    digest="",
                    detail=(
                        f"Ejecución bloqueada antes del snapshot: {error_name}. "
                        "No se editaron páginas canónicas; revisar permisos/configuración."
                    ),
                )
            except Exception:
                pass
        print(json.dumps({"status": "BLOCKED", "reason": error_name, "cost_usd": 0}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
