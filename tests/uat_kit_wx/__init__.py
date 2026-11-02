"""uat_kit_wx: the real-terminal test kit vendored from WPTK/wxbrief commit e01891b (tui-test 0.1.1, async, wrapped in a
blocking API). Used as a second driver beside the older pywinpty/pyte kit in ``tests/uat_kit``; see ``ew_driver.py``."""

from .terminal import Screen, Terminal, unavailable_reason

__all__ = ["Screen", "Terminal", "unavailable_reason"]
