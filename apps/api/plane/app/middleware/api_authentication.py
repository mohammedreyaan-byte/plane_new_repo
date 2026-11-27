# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.utils import timezone
from django.db.models import Q

# Third party imports
from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed

# Module imports
from plane.api.rate_limit import record_token_auth_failure
from plane.db.models import APIToken
from plane.db.models.api import hash_api_token


class APIKeyAuthentication(authentication.BaseAuthentication):
    """API-key authentication shared with the external API.

    New tokens are looked up by hash; legacy plaintext rows remain supported.
    The token instance is attached to ``request.auth`` for central project
    scoping, and failures are rate limited without revealing a reason.
    """

    www_authenticate_realm = "api"
    media_type = "application/json"
    auth_header_name = "X-Api-Key"

    def get_api_token(self, request):
        return request.headers.get(self.auth_header_name)

    def authenticate_header(self, request):
        # DRF coerces AuthenticationFailed to 403 when no authenticator
        # supplies a challenge header. API-key failures must stay 401.
        return f'{self.auth_header_name} realm="{self.www_authenticate_realm}"'

    def resolve_api_token(self, token):
        api_token = (
            APIToken.objects.select_related("user")
            .filter(
                Q(token_hash=hash_api_token(token)) | Q(token=token),
                Q(Q(expired_at__gt=timezone.now()) | Q(expired_at__isnull=True)),
                is_active=True,
                revoked_at__isnull=True,
                user__is_active=True,
            )
            .first()
        )
        if api_token is None:
            raise AuthenticationFailed("Given API token is not valid")

        api_token.last_used = timezone.now()
        api_token.save(update_fields=["last_used"])
        return api_token

    def validate_api_token(self, token):
        """Backwards-compatible helper returning the token value as a string."""
        api_token = self.resolve_api_token(token)
        return (api_token.user, token)

    def authenticate(self, request):
        token = self.get_api_token(request=request)
        if not token:
            return None

        try:
            api_token = self.resolve_api_token(token)
        except AuthenticationFailed:
            record_token_auth_failure(request, token)
            raise AuthenticationFailed("Given API token is not valid")

        # DRF assigns the authenticator's second return value to
        # ``request.auth`` after this method returns, so return the instance.
        return (api_token.user, api_token)
