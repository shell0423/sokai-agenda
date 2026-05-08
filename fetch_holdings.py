"""アクティビストの大量保有報告書から保有比率推移を取得する。"""
from __future__ import annotations

import json
import os
import re
import time
import zipfile
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("EDINET_API_KEY", "")
BASE_URL = "https://disclosure.edinet-fsa.go.jp/api/v2"
HEADERS = {"Ocp-Apim-Subscription-Key": API_KEY}

# 対象企業（証券コード → 企業名）
TARGET_CODES = {
    "4626": "太陽HD",
    "4549": "栄研化学",
    "3593": "ホギメディカル",
    "2267": "ヤクルト本社",
    "7201": "日産自動車",
    "6201": "豊田自動織機",
    "4886": "あすか製薬HD",
    "8795": "T&D HD",
    "9377": "エージーピー",
    "1827": "ナカノフドー建設",
    "7937": "ツツミ",
    "3646": "駅探",
    "5186": "ニッタ",
    "6927": "ヘリオステクノHD",
    "5408": "中山製鋼所",
    "6351": "鶴見製作所",
    "6419": "マースグループHD",
    "8291": "日産東京販売HD",
    "8630": "SOMPO HD",
    "9201": "日本航空",
    "1921": "巴コーポレーション",
    "9362": "兵機海運",
    "9930": "北沢産業",
    "2168": "パソナグループ",
}


def scan_tairyo_docs(
    start: date, end: date, target_codes: set[str]
) -> list[dict]:
    """大量保有報告書のメタデータを取得。"""
    results = []
    current = start
    while current <= end:
        url = f"{BASE_URL}/documents.json"
        params = {
            "date": current.strftime("%Y-%m-%d"),
            "type": 2,
            "Subscription-Key": API_KEY,
        }
        try:
            resp = httpx.get(url, params=params, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  Error on {current}: {e}")
            current += timedelta(days=1)
            time.sleep(0.5)
            continue

        docs = data.get("results", [])
        for doc in docs:
            doc_type = str(doc.get("docTypeCode", ""))
            if doc_type not in ("350", "360"):
                continue
            sec_code_raw = str(doc.get("secCode", "") or "")
            sec_code = sec_code_raw[:4]
            if sec_code in target_codes:
                results.append({
                    "date": current.strftime("%Y-%m-%d"),
                    "sec_code": sec_code,
                    "filer_name": doc.get("filerName", ""),
                    "doc_description": doc.get("docDescription", ""),
                    "doc_id": doc.get("docID", ""),
                    "doc_type": doc_type,
                })

        current += timedelta(days=1)
        time.sleep(0.3)

        if current.day == 1:
            print(f"  Scanning {current.strftime('%Y-%m')}...")

    return results


def download_and_extract_ratio(doc_id: str) -> dict | None:
    """大量保有報告書のZIPをDLし、保有割合を抽出。"""
    url = f"{BASE_URL}/documents/{doc_id}"
    params = {"type": 1, "Subscription-Key": API_KEY}
    try:
        resp = httpx.get(url, params=params, headers=HEADERS, timeout=60)
        resp.raise_for_status()
    except Exception as e:
        print(f"    DL error {doc_id}: {e}")
        return None

    try:
        zf = zipfile.ZipFile(BytesIO(resp.content))
    except Exception:
        return None

    # XBRLまたはHTMLファイルを探す
    result = {}
    for name in zf.namelist():
        if name.startswith("XBRL/PublicDoc/") and (
            name.endswith(".htm") or name.endswith(".html")
        ):
            try:
                content = zf.read(name).decode("utf-8", errors="replace")
            except Exception:
                continue

            # 保有割合を抽出
            # パターン1: 「保有割合」の近くの数値
            # パターン2: XBRL iXBRLタグ
            ratios = _extract_ratios(content)
            if ratios:
                result.update(ratios)

    return result if result else None


def _extract_ratios(html: str) -> dict:
    """HTMLから保有割合情報を抽出。"""
    import re

    # HTMLタグを除去
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text)

    result = {}

    # 「保有割合」の近くにある数値を探す
    # パターン: 「株券等保有割合 XX.XX%」
    ratio_patterns = [
        r"株券等保有割合[^0-9]*?(\d+[.．]\d+)\s*[％%]",
        r"保有割合[^0-9]*?(\d+[.．]\d+)\s*[％%]",
        r"提出後の株券等保有割合[^0-9]*?(\d+[.．]\d+)\s*[％%]",
    ]
    for pat in ratio_patterns:
        m = re.search(pat, text)
        if m:
            val = m.group(1).replace("．", ".")
            result["holding_ratio"] = float(val)
            break

    # 提出者名
    name_patterns = [
        r"氏名又は名称[^a-zA-Zぁ-んァ-ヶ亜-熙]*?([ぁ-んァ-ヶ亜-熙a-zA-Z\s・]+)",
    ]
    for pat in name_patterns:
        m = re.search(pat, text)
        if m:
            name = m.group(1).strip()
            if len(name) > 1 and len(name) < 100:
                result["holder_name"] = name
            break

    # 提出前の保有割合
    before_patterns = [
        r"提出前[^0-9]*?株券等保有割合[^0-9]*?(\d+[.．]\d+)\s*[％%]",
        r"変更前[^0-9]*?(\d+[.．]\d+)\s*[％%]",
    ]
    for pat in before_patterns:
        m = re.search(pat, text)
        if m:
            val = m.group(1).replace("．", ".")
            result["prev_ratio"] = float(val)
            break

    return result


