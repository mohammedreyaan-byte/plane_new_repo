# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import hashlib
import os

# Django imports
from django.conf import settings
from django.core.cache import cache

# Third party imports
from rest_framework.exceptions import Throttled
from rest_framework.throttling import SimpleRateThrottle


class ApiKeyRateThrottle(SimpleRateThrottle):
    scope = "api_key"
    rate = settings.API_KEY_RATE_LIMIT

    def get_cache_key(self, request, view):
        # Retrieve the API key from the request header
        api_key = request.headers.get("X-Api-Key")
        if not api_key:
            return None  # Allow the request if there's no API key

        # Use the API key as part of the cache key
        return f"{self.scope}:{api_key}"

    def allow_request(self, request, view):
        allowed = super().allow_request(request, view)

        if allowed:
            now = self.timer()
            # Calculate the remaining limit and reset time
            history = self.cache.get(self.key, [])

            # Remove old histories
            while history and history[-1] <= now - self.duration:
                history.pop()

            # Calculate the requests
            num_requests = len(history)

            # Check available requests
            available = self.num_requests - num_requests

            # Unix timestamp for when the rate limit will reset
            reset_time = int(now + self.duration)

            # Add headers
            request.META["X-RateLimit-Remaining"] = max(0, available)
            request.META["X-RateLimit-Reset"] = reset_time

        return allowed


TOKEN_AUTH_FAILURE_LIMIT = int(os.environ.get("TOKEN_AUTH_FAILURE_LIMIT", "20"))
INVITATION_ACCEPT_LIMIT = int(os.environ.get("INVITATION_ACCEPT_LIMIT", "50"))
WEBHOOK_RECEIVER_LIMIT = int(os.environ.get("WEBHOOK_RECEIVER_LIMIT", "100"))
RATE_LIMIT_WINDOW = 60
TOKEN_AUTH_FAILURE_WINDOW = RATE_LIMIT_WINDOW


def _client_ip(request):
    """Best-effort client address for rate limiting; never includes credentials."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _fingerprint(value):
    """Stable, non-reversible cache-key fragment (never stores credentials)."""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _token_fingerprint(token):
    return _fingerprint(token)


def _increment_counter(key, limit, window):
    """Increment a fixed-window counter and return the wait seconds if blocked."""
    count = cache.get(key, 0) + 1
    cache.set(key, count, window)
    if count > limit:
        return window
    return None


def _record_failure_key(key):
    return _increment_counter(key, TOKEN_AUTH_FAILURE_LIMIT, TOKEN_AUTH_FAILURE_WINDOW)


def record_action_attempt(request, action, account=None, *, limit, window=RATE_LIMIT_WINDOW):
    """Count an auth-like attempt per IP and, when available, per account.

    Account identifiers are hashed before being used in cache keys. Raising
    ``Throttled`` keeps the failure response uniform and avoids disclosing
    whether an account exists.
    """
    keys = [f"auth_attempt:{action}:ip:{_client_ip(request)}"]
    if account:
        keys.append(f"auth_attempt:{action}:account:{_fingerprint(account)}")
    waits = [_increment_counter(key, limit, window) for key in keys]
    wait = max(filter(None, waits), default=None)
    if wait is not None:
        raise Throttled(wait=wait)


def record_invitation_accept(request, email):
    """Rate limit invitation acceptance by IP and invited address."""
    record_action_attempt(
        request,
        "invitation_accept",
        account=email,
        limit=INVITATION_ACCEPT_LIMIT,
    )


def record_webhook_receiver(request, workspace_slug, provider):
    """Rate limit unauthenticated provider webhook receivers."""
    record_action_attempt(
        request,
        "webhook_receiver",
        account=f"{workspace_slug}:{provider}",
        limit=WEBHOOK_RECEIVER_LIMIT,
    )


def record_token_auth_failure(request, token):
    """Count failed API-token authentication attempts per IP and token.

    Keys use a token fingerprint instead of the plaintext value. Raising
    ``Throttled`` keeps the response generic (no validity information) while
    protecting against credential stuffing.
    """
    ip_key = f"token_auth_failures:ip:{_client_ip(request)}"
    token_key = f"token_auth_failures:token:{_token_fingerprint(token)}"
    wait = max(filter(None, (_record_failure_key(ip_key), _record_failure_key(token_key))), default=None)
    if wait is not None:
        raise Throttled(wait=wait)
