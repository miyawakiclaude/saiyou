#!/usr/bin/env python3
"""ここdeサーチ (https://www.wam.go.jp/kokodesearch/) から各施設の TEL/FAX を取得する。

使い方:
  1. ローカル等の egress 制限のない環境で実行する
  2. 依存: Python 3.9+ / playwright
       pip install playwright
       playwright install chromium
  3. 実行: python scrape_kokode_search.py
       オプション:
         --input  sales_list.csv             入力CSV
         --output sales_list_with_contacts.csv 出力CSV（途中経過もここに書く）
         --start 0  --limit 0                 行の範囲指定（0=全部）
         --headed                             ブラウザ表示で動かす（デバッグ用）
         --delay 2.0                          1件ごとの待機秒（礼儀のため）

特徴:
  - 入力 sales_list.csv の全行を処理。既に「電話番号/FAX」が入っている行はスキップ → レジューム対応
  - 25件ごとに出力CSVへ書き出す（途中で止まっても再開可能）
  - 失敗・該当なしは空欄のまま残す
  - 検索クエリ: 施設名 + 市区町村 で絞り込み（同名対策）
  - WAF対策: 実ブラウザ（Chromium）経由、UA偽装、適度な遅延、リトライ最大2回

注意:
  - 公開API ではないため、利用規約・robots.txt を遵守し、--delay を 1.5 秒以上で実行してください
  - 大量並列アクセスはサイト側に迷惑が掛かるため、本スクリプトは並列化していません
"""
from __future__ import annotations
import argparse
import csv
import re
import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    sys.stderr.write(
        "playwright が見つかりません。次を実行してください:\n"
        "  pip install playwright\n"
        "  playwright install chromium\n"
    )
    sys.exit(1)

BASE = "https://www.wam.go.jp/kokodesearch/"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

PHONE_RE = re.compile(
    r"(?<![\d])"
    r"(0\d{1,4})\s*[-－ｰ()（）./・]?\s*(\d{1,4})\s*[-－ｰ()（）./・]?\s*(\d{3,4})"
    r"(?![\d])"
)


def normalize_phone(groups: tuple[str, str, str]) -> str:
    a, b, c = groups
    digits = a + b + c
    if not digits.startswith("0"):
        return ""
    if len(digits) not in (9, 10, 11):
        return ""
    return f"{a}-{b}-{c}"


def parse_tel_fax(text: str) -> tuple[str, str]:
    """ページ全文テキストから TEL/FAX を抽出する。

    1. "電話番号" / "FAX" のラベル直後を優先
    2. 上で取れなければ、ページ内の最初の電話番号を TEL とする
    """
    text = text.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    tel, fax = "", ""

    # ラベル付き抽出（ラベルから前方 0〜40文字以内に電話番号があれば採用）
    for label in ("電話番号", "電話", "ＴＥＬ", "TEL", "Tel"):
        for m in re.finditer(re.escape(label), text):
            window = text[m.end(): m.end() + 60]
            pm = PHONE_RE.search(window)
            if pm:
                cand = normalize_phone(pm.groups())
                if cand and not tel:
                    tel = cand
                    break
        if tel:
            break

    for label in ("FAX番号", "ＦＡＸ", "FAX", "Fax", "ファクシミリ", "ファックス"):
        for m in re.finditer(re.escape(label), text):
            window = text[m.end(): m.end() + 60]
            pm = PHONE_RE.search(window)
            if pm:
                cand = normalize_phone(pm.groups())
                if cand and not fax:
                    fax = cand
                    break
        if fax:
            break

    # フォールバック: TEL が取れなければ最初の電話番号
    if not tel:
        pm = PHONE_RE.search(text)
        if pm:
            tel = normalize_phone(pm.groups())

    return tel, fax


def open_top(page) -> None:
    page.goto(BASE, wait_until="domcontentloaded", timeout=30_000)
    # ここdeサーチのトップは「キーワード/施設名で探す」入口を持つ。
    # 詳しい DOM が分かり次第セレクタを調整してください。
    page.wait_for_timeout(800)


