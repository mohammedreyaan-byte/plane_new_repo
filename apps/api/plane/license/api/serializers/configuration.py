# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from .base import BaseSerializer
from plane.license.models import InstanceConfiguration
from plane.license.utils.encryption import decrypt_data


class InstanceConfigurationSerializer(BaseSerializer):
    class Meta:
        model = InstanceConfiguration
        fields = "__all__"

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # SMTP passwords are write-only; never return the decrypted value.
        if instance.key == "EMAIL_HOST_PASSWORD":
            data["value"] = ""
        # Decrypt other secrets for the admin configuration screen.
        elif instance.is_encrypted and instance.value is not None:
            data["value"] = decrypt_data(instance.value)

        return data
