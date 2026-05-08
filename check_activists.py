"""対象企業の大量保有報告書を検索し、アクティビスト保有を調査する。"""
from __future__ import annotations

import csv
import json
import os
import time
from datetime import date, timedelta

import httpx
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("EDINET_API_KEY", "")
BASE_URL = "https://disclosure.edinet-fsa.go.jp/api/v2"
HEADERS = {"Ocp-Apim-Subscription-Key": API_KEY}

# 主要アクティビスト名（部分一致で検索）
ACTIVIST_KEYWORDS = [
    "オアシス", "Oasis",
    "村上", "シティインデックス", "City Index",
    "ストラテジックキャピタル", "Strategic Capital",
    "ダルトン", "Dalton",
    "エフィッシモ", "Effissimo",
    "サード・ポイント", "Third Point",
    "エリオット", "Elliott",
    "バリューアクト", "ValueAct",
    "タイヨウ", "Taiyo",
    "RMB", "旧村上ファンド",
    "南青山不動産",
    "レノ", "Reno",
    "アクティビスト",
    "光通信",
    "野村絢", "野村綜合",
    "シルチェスター", "Silchester",
    "ブランデス", "Brandes",
    "スパークス", "SPARX",
    "アセットバリュー", "Asset Value",
    "いちごアセット", "Ichigo",
    "旧MACアセット",
    "香港", "Hong Kong", "Singapore", "シンガポール",
    "Cayman", "ケイマン",
]

# 両条件を満たす14社 + 新規株主提案のみの主要企業
TARGET_CODES = {
    "1921": "巴コーポレーション",
    "2168": "パソナグループ",
    "3593": "ホギメディカル",
    "3646": "駅探",
    "4626": "太陽ホールディングス",
    "5186": "ニッタ",
    "5408": "中山製鋼所",
    "6201": "豊田自動織機",
    "6927": "ヘリオステクノ",
    "7201": "日産自動車",
    "9201": "日本航空",
    "9362": "兵機海運",
    "9377": "エージーピー",
    "9930": "北沢産業",
    # 新規株主提案のみの注目企業
    "1827": "ナカノフドー建設",
    "2267": "ヤクルト本社",
    "4549": "栄研化学",
    "4886": "あすか製薬HD",
    "8630": "SOMPOホールディングス",
    "8795": "T&Dホールディングス",
    "6351": "鶴見製作所",
    "6419": "マースグループHD",
    "7937": "ツツミ",
    "8291": "日産東京販売HD",
}


def search_tairyo_hoyu(
    start: date, end: date, target_sec_codes: set[str]
) -> list[dict]:
    """指定期間の大量保有報告書から対象企業のものを検索。"""
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
            resp = httpx.get(
                url, params=params, headers=HEADERS, timeout=30
            )
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
            sec_code = str(doc.get("secCode", ""))[:4]
            if sec_code in target_sec_codes:
                results.append({
                    "date": current.strftime("%Y-%m-%d"),
                    "sec_code": sec_code,
                    "company": doc.get("filerName", ""),
                    "issuer": doc.get("issuerName", "")
                              or doc.get("securitiesName", ""),
                    "doc_description": doc.get("docDescription", ""),
                    "doc_id": doc.get("docID", ""),
                    "filer_name": doc.get("filerName", ""),
                })

        current += timedelta(days=1)
        time.sleep(0.3)

        if current.day == 1:
            print(f"  Scanning {current.strftime('%Y-%m')}...")

    return results


def check_activist(filer_name: str) -> list[str]:
    """報告者名にアクティビストキーワードが含まれるか判定。"""
    matched = []
    for kw in ACTIVIST_KEYWORDS:
        if kw.lower() in filer_name.lower():
            matched.append(kw)
    return matched


def main() -> None:
    target_codes = set(TARGET_CODES.keys())

    # 2024/4/1 〜 2025/3/18（約1年）
    start = date(2024, 4, 1)
    end = date(2025, 3, 18)

    print(f"=== 大量保有報告書検索 ===")
    print(f"期間: {start} 〜 {end}")
    print(f"対象企業: {len(target_codes)}社")
    print()

    print("スキャン中...")
    results = search_tairyo_hoyu(start, end, target_codes)

    print(f"\n=== 検索結果: {len(results)}件 ===\n")

    # 企業ごとにまとめる
    by_company: dict[str, list[dict]] = {}
    for r in results:
        code = r["sec_code"]
        if code not in by_company:
            by_company[code] = []
        by_company[code].append(r)

    activist_found = []
    for code in sorted(by_company):
        name = TARGET_CODES.get(code, code)
        docs = by_company[code]
        print(f"--- {code} {name} ({len(docs)}件) ---")
        for d in docs:
            activist = check_activist(d["filer_name"])
            marker = " ★アクティビスト★" if activist else ""
            print(
                f"  {d['date']} | {d['filer_name']} | "
                f"{d['doc_description']}{marker}"
            )
            if activist:
                activist_found.append({
                    "code": code,
                    "company": name,
                    "filer": d["filer_name"],
                    "description": d["doc_description"],
                    "date": d["date"],
                    "keywords": activist,
                })
        print()

    # 大量保有報告書が無かった企業
    no_reports = target_codes - set(by_company.keys())
    if no_reports:
        print("--- 大量保有報告書なし ---")
        for code in sorted(no_reports):
            print(f"  {code} {TARGET_CODES.get(code, code)}")
        print()

    # アクティビストサマリー
    print(f"\n{'='*60}")
    print(f"★ アクティビスト検出サマリー: {len(activist_found)}件 ★")
    print(f"{'='*60}")
    for a in activist_found:
        print(
            f"  {a['code']} {a['company']} ← {a['filer']} "
            f"({a['date']}) [{','.join(a['keywords'])}]"
        )

    # CSV出力
    with open("output/activist_check.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "証券コード", "企業名", "日付", "報告者",
            "書類概要", "アクティビスト判定", "キーワード",
        ])
        for r in results:
            code = r["sec_code"]
            activist = check_activist(r["filer_name"])
            w.writerow([
                code,
                TARGET_CODES.get(code, ""),
                r["date"],
                r["filer_name"],
                r["doc_description"],
                "YES" if activist else "",
                ",".join(activist),
            ])

    print(f"\n出力: output/activist_check.csv")


if __name__ == "__main__":
    main()