def search_facility(page, name: str, pref: str, city: str) -> str | None:
    """施設名 + 市区町村 で検索し、最初のヒットの詳細URLを返す。失敗時 None。

    注: 実DOMが取れていないため、複数のセレクタ候補をフォールバック試行する。
    現地で動かしたあとに合うものを残し、合わないものを削除してください。
    """
    open_top(page)

    # キーワード検索フォームへ遷移するボタン候補（テキストで探す）
    for trigger in [
        "text=キーワードで探す",
        "text=キーワード検索",
        "text=フリーワード",
        "text=施設名で探す",
    ]:
        try:
            el = page.locator(trigger).first
            if el.count():
                el.click(timeout=3_000)
                page.wait_for_timeout(500)
                break
        except Exception:
            continue

    # 入力欄候補
    query = f"{name} {city}".strip()
    filled = False
    for sel in [
        'input[type="search"]',
        'input[name*="keyword"]',
        'input[name*="word"]',
        'input[placeholder*="キーワード"]',
        'input[placeholder*="施設"]',
        'input[type="text"]',
    ]:
        try:
            el = page.locator(sel).first
            if el.count():
                el.fill(query, timeout=2_000)
                filled = True
                break
        except Exception:
            continue
    if not filled:
        return None

    # 検索ボタン候補
    for sel in [
        'button:has-text("検索")',
        'input[type="submit"][value*="検索"]',
        'button[type="submit"]',
        'a:has-text("検索")',
    ]:
        try:
            el = page.locator(sel).first
            if el.count():
                el.click(timeout=2_000)
                break
        except Exception:
            continue

    # 結果ロード待ち
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except PWTimeout:
        pass

    # 結果一覧から最初の詳細リンクを取得
    for sel in [
        'a[href*="ANN010102E15.do"]',
        'a[href*="facility="]',
        'a:has-text("詳細")',
    ]:
        try:
            links = page.locator(sel)
            if links.count():
                href = links.first.get_attribute("href")
                if href:
                    if href.startswith("/"):
                        return "https://www.wam.go.jp" + href
                    if href.startswith("http"):
                        return href
                    return BASE + href
        except Exception:
            continue
    return None


def fetch_detail(page, url: str) -> tuple[str, str]:
    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except PWTimeout:
        pass
    body = page.locator("body").inner_text(timeout=10_000)
    return parse_tel_fax(body)


def load_input(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    return header, rows


def ensure_columns(header: list[str], rows: list[list[str]]) -> tuple[list[str], list[list[str]], int, int]:
    """電話番号 / FAX 列を追加（なければ）。インデックスを返す。"""
    if "電話番号" in header and "FAX" in header:
        return header, rows, header.index("電話番号"), header.index("FAX")
    hp_idx = header.index("施設HP") if "施設HP" in header else len(header) - 1
    insert_at = hp_idx + 1
    new_header = header[:insert_at] + ["電話番号", "FAX"] + header[insert_at:]
    new_rows = [r[:insert_at] + ["", ""] + r[insert_at:] for r in rows]
    return new_header, new_rows, insert_at, insert_at + 1


def save(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="sales_list.csv")
    ap.add_argument("--output", default="sales_list_with_contacts.csv")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0, help="0=all")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--delay", type=float, default=2.0)
    args = ap.parse_args()

    src = Path(args.input)
    dst = Path(args.output)

    # 既存出力があればそれをベースにレジューム
    if dst.exists():
        header, rows = load_input(dst)
    else:
        header, rows = load_input(src)
    header, rows, tel_idx, fax_idx = ensure_columns(header, rows)
    name_idx = header.index("施設名")
    pref_idx = header.index("都道府県")
    city_idx = header.index("市区町村")

    end = len(rows) if args.limit == 0 else min(len(rows), args.start + args.limit)
    print(f"target rows: {args.start}..{end} (total {end - args.start})")

    stats = {"ok_tel": 0, "ok_fax": 0, "skip": 0, "miss": 0, "err": 0}
    t0 = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        ctx = browser.new_context(user_agent=UA, locale="ja-JP")
        page = ctx.new_page()
        page.set_default_timeout(20_000)

        for i in range(args.start, end):
            r = rows[i]
            if r[tel_idx].strip() or r[fax_idx].strip():
                stats["skip"] += 1
                continue
            name = r[name_idx].strip()
            pref = r[pref_idx].strip()
            city = r[city_idx].strip()
            tel = fax = ""
            tries = 0
            while tries < 2 and not (tel or fax):
                tries += 1
                try:
                    url = search_facility(page, name, pref, city)
                    if not url:
                        break
                    tel, fax = fetch_detail(page, url)
                except Exception as e:
                    if tries >= 2:
                        stats["err"] += 1
                        print(f"  [ERR row {i}] {name}: {e!r}")
                    else:
                        time.sleep(2)
            if tel:
                r[tel_idx] = tel
                stats["ok_tel"] += 1
            if fax:
                r[fax_idx] = fax
                stats["ok_fax"] += 1
            if not (tel or fax):
                stats["miss"] += 1

            done = i - args.start + 1
            if done % 10 == 0 or done == end - args.start:
                el = time.time() - t0
                print(
                    f"  {done}/{end - args.start}  "
                    f"tel={stats['ok_tel']} fax={stats['ok_fax']} "
                    f"miss={stats['miss']} err={stats['err']} skip={stats['skip']} "
                    f"({el:.0f}s)"
                )
            # 25件ごとに途中保存
            if done % 25 == 0:
                save(dst, header, rows)

            time.sleep(args.delay)

        browser.close()

    save(dst, header, rows)
    print(f"wrote {dst}")
    print(f"stats: {stats}")


if __name__ == "__main__":
    main()
