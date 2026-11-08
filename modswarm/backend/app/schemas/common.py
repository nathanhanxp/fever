"""Shared type aliases for the GraphDev schema layer."""

from typing import Literal

EdgeType = str

DiffType = Literal["added", "removed", "modified", "moved"]
