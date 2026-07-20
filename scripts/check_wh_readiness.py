#!/usr/bin/env python3
"""倉庫(wh_shareholders)へ大量保有を寄せてよいかを機械判定する CLI。

    .venv/bin/python scripts/check_wh_readiness.py

判定ロジックは src/wh_readiness.py。アプリのサイドバー「🏭 倉庫レディネス判定」
ボタンからも同じ判定を実行できる。
終了コード: 0=🟢寄せてよい / 1=🟡近い / 2=🔴まだ・接続不可。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import wh_readiness  # noqa: E402


def main() -> int:
    r = wh_readiness.evaluate()
    print(wh_readiness.format_text(r))
    if not r.get("available"):
        return 2
    return {"green": 0, "yellow": 1, "red": 2}[r["level"]]


if __name__ == "__main__":
    sys.exit(main())
