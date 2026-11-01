# Vendored unchanged from WPTK/wxbrief PR #227 (branch uat-kit), commit 321a5a3372058e0ee7e014b3e2a3372cd652c4d4, tests/uat_kit/__init__.py
"""uat_kit: a self-contained, vendorable real-terminal test kit (pywinpty/ConPTY or stdlib pty, plus pyte)."""

from .terminal import Screen, Terminal, unavailable_reason

__all__ = ["Screen", "Terminal", "unavailable_reason"]
