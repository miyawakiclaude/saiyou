#!/usr/bin/env python3
"""Build a unified sales list (営業リスト) from:
  - PDF: 企業主導型保育園 (corporate-led nursery)
  - Excel: 幼稚園・幼保連携型認定こども園
"""
import csv
import re
import sys
import pdfplumber
import openpyxl

PDF_PATH = "/root/.claude/uploads/ee56ff78-fe5d-430d-b2c8-78c9313c22e2/86c3cce8-2026043001r801jyuusoku.pdf"
XLSX_PATH = "/root/.claude/uploads/ee56ff78-fe5d-430d-b2c8-78c9313c22e2/46558f07-______.xlsx"
OUT = "/home/user/saiyou/sales_list.csv"

HEADER = [
    "施設種別", "都道府県", "市区町村", "施設名", "住所",
    "郵便番号", "設置者法人名", "運営委託先法人名",
    "設置区分", "設置パターン", "定員合計", "在籍児童合計",
    "充足率", "開所時間", "開所曜日", "施設HP", "出典",
]


def clean(s):
    if s is None:
        return ""
    return str(s).replace("\n", " ").strip()


def parse_pdf(rows_out):
    print(f"[PDF] {PDF_PATH}")
    n = 0
    with pdfplumber.open(PDF_PATH) as pdf:
        for pi, page in enumerate(pdf.pages):
            tables = page.extract_tables()
            for t in tables:
                for r in t:
                    if not r or not r[0]:
                        continue
                    num = clean(r[0])
                    # only data rows whose first cell is a number
                    if not re.fullmatch(r"\d+", num):
                        continue
                    pref = clean(r[1])
                    city = clean(r[2])
                    banchi = clean(r[3])
                    bldg = clean(r[4])
                    name = clean(r[5])
                    setter = clean(r[8])
                    operator = clean(r[10])
                    pattern = clean(r[11])
                    open_basic = clean(r[12])
                    open_ext = clean(r[13])
                    days = clean(r[14])
                    capacity_total = clean(r[19])
                    enrolled_total = clean(r[36])
                    fill_rate = clean(r[37])
                    hp = clean(r[38])
                    address = f"{pref}{city}{banchi}"
                    if bldg:
                        address = f"{address} {bldg}"
                    open_hours = open_basic
                    if open_ext and open_ext != open_basic:
                        open_hours = f"{open_basic}（延長{open_ext}）"
                    rows_out.append([
                        "企業主導型保育園",
                        pref, city, name, address, "",
                        setter, operator, "",
                        pattern, capacity_total, enrolled_total,
                        fill_rate, open_hours, days, hp,
                        "児童育成協会_2026年1月施設一覧",
                    ])
                    n += 1
            if (pi + 1) % 10 == 0:
                print(f"  page {pi+1}/{len(pdf.pages)} ({n} rows)")
    print(f"[PDF] extracted {n} rows")


PREF_RE = re.compile(r"^\d+\(([^)]+)\)$")
KBN_RE = re.compile(r"^\d+\(([^)]+)\)$")
TYPE_RE = re.compile(r"^[A-Z]\d+\(([^)]+)\)$")

PREF_FULL = {
    "北海道": "北海道",
    "東京": "東京都", "京都": "京都府", "大阪": "大阪府",
}
# 県 suffix for everything else
for _p in ["青森","岩手","宮城","秋田","山形","福島","茨城","栃木","群馬","埼玉",
          "千葉","神奈川","新潟","富山","石川","福井","山梨","長野","岐阜","静岡",
          "愛知","三重","滋賀","兵庫","奈良","和歌山","鳥取","島根","岡山","広島",
          "山口","徳島","香川","愛媛","高知","福岡","佐賀","長崎","熊本","大分",
          "宮崎","鹿児島","沖縄"]:
    PREF_FULL[_p] = _p + "県"


def parse_xlsx(rows_out):
    print(f"[XLSX] {XLSX_PATH}")
    wb = openpyxl.load_workbook(XLSX_PATH, read_only=True, data_only=True)
    ws = wb["Sheet1"]
    rows = ws.iter_rows(values_only=True)
    next(rows)  # title row
    next(rows)  # header row
    n = 0
    skipped_abolished = 0
    skipped_other = 0
    for r in rows:
        if not r or not r[0]:
            continue
        code, school_type, pref_no, kbn, honbun, name, addr, zip_, _set_dt, abol_dt, _old, _new = r[:12]
        if abol_dt is not None:
            skipped_abolished += 1
            continue
        if honbun and "9" in str(honbun):
            skipped_abolished += 1
            continue
        # only keep 幼稚園 (A1) and こども園 (A2)
        type_m = TYPE_RE.match(str(school_type or ""))
        type_label = type_m.group(1) if type_m else clean(school_type)
        if "幼稚園" in type_label:
            type_label = "幼稚園"
        elif "こども" in type_label:
            type_label = "幼保連携型認定こども園"
        else:
            skipped_other += 1
            continue
        pref_m = PREF_RE.match(str(pref_no or ""))
        pref_short = pref_m.group(1) if pref_m else ""
        pref = PREF_FULL.get(pref_short, pref_short)
        kbn_m = KBN_RE.match(str(kbn or ""))
        kbn_label = kbn_m.group(1) if kbn_m else clean(kbn)
        kbn_label = {"国": "国立", "公": "公立", "私": "私立"}.get(kbn_label, kbn_label)
        a = clean(addr)
        city = ""
        if pref and a.startswith(pref):
            rest = a[len(pref):]
            # 政令指定都市は「市+区」までを市区町村として扱う
            m2 = re.match(r"^(.+?市.+?区|.+?[市区町村]|.+?郡.+?[町村])", rest)
            if m2:
                city = m2.group(1)
        zip_str = ""
        if zip_:
            z = str(zip_).strip()
            if len(z) == 7 and z.isdigit():
                zip_str = f"{z[:3]}-{z[3:]}"
            else:
                zip_str = z
        rows_out.append([
            type_label,
            pref, city, clean(name), a, zip_str,
            "", "", kbn_label,
            "", "", "", "", "", "", "",
            "文部科学省_学校コード一覧",
        ])
        n += 1
    print(f"[XLSX] extracted {n} rows (skipped abolished={skipped_abolished}, other-type={skipped_other})")


def main():
    out_rows = []
    parse_pdf(out_rows)
    parse_xlsx(out_rows)
    # sort: prefecture, city, type, name
    out_rows.sort(key=lambda x: (x[1], x[2], x[0], x[3]))
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(out_rows)
    print(f"[OUT] {OUT}  total={len(out_rows)}")
    # summary by type
    from collections import Counter
    c = Counter(r[0] for r in out_rows)
    for k, v in c.most_common():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
