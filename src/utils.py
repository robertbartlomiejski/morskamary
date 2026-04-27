"""Shared utility helpers."""

from __future__ import annotations

import re
from typing import Optional


def slugify(text: str, max_length: Optional[int] = 60) -> str:
    """
    Convert text to a filesystem- and identifier-safe slug.

    Args:
        text: Raw input string to normalize.
        max_length: Optional maximum length for the slug; set to ``None`` to
            disable truncation.

    Returns:
        Normalized lowercase slug using underscores as separators.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    if max_length is not None:
        slug = slug[:max_length]
    return slug
