"""失敗した文書のテキスト行を詳細に確認する。"""
from __future__ import annotations

import io
import os
import re
import zipfile

from dotenv import load_dotenv

from src.edinet_client import EdinetClient

load_dotenv()

api_key = os.getenv("EDINET_API_KEY", "")
client = EdinetClient(api_key=api_key)

# ローツェ (成功しなかった最初のサンプル)
doc_id = "S100VUQI"
print(f"=== {doc_id} ===")
zip_bytes = client.download_document_zip(doc_id)

with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
    for name in zf.namelist():
        if ("honbun" in name or "PublicDoc" in name) and name.endswith(".htm"):
            content = zf.read(name).decode("utf-8")
            text = re.sub(r"<style[^>]*>.*?</style>", "", content, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", "\n", text)
            text = re.sub(r"&#\d+;", " ", text)
            text = re.sub(r"&\w+;", " ", text)
            lines = [l.strip() for l in text.split("\n") if l.strip()]

            print(f"ファイル: {name}")
            print(f"行数: {len(lines)}")
            print()

            # 議決結果関連のキーワード周辺を出力
            for i, line in enumerate(lines):
                if any(kw in line for kw in [
                    "決議事項", "議案", "賛成", "反対", "棄権",
                    "可決", "否決", "会社提案", "株主提案",
                    "取締役", "監査", "剰余金", "議決権",
                ]):
                    print(f"  L{i:4d}: {line[:120]}")
            break
