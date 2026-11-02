"""uat_kit_wx: the real-terminal test kit vendored from WPTK/wxbrief commit e01891b (tui-test 0.1.1, async, wrapped in a
blocking API). Driven by the eyewall adapter in ``ew_driver.py`` and ``tests/realinput_wx/app.py``."""

from .terminal import Screen, Terminal, unavailable_reason

__all__ = ["Screen", "Terminal", "unavailable_reason"]
