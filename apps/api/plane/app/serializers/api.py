# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from .base import BaseSerializer
from plane.db.models import APIToken, APIActivityLog
from rest_framework import serializers
from django.utils import timezone


class APITokenSerializer(BaseSerializer):
    class Meta:
        model = APIToken
        exclude = ("token_hash",)
        read_only_fields = [
            "token",
            "token_prefix",
            "capabilities",
            "revoked_at",
            "created_by",
            "expired_at",
            "created_at",
            "updated_at",
            "workspace",
            "user",
            "is_active",
            "last_used",
            "user_type",
            "allowed_rate_limit",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Show the plaintext exactly once, at creation time. Afterwards only
        # the non-secret prefix is available.
        plaintext = getattr(instance, "_plaintext_token", None)
        if plaintext:
            data["token"] = plaintext
        else:
            data["token"] = getattr(instance, "token_prefix", "")
        return data


class APITokenReadSerializer(BaseSerializer):
    is_active = serializers.SerializerMethodField()

    class Meta:
        model = APIToken
        exclude = ("token", "token_hash")

    def get_is_active(self, obj: APIToken) -> bool:
        if obj.expired_at is None:
            return True
        return timezone.now() < obj.expired_at


class APIActivityLogSerializer(BaseSerializer):
    class Meta:
        model = APIActivityLog
        fields = "__all__"
