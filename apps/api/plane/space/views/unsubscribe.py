# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Public, login-free endpoints for one-click email unsubscribe links."""

# Django imports
from django.http import HttpResponse
from django.utils.html import escape

# Third party imports
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

# Module imports
from plane.utils.unsubscribe import apply_unsubscribe, verify_unsubscribe_token

EVENT_LABELS = {
    "issue_updates": "issue updates",
    "property_change": "property change emails",
    "assignment": "assignment emails",
    "state": "state change emails",
    "state_change": "state change emails",
    "comment": "comment emails",
    "mention": "mention emails",
    "issue_completed": "work item completion emails",
    "project_invitation": "project invitation emails",
}


class UnsubscribeEndpoint(APIView):
    """Verify a signed token and apply the single preference it authorises."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "email_unsubscribe"

    def _unsubscribe(self, token):
        record = verify_unsubscribe_token(token, consume=True)
        if record is None:
            return None
        apply_unsubscribe(record)
        return record

    def get(self, request, token):
        """One-click path used directly from the email client."""

        record = self._unsubscribe(token)
        if record is None:
            return HttpResponse(
                "<!doctype html><html><body><p>This unsubscribe link is invalid or has expired.</p></body></html>",
                status=400,
                content_type="text/html; charset=utf-8",
            )
        label = EVENT_LABELS.get(record.event_type, "these emails")
        return HttpResponse(
            "<!doctype html><html><head><meta charset='utf-8'><title>Unsubscribed</title></head>"
            "<body><p>You have been unsubscribed from "
            f"{escape(label)} for {escape(record.email)}.</p>"
            "<p>Security emails such as password resets are unaffected.</p></body></html>",
            content_type="text/html; charset=utf-8",
        )

    def post(self, request, token):
        record = self._unsubscribe(token)
        if record is None:
            return Response({"error": "Invalid or expired unsubscribe link"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "unsubscribed": True,
                "event_type": record.event_type,
                "email": record.email,
                "workspace_id": str(record.workspace_id) if record.workspace_id else None,
                "project_id": str(record.project_id) if record.project_id else None,
            },
            status=status.HTTP_200_OK,
        )
