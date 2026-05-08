from __future__ import annotations

import time


class RateLimiter:
    """シンプルなレートリミッター。

    前回呼び出しからmin_interval秒経過するまで待機する。
    """

    def __init__(self, min_interval: float = 1.0) -> None:
        self._min_interval = min_interval
        self._last_call: float = 0.0

    def wait(self) -> None:
        """前回呼び出しからmin_interval秒経過するまで待機する。"""
        now = time.monotonic()
        elapsed = now - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call = time.monotonic()
