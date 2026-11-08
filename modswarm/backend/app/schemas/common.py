"""Shared type aliases for the GraphDev schema layer."""

from typing import Literal

EdgeType = Literal["calls", "http_calls", "renders"]

DiffType = Literal["added", "removed", "modified", "moved"]
