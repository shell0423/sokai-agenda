"""アプリのボタンから実行するジョブ群。

- fast_regen: キャッシュからトリガー比較→差分→実戦リスト→HTMLを再生成(数秒〜数分)
- start_full_update / full_update_status: EDINET再スキャン(長時間・バックグラウンド)
- check_coverage: EDINETメタデータのみの充足チェック(日次件数)
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from src.analysis_diff import OUTPUT_DIR, PROJECT_ROOT, build_all

LOG_DIR = OUTPUT_DIR / "logs"
FULL_UPDATE_LOG = LOG_DIR / "full_update.log"
FULL_UPDATE_PID = LOG_DIR / "full_update.pid"
PYTHON = str(PROJECT_ROOT / ".venv" / "bin" / "python")


# ------------------------------------------------------------------
# ① 高速再生成(キャッシュから)
# ------------------------------------------------------------------

def fast_regen(progress=None) -> dict:
    """トリガー比較CSV(2年ペア×2)→差分/実戦リスト→ダッシュボードHTML。

    Args:
        progress: callable(str) 進捗コールバック(Streamlitのst.write等)。

    Returns:
        analysis_diff.build_all() の結果dict。
    """
    def log(msg: str) -> None:
        if progress:
            progress(msg)

    pairs = [("2024,2025", "trigger_comparison_2425.csv"),
             ("2025,2026", "trigger_comparison_2526.csv")]
    for years, out_name in pairs:
        log(f"トリガー比較 {years} → {out_name}")
        r = subprocess.run(
            [PYTHON, "compare_triggers.py", "--years", years,
             "--csv", "-o", f"output/{out_name}"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300,
        )
        if r.returncode != 0:
            # compare_triggersはエラー理由をstdoutに出すことがある
            detail = (r.stderr or "").strip() or (r.stdout or "").strip()
            raise RuntimeError(
                f"compare_triggers {years} 失敗:\n{detail[-800:]}")

    log("差分＋実戦ウォッチリスト構築")
    result = build_all()

    log("ダッシュボードHTML生成")
    from src.dashboard_gen import generate_dashboard
    generate_dashboard()

    c = result["counts"]
    log(f"完了: 継続{c['cont']}/新規{c['new']}/卒業{c['grad']} "
        f"実戦{c['kept']}社(A{c['A']}/B{c['B']}/C{c['C']})")
    return result


# ------------------------------------------------------------------
# ② フル更新(EDINET再スキャン・バックグラウンド)
# ------------------------------------------------------------------

# 直近に起動したPopenハンドル(同一プロセス内)。poll()でゾンビを回収するために保持する。
_PROC: subprocess.Popen | None = None


def _pid_is_our_script(pid: int) -> bool:
    """PIDが生きていて、かつ我々のfull_update.shである(=PID再利用でない)ことを確認。

    ゾンビ(stat Z)は「終了済み」として扱う。
    """
    try:
        r = subprocess.run(
            ["ps", "-p", str(pid), "-o", "stat=,command="],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return False
    line = (r.stdout or "").strip()
    if not line:
        return False  # プロセス不在
    stat, _, command = line.partition(" ")
    if stat.startswith("Z"):
        return False  # ゾンビ=実質終了(親が未回収なだけ)
    return "full_update.sh" in command or "bash" in command


def start_full_update() -> dict:
    """scripts/full_update.sh をバックグラウンド起動。既に実行中なら起動しない。"""
    global _PROC
    status = full_update_status()
    if status["running"]:
        return status
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    FULL_UPDATE_LOG.write_text("", encoding="utf-8")
    _PROC = subprocess.Popen(
        ["/bin/bash", str(PROJECT_ROOT / "scripts" / "full_update.sh")],
        cwd=PROJECT_ROOT,
        stdout=open(FULL_UPDATE_LOG, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,  # アプリを閉じても継続
    )
    FULL_UPDATE_PID.write_text(str(_PROC.pid), encoding="utf-8")
    return full_update_status()


def full_update_status() -> dict:
    """{running, pid, log_tail, done, failed}"""
    # 自プロセスが起動した子はpoll()で回収(ゾンビ化して「実行中」に見え続けるのを防ぐ)
    if _PROC is not None:
        _PROC.poll()

    pid = None
    if FULL_UPDATE_PID.exists():
        try:
            pid = int(FULL_UPDATE_PID.read_text().strip())
        except ValueError:
            pid = None

    running = bool(pid) and _pid_is_our_script(pid)
    if pid and not running:
        # 終了済み/PID再利用 → staleなpidファイルを片付ける
        FULL_UPDATE_PID.unlink(missing_ok=True)
        pid = None

    tail = ""
    done = False
    failed = False
    if FULL_UPDATE_LOG.exists():
        lines = FULL_UPDATE_LOG.read_text(encoding="utf-8",
                                          errors="replace").splitlines()
        tail = "\n".join(lines[-25:])
        done = any("FULL_UPDATE_DONE status=ok" in ln for ln in lines[-5:])
        failed = any("FULL_UPDATE_DONE status=error" in ln
                     for ln in lines[-5:])
    return {"running": running, "pid": pid, "log_tail": tail,
            "done": done, "failed": failed}


def stop_full_update() -> bool:
    st = full_update_status()
    if not (st["running"] and st["pid"]):
        return False
    # PID再利用の誤爆防止: 対象が本当に我々のスクリプトの時だけ殺す
    if not _pid_is_our_script(st["pid"]):
        FULL_UPDATE_PID.unlink(missing_ok=True)
        return False
    try:
        os.killpg(os.getpgid(st["pid"]), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(st["pid"], signal.SIGTERM)
        except Exception:
            return False
    return True


# ------------------------------------------------------------------
# ③ データ充足チェック(メタデータのみ・軽量)
# ------------------------------------------------------------------

def check_coverage(start: date, end: date, progress=None) -> list[dict]:
    """EDINETメタデータのみで日次の臨時報告書(180・上場)件数を数える。

    Returns:
        [{"date": iso, "count": int}] 土日は除外。
    """
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("EDINET_API_KEY", "")
    if not api_key:
        raise RuntimeError("EDINET_API_KEY が設定されていません(.env)")

    from src.edinet_client import EXTRAORDINARY_REPORT_CODE, EdinetClient

    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    days = [d for d in days if d.weekday() < 5]
    out: list[dict] = []
    with EdinetClient(api_key=api_key, rate_limit=0.5) as client:
        for i, d in enumerate(days):
            if progress:
                progress((i + 1) / len(days), f"{d.isoformat()} を確認中")
            try:
                docs = client._get_documents(d)
            except Exception:
                out.append({"date": d.isoformat(), "count": None})
                continue
            n = sum(
                1 for doc in docs
                if doc.get("docTypeCode") == EXTRAORDINARY_REPORT_CODE
                and (doc.get("secCode") or "")
            )
            out.append({"date": d.isoformat(), "count": n})
    return out


if __name__ == "__main__":
    # CLI: python -m src.jobs fast|coverage
    cmd = sys.argv[1] if len(sys.argv) > 1 else "fast"
    if cmd == "fast":
        fast_regen(progress=print)
    elif cmd == "coverage":
        y = date.today().year
        rows = check_coverage(date(y, 6, 1), date.today())
        for r in rows:
            print(r["date"], r["count"])
    else:
        print(json.dumps(full_update_status(), ensure_ascii=False, indent=1))
