# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Background processing for CSV, Jira and GitHub import jobs."""

import csv
import io
import json
import traceback
from typing import Any, Dict, List

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from plane.app.serializers.issue import IssueCreateSerializer
from plane.db.models import CycleIssue, Importer, Issue, Label, ModuleIssue, State, User, WorkspaceMember
from plane.license.utils.encryption import decrypt_data


def _decrypt_config_value(config: Dict[str, Any], key: str) -> str:
    value = config.get(key, "")
    if not value:
        return ""
    try:
        return decrypt_data(value)
    except Exception:
        return ""


def _normalize_header(header: str) -> str:
    return header.strip().lower().replace("-", "_").replace(" ", "_")


def _parse_csv_rows(content: str) -> List[Dict[str, str]]:
    reader = csv.DictReader(io.StringIO(content))
    rows: List[Dict[str, str]] = []
    for raw in reader:
        normalized = {_normalize_header(key or ""): (value or "").strip() for key, value in raw.items()}
        if normalized.get("title"):
            rows.append(normalized)
    return rows


def _parse_jira_rows(issues: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for issue in issues:
        fields = issue.get("fields", {})
        description = fields.get("description")
        if isinstance(description, dict):
            description = json.dumps(description)
        assignee = fields.get("assignee") or {}
        rows.append(
            {
                "title": fields.get("summary") or "",
                "description": description or "",
                "state": (fields.get("status") or {}).get("name", ""),
                "priority": (fields.get("priority") or {}).get("name", ""),
                "assignee_email": assignee.get("emailAddress", ""),
                "label_names": ",".join(fields.get("labels") or []),
                "external_id": issue.get("key", ""),
            }
        )
    return rows


def _parse_github_rows(issues: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for issue in issues:
        rows.append(
            {
                "title": issue.get("title") or "",
                "description": issue.get("body") or "",
                "state": issue.get("state") or "",
                "assignee_email": (issue.get("assignee") or {}).get("login", ""),
                "label_names": ",".join(label.get("name", "") for label in issue.get("labels") or []),
                "external_id": str(issue.get("number", "")),
                "url": issue.get("html_url", ""),
            }
        )
    return rows


def _resolve_state(project_id, value: str):
    if not value:
        return None
    return State.objects.filter(project_id=project_id, name__iexact=value.strip()).first()


def _resolve_labels(project_id, value: str):
    names = [name.strip() for name in value.split(",") if name.strip()]
    if not names:
        return []
    return list(Label.objects.filter(project_id=project_id, name__in=names).distinct())


def _resolve_assignee(importer: Importer, value: str):
    if not value:
        return None
    user = User.objects.filter(email__iexact=value.strip()).first()
    if not user:
        return None
    if not WorkspaceMember.objects.filter(workspace_id=importer.workspace_id, member=user, is_active=True).exists():
        return None
    return user


def _link_related_objects(importer: Importer, issue: Issue, row: Dict[str, str]) -> None:
    cycle_name = row.get("cycle_name", "").strip()
    if cycle_name:
        from plane.db.models import Cycle

        cycle = Cycle.objects.filter(project_id=importer.project_id, name__iexact=cycle_name).first()
        if cycle:
            CycleIssue.objects.get_or_create(
                issue=issue,
                cycle=cycle,
                project_id=importer.project_id,
                workspace_id=importer.workspace_id,
                defaults={"created_by_id": importer.initiated_by_id},
            )
    module_name = row.get("module_name", "").strip()
    if module_name:
        from plane.db.models import Module

        module = Module.objects.filter(project_id=importer.project_id, name__iexact=module_name).first()
        if module:
            ModuleIssue.objects.get_or_create(
                issue=issue,
                module=module,
                project_id=importer.project_id,
                workspace_id=importer.workspace_id,
                defaults={"created_by_id": importer.initiated_by_id},
            )


def _update_job(importer_id, **fields) -> None:
    Importer.objects.filter(pk=importer_id).update(**fields)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=60, max_retries=2)
def process_import_job(self, importer_id: str) -> None:
    """Create real work items for a persisted import job."""

    importer = Importer.objects.select_related("project", "workspace").get(pk=importer_id)
    if importer.status in ("completed", "processing"):
        return
    _update_job(
        importer_id,
        status="processing",
        started_at=timezone.now(),
        progress=5,
    )
    config = importer.config or {}
    error_log: List[str] = []
    created_count = 0

    try:
        if importer.service == "csv":
            rows = _parse_csv_rows(_decrypt_config_value(config, "csv_content"))
        elif importer.service == "jira":
            from plane.utils.gmc_integrations import fetch_jira_issues

            rows = _parse_jira_rows(
                fetch_jira_issues(
                    _decrypt_config_value(config, "site_url"),
                    _decrypt_config_value(config, "email"),
                    _decrypt_config_value(config, "api_token"),
                    _decrypt_config_value(config, "project_key"),
                )
            )
        elif importer.service == "github":
            from plane.utils.gmc_integrations import fetch_github_issues

            owner = _decrypt_config_value(config, "owner")
            repo = _decrypt_config_value(config, "repo")
            rows = _parse_github_rows(
                fetch_github_issues(
                    _decrypt_config_value(config, "token"),
                    owner,
                    repo,
                    bool(config.get("include_issues", True)),
                    bool(config.get("include_prs", True)),
                )
            )
        else:
            raise ValueError("Unsupported import service")

        total = len(rows)
        _update_job(importer_id, total_count=total, metadata={**(importer.metadata or {}), "source_rows": total})

        project = importer.project
        for index, row in enumerate(rows, start=1):
            try:
                title = str(row.get("title", "")).strip()
                if not title:
                    raise ValueError("Title is required")
                assignee = _resolve_assignee(importer, row.get("assignee_email", ""))
                payload: Dict[str, Any] = {
                    "name": title[:255],
                    "description_html": f"<p>{row.get('description', '')}</p>" if row.get("description") else "",
                    "external_source": "import",
                    "external_id": str(row.get("external_id", f"{importer.service}-{index}")),
                }
                state = _resolve_state(project.id, row.get("state", ""))
                if state:
                    payload["state_id"] = str(state.id)
                priority = str(row.get("priority", "")).strip().lower()
                if priority in ("urgent", "high", "medium", "low"):
                    payload["priority"] = priority
                labels = _resolve_labels(project.id, row.get("label_names", ""))
                if labels:
                    payload["label_ids"] = [str(label.id) for label in labels]
                if assignee:
                    payload["assignee_ids"] = [str(assignee.id)]

                with transaction.atomic():
                    serializer = IssueCreateSerializer(
                        data=payload,
                        context={
                            "project_id": project.id,
                            "workspace_id": importer.workspace_id,
                            "default_assignee_id": project.default_assignee_id,
                        },
                    )
                    serializer.is_valid(raise_exception=True)
                    issue = serializer.save()
                    _link_related_objects(importer, issue, row)
                created_count += 1
            except Exception:
                error_log.append(f"Row {index}: {traceback.format_exc(limit=2).splitlines()[-1]}")
            _update_job(
                importer_id,
                created_count=created_count,
                error_count=len(error_log),
                error_log=error_log[-200:],
                progress=min(99, max(5, round(index * 100 / max(total, 1)))),
            )

        failed = bool(error_log)
        _update_job(
            importer_id,
            status="failed" if failed else "completed",
            progress=100,
            created_count=created_count,
            error_count=len(error_log),
            error_log=error_log[-200:],
            finished_at=timezone.now(),
        )
    except Exception as exc:
        _update_job(
            importer_id,
            status="failed",
            progress=100,
            error_count=1,
            error_log=[f"Import failed: {type(exc).__name__}"],
            finished_at=timezone.now(),
        )
        raise self.retry(exc=exc) if self.request.retries < self.max_retries else None
