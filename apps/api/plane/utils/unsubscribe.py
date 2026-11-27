# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Signed, one-click unsubscribe links for non-security email.

Security mail (password reset, magic links, verification) never calls these
helpers, so an unsubscribe can only affect the event type encoded in the token.
"""

# Python imports
from datetime import timedelta
from urllib.parse import quote

# Django imports
from django.conf import settings
from django.core import signing
from django.core.signing import BadSignature
from django.db.models import Q
from django.utils import timezone

# Module imports
from plane.db.models import UnsubscribeToken, User, UserNotificationPreference

UNSUBSCRIBE_SALT = "plane-email-unsubscribe"

ISSUE_EMAIL_FIELDS = (
    "property_change",
    "assignment",
    "state_change",
    "comment",
    "mention",
    "issue_completed",
)

EVENT_PREFERENCE_FIELDS = {
    "issue_updates": None,  # all issue event types
    "property_change": "property_change",
    "assignment": "assignment",
    "state": "state_change",
    "state_change": "state_change",
    "comment": "comment",
    "mention": "mention",
    "issue_completed": "issue_completed",
    "project_invitation": "project_invitation",
}


def _max_age_seconds():
    days = getattr(settings, "EMAIL_UNSUBSCRIBE_MAX_AGE_DAYS", 90)
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 90
    return max(1, min(days, 365)) * 24 * 60 * 60


def create_unsubscribe_token(user, email, event_type, workspace=None, project=None):
    """Persist and return a signed token for one notification category."""

    if event_type not in EVENT_PREFERENCE_FIELDS:
        raise ValueError(f"Unsupported unsubscribe event type: {event_type}")

    normalized_email = str(email or "").strip().lower()
    payload = {
        "user_id": str(getattr(user, "pk", "") or ""),
        "email": normalized_email,
        "event_type": event_type,
        "workspace_id": str(getattr(workspace, "pk", "") or ""),
        "project_id": str(getattr(project, "pk", "") or ""),
    }
    token = signing.dumps(payload, salt=UNSUBSCRIBE_SALT)
    UnsubscribeToken.objects.create(
        token=token,
        user=user,
        email=normalized_email,
        event_type=event_type,
        workspace=workspace,
        project=project,
        expires_at=timezone.now() + timedelta(seconds=_max_age_seconds()),
    )
    return token


def build_unsubscribe_url(user, email, event_type, workspace=None, project=None):
    """Return the public, login-free URL for a signed unsubscribe token."""

    token = create_unsubscribe_token(user, email, event_type, workspace=workspace, project=project)
    base_url = str(getattr(settings, "WEB_URL", "http://localhost") or "http://localhost").rstrip("/")
    return f"{base_url}/api/public/unsubscribe/{quote(token, safe='')}/"


def verify_unsubscribe_token(token, consume=False):
    """Validate signature, expiry and stored state; optionally consume the token."""

    if not token:
        return None
    try:
        payload = signing.loads(token, salt=UNSUBSCRIBE_SALT, max_age=_max_age_seconds())
    except (BadSignature, ValueError, TypeError):
        return None

    record = (
        UnsubscribeToken.objects.filter(token=token, revoked=False, used_at__isnull=True)
        .filter(Q(expires_at__gt=timezone.now()) | Q(expires_at__isnull=True))
        .select_related("user", "workspace", "project")
        .first()
    )
    if record is None:
        return None

    expected = {
        "user_id": str(record.user_id or ""),
        "email": str(record.email).lower(),
        "event_type": record.event_type,
        "workspace_id": str(record.workspace_id or ""),
        "project_id": str(record.project_id or ""),
    }
    if any(str(payload.get(key, "")) != value for key, value in expected.items()):
        return None

    if consume:
        UnsubscribeToken.objects.filter(pk=record.pk, used_at__isnull=True).update(used_at=timezone.now())
        record.used_at = timezone.now()
    return record


def apply_unsubscribe(record):
    """Disable only the event type named by the token, scoped to its workspace/project."""

    user = record.user or User.objects.filter(email__iexact=record.email).first()
    pref_field = EVENT_PREFERENCE_FIELDS.get(record.event_type)
    if pref_field is None:
        values = {field: False for field in ISSUE_EMAIL_FIELDS}
    else:
        values = {pref_field: False}

    if user is None:
        # An invitee without an account is covered by the consumed token below.
        return None
    preference, _ = UserNotificationPreference.objects.update_or_create(
        user=user,
        workspace_id=record.workspace_id,
        project_id=record.project_id,
        defaults=values,
    )
    return preference


def is_email_unsubscribed(email, event_type):
    """Return True when this address has already consumed a token for the event."""

    if not email or event_type not in EVENT_PREFERENCE_FIELDS:
        return False
    return UnsubscribeToken.objects.filter(
        email__iexact=str(email).strip(),
        event_type=event_type,
        used_at__isnull=False,
        revoked=False,
    ).exists()


def email_preference_allows(user, event_type, workspace=None, project=None):
    """Return False only when a scoped preference explicitly opts out."""

    if not getattr(user, "pk", None) or event_type not in EVENT_PREFERENCE_FIELDS:
        return True

    pref_field = EVENT_PREFERENCE_FIELDS[event_type]
    scopes = []
    if project is not None:
        scopes.append({"workspace_id": getattr(project, "workspace_id", None), "project_id": project.pk})
    if workspace is not None:
        scopes.append({"workspace_id": workspace.pk, "project_id": None})
    scopes.append({"workspace_id": None, "project_id": None})

    for scope in scopes:
        preference = UserNotificationPreference.objects.filter(user=user, **scope).first()
        if preference is None:
            continue
        if pref_field is None:
            return any(getattr(preference, field) for field in ISSUE_EMAIL_FIELDS)
        return bool(getattr(preference, pref_field))
    return True
