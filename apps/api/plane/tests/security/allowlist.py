# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Explicit allowlist of routes that are intentionally not project-scoped.

Each entry is a route fragment plus the reason it may be reached without an
active ``ProjectMember`` check. Project-scoped routes must never be added here.
"""

PUBLIC_ROUTES = {
    # Exact project-scoped routes that are public by product design. They must
    # remain explicit so a new unscoped route cannot silently join the list.
    "api/public/workspaces/<str:slug>/projects/<uuid:project_id>/anchor/": (
        "Public deploy-board anchor resolves an opaque share link; access is granted by DeployBoard, not membership."
    ),
    "api/auth/": "Authentication endpoints create sessions; they do not expose project data.",
    "api/spaces/invitations/": "Invitation links are validated by signed token before membership exists.",
    "api/spaces/workspaces/": "Space bootstrap endpoints are gated by the signed invitation flow.",
    "api/provider-webhooks/": "Provider webhooks are authenticated by HMAC signature and scoped to an integration.",
    "api/oauth/": "OAuth callbacks are validated by short-lived signed state and do not read project data.",
    "api/instances/": "Instance configuration is public by product design.",
    "api/health/": "Liveness probe carries no tenant data.",
    "api/docs/": "API schema/documentation endpoint carries no tenant data.",
}
