"""日次公開: 再生成 → docs/更新 → 秘密情報スキャン → commit & push。

launchd (com.sokai.refresh) から毎日 06:00 JST に呼び出される。boutetsuya-stocks の
publish.py と同じ思想で、公開前に秘密情報の混入を検査してから push する。

再生成の重さは3段階:
  --fast      src.jobs fast のみ（数秒〜1分）。キャッシュから再計算し、
              株価/PER/PBR を倉庫から取り直す。**日次運用はこれ**
              （総会データは年1回の季節データなので毎日EDINETを舐める意味が薄い）。
  (既定)      full_update.sh（EDINET全再スキャン・40分〜2時間）。総会シーズン用。
  --skip-full 再生成なし。既存ファイルをそのまま公開。

使い方:
  .venv/bin/python scripts/publish.py --fast          # 日次運用（launchd はこれを呼ぶ）
  .venv/bin/python scripts/publish.py                 # フル更新つき（総会後に手動で）
  .venv/bin/python scripts/publish.py --dry-run       # push しない疎通確認
  .venv/bin/python scripts/publish.py --skip-full     # 再生成せず現状のファイルを push
  .venv/bin/python scripts/publish.py --message "..." # commit message を上書き
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "output" / "logs"
LOG_FILE = LOG_DIR / "publish.log"
FULL_UPDATE_SH = PROJECT_ROOT / "scripts" / "full_update.sh"

# GitHub Pages の配信元（boutetsuya-stocks と同じ「HTML 1枚を配る」方式）。
# main ブランチの docs/ を Pages のソースに設定してあるため、ここへ置けば公開される。
DASHBOARD_HTML = PROJECT_ROOT / "output" / "dashboard_2026.html"
PAGES_DIR = PROJECT_ROOT / "docs"

# 公開対象（.gitignore の白リストと一致させる）。ワイルドカードは git add が展開する。
PUBLISH_TARGETS: list[str] = [
    "docs/",
    "output/derived/",
    "output/watchlist_*.csv",
    "output/trigger_holdings_summary.csv",
    "output/trigger_analysis_*.md",
    "output/dashboard_*.html",
    "output/diff_*.md",
    "data/*.json",
]

# 公開してはならない文字列パターン（混入検査）。boutetsuya の publish.py を基に、
# EDINET / warehouse 向けにチューニング。ヒット=検出即中断。
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    # 汎用トークン系
    re.compile(r"discord(?:app)?\.com/api/webhooks/", re.I),
    re.compile(r"X-API-Key", re.I),
    re.compile(r"Ocp-Apim-Subscription-Key\s*[:=]", re.I),
    # 環境変数名を「値付き」で書いてある行のみ検出（コメント中の名前だけの言及は許可）
    re.compile(r"EDINET_API_KEY\s*=\s*['\"]?[A-Za-z0-9_\-]{20,}", re.I),
    re.compile(r"EDINETDB_API_KEY\s*=\s*['\"]?[A-Za-z0-9_\-]{20,}", re.I),
    re.compile(r"JQUANTS_REFRESH_TOKEN", re.I),
    # Discord Bot トークン形（26+ 桁の3セグメント）
    re.compile(r"[A-Za-z0-9_\-]{24}\.[A-Za-z0-9_\-]{6}\.[A-Za-z0-9_\-]{27,}"),
    # 明らかな bearer / password 直書き
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{20,}"),
]


def _log(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    """subprocess.run のラッパ。ログにコマンドと exit code を残す。"""
    _log(f"$ {' '.join(cmd)}")
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        text=True,
        capture_output=True,
    )
    if proc.stdout:
        _log(proc.stdout.rstrip())
    if proc.stderr:
        _log("STDERR: " + proc.stderr.rstrip())
    if check and proc.returncode != 0:
        _log(f"❌ exit code {proc.returncode}")
        sys.exit(proc.returncode)
    return proc


def scan_for_secrets(paths: list[Path]) -> list[tuple[Path, str]]:
    """公開対象ファイル群を走査し、秘密情報が混入していないかチェック。

    テキストとして読めるファイルのみ検査（バイナリはスキップ）。
    戻り値: (file_path, matched_pattern_source) のリスト。空なら安全。
    """
    hits: list[tuple[Path, str]] = []
    for p in paths:
        if not p.exists() or not p.is_file():
            continue
        # 巨大ファイルは検査しない（10MB 超は白リスト外のはずだが念のため）
        if p.stat().st_size > 10 * 1024 * 1024:
            _log(f"⚠️  {p} は 10MB 超のため秘密情報スキャンをスキップ")
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:  # noqa: BLE001
            _log(f"⚠️  {p} 読み込み失敗（スキップ）: {e}")
            continue
        for pat in _SECRET_PATTERNS:
            if pat.search(text):
                hits.append((p, pat.pattern))
    return hits


def stage_pages() -> bool:
    """ダッシュボードHTMLを docs/index.html へ複製する（GitHub Pages の配信元）。

    boutetsuya-stocks の publish.py --dir と同じ役割。Pages は静的配信なので
    Python は動かず、生成済みHTMLをそのまま配る。

    Returns:
        複製したら True。生成物が無ければ False（この段は致命ではない）。
    """
    if not DASHBOARD_HTML.exists():
        _log(f"⚠️  {DASHBOARD_HTML.name} が無いため Pages 更新をスキップ"
             "（先に full_update / jobs fast を実行）")
        return False
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    # Jekyll に処理させない（_ 始まりのパス等を素通しさせるための慣習ファイル）
    (PAGES_DIR / ".nojekyll").touch()
    shutil.copy2(DASHBOARD_HTML, PAGES_DIR / "index.html")
    kb = (PAGES_DIR / "index.html").stat().st_size / 1024
    _log(f"✅ docs/index.html を更新（{kb:.0f}KB）")
    return True


def _resolve_publish_files() -> list[Path]:
    """PUBLISH_TARGETS を実ファイルパスに展開。"""
    files: list[Path] = []
    for pattern in PUBLISH_TARGETS:
        # 末尾スラッシュはディレクトリ再帰。
        if pattern.endswith("/"):
            base = PROJECT_ROOT / pattern.rstrip("/")
            if base.exists():
                files.extend(p for p in base.rglob("*") if p.is_file())
        else:
            files.extend(PROJECT_ROOT.glob(pattern))
    # 重複除去 & 並べ替え
    return sorted({p.resolve() for p in files})


def _git_has_staged_changes() -> bool:
    proc = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=str(PROJECT_ROOT),
    )
    # exit 1 = 差分あり、exit 0 = 差分なし
    return proc.returncode != 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="日次公開: 再生成 → docs/更新 → 秘密スキャン → push")
    ap.add_argument("--dry-run", action="store_true",
                    help="scan と git add まで実行し、commit/push はしない")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--fast", action="store_true",
                      help="full_update.sh の代わりに src.jobs fast を実行"
                           "（数秒〜1分・株価/PER/PBR を更新）。日次運用向け")
    mode.add_argument("--skip-full", action="store_true",
                      help="再生成せず現状ファイルだけを公開")
    ap.add_argument("-m", "--message", type=str, default="",
                    help="commit message（既定: 'daily: YYYY-MM-DD refresh'）")
    args = ap.parse_args()

    _log("=" * 50)
    _log(f"publish 開始 (dry_run={args.dry_run}, fast={args.fast}, "
         f"skip_full={args.skip_full})")

    # 1) データを再生成（--fast=軽量 / 既定=フル / --skip-full=なし）
    if args.fast:
        _log("--- [1/5] 高速再生成 (src.jobs fast) ---")
        proc = subprocess.run(
            [sys.executable, "-m", "src.jobs", "fast"],
            cwd=str(PROJECT_ROOT), text=True, capture_output=True,
        )
        for line in (proc.stdout or "").splitlines():
            _log("  " + line)
        if proc.returncode != 0:
            _log(f"❌ src.jobs fast 失敗 (exit {proc.returncode}). push 中止")
            if proc.stderr:
                _log("STDERR tail: " + "\n".join(proc.stderr.splitlines()[-20:]))
            return proc.returncode
        _log("✅ 高速再生成 完了")
    elif not args.skip_full:
        if not FULL_UPDATE_SH.exists():
            _log(f"❌ {FULL_UPDATE_SH} が見つかりません")
            return 1
        _log("--- [1/5] full_update.sh 実行 ---")
        proc = subprocess.run(
            ["/bin/bash", str(FULL_UPDATE_SH)],
            cwd=str(PROJECT_ROOT),
            text=True,
            capture_output=True,
        )
        # full_update.sh は自分でログを追記するので、ここでは要約だけ残す
        if proc.returncode != 0:
            _log(f"❌ full_update.sh 失敗 (exit {proc.returncode}). push 中止")
            if proc.stderr:
                _log("STDERR tail: " + "\n".join(proc.stderr.splitlines()[-20:]))
            return proc.returncode
        _log("✅ full_update.sh 完了")
    else:
        _log("--- [1/5] full_update.sh スキップ (--skip-full) ---")

    # 2) GitHub Pages 配信用に docs/index.html を更新
    _log("--- [2/5] docs/ (GitHub Pages) を更新 ---")
    stage_pages()

    # 3) 公開対象ファイルを列挙・秘密情報スキャン
    _log("--- [3/5] 公開対象を列挙 & 秘密情報スキャン ---")
    files = _resolve_publish_files()
    _log(f"対象 {len(files)} ファイル")
    hits = scan_for_secrets(files)
    if hits:
        _log("🛑 秘密情報らしき文字列を検出。push 中止:")
        for path, pat in hits:
            _log(f"   - {path.relative_to(PROJECT_ROOT)}  ← {pat}")
        return 2
    _log("✅ 秘密情報の混入なし")

    # 4) git add
    _log("--- [4/5] git add ---")
    add_cmd = ["git", "add"] + PUBLISH_TARGETS
    proc = subprocess.run(add_cmd, cwd=str(PROJECT_ROOT), text=True, capture_output=True)
    if proc.returncode != 0:
        # pathspec が空だと 128 で失敗する。1つも対象がないケースは正常扱いにする。
        if "did not match any files" in (proc.stderr or ""):
            _log("(add 対象が1つも存在しなかった)")
        else:
            _log("❌ git add 失敗: " + (proc.stderr or ""))
            return proc.returncode
    if not _git_has_staged_changes():
        _log("差分なし。commit/push スキップして正常終了")
        return 0

    # 5) commit & push
    if args.dry_run:
        _log("--- [5/5] dry-run のため commit/push はスキップ ---")
        # ステージング状態は残しておく（オペレータが確認できるよう）
        return 0

    _log("--- [5/5] commit & push ---")
    msg = args.message or f"daily: {datetime.now().strftime('%Y-%m-%d')} refresh"
    _run(["git", "commit", "-m", msg])
    _run(["git", "push", "origin", "main"])
    _log("✅ publish 完了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