def main() -> None:
    target_codes = set(TARGET_CODES.keys())

    # 2年分スキャン (2023/4/1 〜 2025/3/18)
    start = date(2023, 4, 1)
    end = date(2025, 3, 18)

    cache_path = Path("output/cache/tairyo_docs.json")
    if cache_path.exists():
        print("キャッシュから大量保有報告書メタデータを読み込み...")
        with open(cache_path) as f:
            docs = json.load(f)
        print(f"  {len(docs)}件のメタデータを読み込みました")
    else:
        print(f"=== 大量保有報告書スキャン ===")
        print(f"期間: {start} 〜 {end}")
        print(f"対象企業: {len(target_codes)}社\n")
        docs = scan_tairyo_docs(start, end, target_codes)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(docs, f, ensure_ascii=False, indent=2)
        print(f"\n{len(docs)}件のメタデータを取得")

    # 各ドキュメントの保有割合を取得
    print(f"\n=== 保有割合の抽出 ({len(docs)}件) ===\n")

    holdings = []
    for i, doc in enumerate(docs):
        print(
            f"  [{i+1}/{len(docs)}] {doc['date']} {doc['sec_code']} "
            f"{TARGET_CODES.get(doc['sec_code'], '')} ← {doc['filer_name']}"
        )
        ratios = download_and_extract_ratio(doc["doc_id"])
        if ratios:
            holdings.append({
                **doc,
                **ratios,
            })
            ratio = ratios.get("holding_ratio", "?")
            prev = ratios.get("prev_ratio", "")
            prev_str = f" (前回: {prev}%)" if prev else ""
            print(f"    → 保有割合: {ratio}%{prev_str}")
        else:
            print(f"    → 抽出失敗")
        time.sleep(0.5)

    # 結果表示
    print(f"\n{'='*70}")
    print(f"=== 保有割合推移 ===")
    print(f"{'='*70}\n")

    by_company: dict[str, list] = {}
    for h in holdings:
        code = h["sec_code"]
        if code not in by_company:
            by_company[code] = []
        by_company[code].append(h)

    for code in sorted(by_company):
        name = TARGET_CODES.get(code, code)
        items = sorted(by_company[code], key=lambda x: x["date"])
        print(f"--- {code} {name} ---")
        for item in items:
            ratio = item.get("holding_ratio", "?")
            prev = item.get("prev_ratio", "")
            change = ""
            if prev and ratio != "?":
                diff = ratio - prev
                change = f" ({'+' if diff > 0 else ''}{diff:.2f}pp)"
            holder = item.get("holder_name", item["filer_name"])
            desc = item.get("doc_description", "")
            print(
                f"  {item['date']} | {holder} | "
                f"{ratio}%{change} | {desc}"
            )
        print()

    # CSV出力
    import csv

    with open(
        "output/activist_holdings.csv", "w",
        encoding="utf-8-sig", newline=""
    ) as f:
        w = csv.writer(f)
        w.writerow([
            "証券コード", "企業名", "日付", "報告者",
            "保有者名", "書類概要",
            "保有割合(%)", "前回保有割合(%)", "変動(pp)",
        ])
        for h in sorted(holdings, key=lambda x: (x["sec_code"], x["date"])):
            code = h["sec_code"]
            ratio = h.get("holding_ratio", "")
            prev = h.get("prev_ratio", "")
            change = ""
            if ratio and prev:
                change = f"{ratio - prev:+.2f}"
            w.writerow([
                code,
                TARGET_CODES.get(code, ""),
                h["date"],
                h["filer_name"],
                h.get("holder_name", ""),
                h.get("doc_description", ""),
                ratio,
                prev,
                change,
            ])

    print(f"出力: output/activist_holdings.csv")


if __name__ == "__main__":
    main()
