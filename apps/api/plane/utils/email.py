# SPDX-FileCopyrightText: 2023-present Plane Software, Inc.
# SPDX-License-Identifier: LicenseRef-Plane-Commercial
#
# Licensed under the Plane Commercial License (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# https://plane.so/legals/eula
#
# DO NOT remove or modify this notice.
# NOTICE: Proprietary and confidential. Unauthorized use or distribution is prohibited.

# Python imports
import re

# Django imports
from django.conf import settings
from django.utils.html import strip_tags


def generate_plain_text_from_html(html_content):
    """
    Generate clean plain text from HTML email template.
    Removes all HTML tags, CSS styles, and excessive whitespace.

    Args:
        html_content (str): The HTML content to convert to plain text

    Returns:
        str: Clean plain text without HTML tags, styles, or excessive whitespace
    """
    # Remove style tags and their content
    html_content = re.sub(r"<style[^>]*>.*?</style>", "", html_content, flags=re.DOTALL | re.IGNORECASE)

    # Strip HTML tags
    text_content = strip_tags(html_content)

    # Remove excessive empty lines
    text_content = re.sub(r"\n\s*\n\s*\n+", "\n\n", text_content)

    # Ensure there's a leading and trailing whitespace
    text_content = "\n\n" + text_content.lstrip().rstrip() + "\n\n"

    return text_content


def truncate_email_subject(subject, max_bytes=None):
    """Truncate a subject line by UTF-8 byte length without splitting a code point.

    The ellipsis counts towards the limit and the full, untruncated title stays in
    the message body. RFC 5322 limits a header to 998 bytes; the default is
    deliberately smaller so subject lines render in common mail clients.
    """

    limit = max_bytes if max_bytes is not None else getattr(settings, "EMAIL_SUBJECT_MAX_BYTES", 150)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 150
    limit = max(3, min(limit, 998))

    text = re.sub(r"[\r\n\t]+", " ", str(subject or "")).strip()
    if len(text.encode("utf-8")) <= limit:
        return text

    ellipsis = "…"
    budget = limit - len(ellipsis.encode("utf-8"))
    kept = []
    used = 0
    for character in text:
        size = len(character.encode("utf-8"))
        if used + size > budget:
            break
        kept.append(character)
        used += size
    return "".join(kept).rstrip() + ellipsis
