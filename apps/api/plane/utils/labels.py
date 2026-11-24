# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Shared label validation and merge helpers for PLN-002.

Labels are workspace scoped. Both the web API serializers and the v1 API serializers
call :func:`validate_label_attrs` so the two surfaces return the same machine codes.
"""

import re

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from plane.db.models import IssueLabel, Label, Project, Workspace

HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
MAX_LABEL_DEPTH = 3
MAX_LABELS_PER_ISSUE = 10


def label_error(code, message, **details):
    """DRF error body with the stable machine code expected by the UI."""
    error = {"code": code, "message": message}
    if details:
        error["details"] = details
    return serializers.ValidationError({"error": error})


def label_issue_count(label):
    return IssueLabel.objects.filter(label=label, deleted_at__isnull=True).count()


def validate_label_limit(label_ids, *, field_name="label_ids"):
    """Both API surfaces enforce the same per-work-item label ceiling."""
    ids = label_ids or []
    if len(ids) > MAX_LABELS_PER_ISSUE:
        raise serializers.ValidationError(
            {field_name: f"At most {MAX_LABELS_PER_ISSUE} labels can be added to a work item."}
        )
    return ids


def _workspace_id(attrs, instance, workspace_id, project_id):
    if workspace_id:
        return workspace_id
    if instance is not None:
        return instance.workspace_id
    parent = attrs.get("parent")
    if parent is not None and getattr(parent, "workspace_id", None):
        return parent.workspace_id
    if project_id:
        return Project.objects.filter(pk=project_id).values_list("workspace_id", flat=True).first()
    return None


def validate_label_attrs(attrs, *, instance=None, workspace_id=None, project_id=None):
    """Validate name, colour and hierarchy; return the normalised attrs dict."""
    workspace_id = _workspace_id(attrs, instance, workspace_id, project_id)

    if "name" in attrs:
        name = str(attrs.get("name") or "").strip()
        if not name:
            raise label_error("invalid_label_name", "Label name is required.")
        duplicates = Label.objects.filter(
            workspace_id=workspace_id,
            name__iexact=name,
            deleted_at__isnull=True,
        )
        if instance is not None:
            duplicates = duplicates.exclude(pk=instance.pk)
        if duplicates.exists():
            raise label_error(
                "duplicate_label_name",
                "A label with this name already exists in the workspace.",
                workspace_id=str(workspace_id) if workspace_id else None,
            )
        attrs["name"] = name

    if "color" in attrs:
        color = str(attrs.get("color") or "").strip()
        if color and not HEX_COLOR.fullmatch(color):
            raise label_error("invalid_label_color", "Colour must be a hex value such as #FF5733 or be empty.")
        attrs["color"] = color

    parent = attrs.get("parent", instance.parent if instance is not None else None)
    if parent is not None:
        if workspace_id and str(parent.workspace_id) != str(workspace_id):
            raise label_error("invalid_label_parent", "The parent label must belong to the same workspace.")
        if instance is not None and str(parent.pk) == str(instance.pk):
            raise label_error("label_cycle", "A label cannot be its own parent.")

        seen = set()
        cursor = parent
        depth = 0
        while cursor is not None:
            if str(cursor.pk) in seen or (instance is not None and str(cursor.pk) == str(instance.pk)):
                raise label_error("label_cycle", "This parent would create a label hierarchy cycle.")
            seen.add(str(cursor.pk))
            depth += 1
            if depth >= MAX_LABEL_DEPTH:
                raise label_error(
                    "label_depth_exceeded",
                    f"Label hierarchy cannot be deeper than {MAX_LABEL_DEPTH} levels.",
                    max_depth=MAX_LABEL_DEPTH,
                )
            cursor = cursor.parent

    return attrs


def build_merge_preview(target, sources):
    """Read-only description of a merge, used by both the API and the CLI."""
    source_ids = [source.id for source in sources]
    issue_labels = IssueLabel.objects.filter(label_id__in=source_ids, deleted_at__isnull=True)
    issue_ids = sorted({str(value) for value in issue_labels.values_list("issue_id", flat=True)})
    return {
        "target": {
            "id": str(target.id),
            "name": target.name,
            "color": target.color,
            "issue_count": label_issue_count(target),
        },
        "sources": [
            {
                "id": str(source.id),
                "name": source.name,
                "issue_count": label_issue_count(source),
            }
            for source in sources
        ],
        "affected_issue_count": len(issue_ids),
        "affected_issue_ids": issue_ids,
    }


def merge_labels(*, workspace_slug, target_id, source_ids, actor=None, dry_run=False):
    """Merge duplicate labels into the target. Dry-run by default at the call site."""
    workspace = Workspace.objects.filter(slug=workspace_slug).first()
    if workspace is None:
        raise ValueError("Workspace not found.")

    target = Label.objects.filter(workspace=workspace, pk=target_id, deleted_at__isnull=True).first()
    if target is None:
        raise ValueError("Target label not found.")

    source_ids = {str(value) for value in source_ids if str(value) != str(target_id)}
    if not source_ids:
        raise ValueError("At least one different source label is required.")

    sources = list(Label.objects.filter(workspace=workspace, pk__in=source_ids, deleted_at__isnull=True))
    active_ids = {str(label.id) for label in sources}
    skipped = sorted(source_ids - active_ids)
    if not sources:
        return {"merged": False, "skipped": skipped, "reason": "No active source labels remain."}

    preview = build_merge_preview(target, sources)
    preview["skipped"] = skipped
    if dry_run:
        preview["merged"] = False
        return preview

    issue_ids = preview["affected_issue_ids"]
    with transaction.atomic():
        for source in sources:
            duplicate_issue_ids = IssueLabel.objects.filter(
                label=target,
                issue_id__in=issue_ids,
            ).values_list("issue_id", flat=True)
            IssueLabel.objects.filter(label=source, issue_id__in=duplicate_issue_ids).delete()
            IssueLabel.objects.filter(label=source).update(label=target, updated_by=actor)
            source.deleted_at = timezone.now()
            source.updated_by = actor
            source.save(
                update_fields=["deleted_at", "updated_at", "updated_by"],
                disable_auto_set_user=True,
            )

    preview["merged"] = True
    preview["target"]["issue_count"] = label_issue_count(target)
    return preview
