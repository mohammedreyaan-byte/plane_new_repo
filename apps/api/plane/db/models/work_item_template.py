# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Reusable work item templates."""

from django.db import models

from .workspace import WorkspaceBaseModel


class WorkItemTemplate(WorkspaceBaseModel):
    """A reusable set of work item field defaults.

    A template with a project is project-scoped; a template without one is
    available across the workspace. ``template_data`` only stores IDs and text
    defaults - it is validated and scoped again when an issue is created.
    """

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    template_data = models.JSONField(default=dict, blank=True)
    is_public = models.BooleanField(default=True)

    class Meta:
        db_table = "gmc_work_item_templates"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["workspace", "project"], name="gmc_witemplate_scope_idx")]
