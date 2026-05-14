#!/usr/bin/env python3
"""Fetch each 施設HP and extract TEL/FAX from the page.

- 対象: sales_list.csv の「施設HP」列に値がある行のみ
- 取得失敗・抽出失敗は空欄のまま
- TEL/FAX 列を追加した sales_list_enriched.csv を出力
"""
from __future__ import annotations
import csv
import re
import sys
import time
import html
import urllib.parse
import urllib.request
import concurrent.futures
from threading import Lock

SRC = "/home/user/saiyou/sales_list.csv"
DST = "/home/user/saiyou/sales_list_enriched.csv"

UA = "Mozilla/5.0 (compatible; SalesListEnricher/1.0; +contact via repo owner)"
TIMEOUT = 12
MAX_WORKERS = 8

# 0X-XXXX-XXXX / 0X(XXXX)XXXX / 0XXXXXXXXXX / 0X.XXXX.XXXX 等
PHONE_RE = re.compile(
    r"(?<![\d])"
    r"(0\d{1,4})\s*[-－ｰ()（）./・]?\s*(\d{1,4})\s*[-－ｰ()（）./・]?\s*(\d{3,4})"
    r"(?![\d])"
)

TEL_LABELS = ("tel", "ＴＥＬ", "電話", "でんわ", "phone", "ﾃﾚﾌｫﾝ", "☎", "📞")
FAX_LABELS = ("fax", "ＦＡＸ", "ファクス", "ファックス", "ﾌｧｯｸｽ", "ふぁっくす")

KEYWORD_PAGES = ("contact", "access", "about", "info", "概要", "アクセス", "問い合わせ", "お問合せ", "施設案内")

# 抽出除外: 法人番号や郵便番号と誤検出されやすい長すぎる桁
def _norm(num: tuple[str, str, str]) -> str:
    a, b, c = num
    full = f"{a}-{b}-{c}"
    digits = a + b + c
    # 日本の固定電話は 10桁、携帯は 11桁
    if len(digits) not in (9, 10, 11):
        return ""
    if not digits.startswith("0"):
        return ""
    return full


def extract_phones(text: str) -> tuple[str, str]:
    """Return (tel, fax)."""
    # zenkaku digits → hankaku
    text = text.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    text_lower = text.lower()
    tel, fax = "", ""
    # find every phone with its context window
    for m in PHONE_RE.finditer(text):
        num = _norm(m.groups())
        if not num:
            continue
        start = max(0, m.start() - 12)
        ctx = text_lower[start:m.start()]
        is_fax = any(lbl.lower() in ctx for lbl in FAX_LABELS)
        is_tel = any(lbl.lower() in ctx for lbl in TEL_LABELS)
        if is_fax and not fax:
            fax = num
        elif is_tel and not tel:
            tel = num
        elif not tel and not is_fax:
            # 最初に出てきた電話番号らしきものを TEL として採用
            tel = num
        if tel and fax:
            break
    return tel, fax


def strip_html(b: bytes, encoding_hint: str | None = None) -> str:
    # try utf-8 first, then sjis, then cp932
    encs = [encoding_hint, "utf-8", "shift_jis", "cp932", "euc_jp"]
    text = None
    for e in encs:
        if not e:
            continue
        try:
            text = b.decode(e, errors="strict")
            break
        except Exception:
            continue
    if text is None:
        text = b.decode("utf-8", errors="ignore")
    # strip scripts/styles
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text


def fetch(url: str) -> tuple[str, str] | None:
    """Return (text, base_url) or None on failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja,en;q=0.5"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read(800_000)  # cap at ~800KB
            ctype = resp.headers.get("Content-Type", "")
            enc = None
            m = re.search(r"charset=([\w-]+)", ctype, re.I)
            if m:
                enc = m.group(1)
            text = strip_html(raw, enc)
            return text, resp.geturl()
    except Exception:
        return None


def find_subpages(text: str, base_url: str) -> list[str]:
    """Find candidate contact/access subpages."""
    urls = []
    # very lightweight extraction — we already stripped html, so re-fetch raw? Skip.
    return urls  # disabled: we'll only check top page to keep request count low


def enrich_row(idx: int, url: str) -> tuple[int, str, str, str]:
    """Return (idx, tel, fax, status)."""
    url = url.strip()
    if not url:
        return idx, "", "", "empty"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    res = fetch(url)
    if res is None:
        # try http fallback
        if url.startswith("https://"):
            res = fetch("http://" + url[len("https://"):])
        if res is None:
            return idx, "", "", "fetch_failed"
    text, final = res
    tel, fax = extract_phones(text)
    return idx, tel, fax, "ok" if (tel or fax) else "no_match"


def main():
    with open(SRC, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    hp_idx = header.index("施設HP")
    # add TEL/FAX columns just after 施設HP
    insert_at = hp_idx + 1
    new_header = header[:insert_at] + ["電話番号", "FAX"] + header[insert_at:]
    # initialize rows
    new_rows = [r[:insert_at] + ["", ""] + r[insert_at:] for r in rows]

    targets = [(i, r[hp_idx]) for i, r in enumerate(rows) if r[hp_idx].strip()]
    print(f"target rows with HP: {len(targets)}")

    stats = {"ok": 0, "no_match": 0, "fetch_failed": 0, "empty": 0}
    lock = Lock()
    done = 0
    start = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(enrich_row, i, u): (i, u) for i, u in targets}
        for fut in concurrent.futures.as_completed(futs):
            idx, tel, fax, status = fut.result()
            with lock:
                new_rows[idx][insert_at] = tel
                new_rows[idx][insert_at + 1] = fax
                stats[status] = stats.get(status, 0) + 1
                done += 1
                if done % 25 == 0 or done == len(targets):
                    elapsed = time.time() - start
                    print(f"  {done}/{len(targets)}  ok={stats['ok']}  no_match={stats['no_match']}  fail={stats['fetch_failed']}  ({elapsed:.0f}s)")

    with open(DST, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(new_header)
        w.writerows(new_rows)
    print(f"wrote {DST}")
    print(f"stats: {stats}")


if __name__ == "__main__":
    main()
