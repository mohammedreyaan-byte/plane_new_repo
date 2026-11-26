# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.conf import settings
from django.db import models

# Module imports
from plane.utils.html_processor import strip_tags

from .base import BaseModel


class PageComment(BaseModel):
    """A comment made against a page. Replies use ``parent`` to form a thread."""

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="page_comments")
    project = models.ForeignKey("db.Project", on_delete=models.CASCADE, related_name="page_comments")
    page = models.ForeignKey("db.Page", on_delete=models.CASCADE, related_name="page_comments")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="page_comments",
        null=True,
    )
    comment_html = models.TextField(verbose_name="Comment", blank=True, default="<p></p>")
    comment_stripped = models.TextField(verbose_name="Comment stripped", blank=True)
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="replies",
    )
    edited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Page Comment"
        verbose_name_plural = "Page Comments"
        db_table = "page_comments"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["page", "created_at"], name="pagecomment_page_created_idx"),
        ]

    def __str__(self):
        return f"{self.actor_id} <{self.page_id}>"

    def save(self, *args, **kwargs):
        self.comment_stripped = strip_tags(self.comment_html) if self.comment_html else ""
        super().save(*args, **kwargs)
