#!/usr/bin/env python3
"""radar 웹페이지 빌드. briefs/, ledger/, framework/, raw/ 를 읽어 site/out/ 에 정적 페이지를 만든다.

  python3 site/build.py                     → site/out/index.html, site/out/data.json
  python3 site/build.py --date 2026-09-10   기준일 지정 (기본: 오늘, Asia/Seoul)

표준 라이브러리만 쓴다. .github/workflows/pages.yml 이 main 에 push 될 때마다 실행해 GitHub Pages 로 올린다.
집계 규칙은 .claude/commands/trend.md 의 스크립트와 같다 (30/90일 창, 30일 버킷, note 첫 단어 커짐/작아짐/유보, [충돌: A vs B], 티커 횟수를 섹터(테마)별로 묶기).
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import re
import shutil
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
OUT = SITE / "out"
AXES = ("정치권력", "기술권력", "자본권력", "코인")
GROW = re.compile(r"^(?:\[충돌:[^\]]*\]\s*)?(커짐|작아짐|유보)")
CONF = re.compile(r"\[충돌:\s*(\S+)\s+vs\s+(\S+)\s*\]", re.I)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def d(s: str) -> datetime.date:
    return datetime.date.fromisoformat(s)


def load_ledger() -> list[dict]:
    rows: list[dict] = []
    p = ROOT / "ledger/signals.jsonl"
    if not p.exists():
        return rows
    for n, line in enumerate(p.read_text(encoding="utf-8").split("\n"), 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            d(r["date"])
        except Exception as e:  # 장부는 수정 금지. 빌드만 멈춘다
            sys.exit(f"ledger {n}번째 줄 파싱 실패: {e}")
        r["line"] = n
        rows.append(r)
    return rows


def grow(r: dict) -> str:
    m = GROW.match(r.get("note", ""))
    return m.group(1) if m else "미표기"


def pair(m: re.Match) -> str:
    return " vs ".join(sorted((m.group(1), m.group(2)), key=lambda x: AXES.index(x) if x in AXES else 99))


def window(rows: list[dict], today: datetime.date, days: int) -> dict:
    cut = today - datetime.timedelta(days=days)
    w = [r for r in rows if cut < d(r["date"]) <= today]
    axes = []
    for a in AXES:
        s = [r for r in w if r["axis"] == a]
        g = collections.Counter(grow(r) for r in s)
        dc = collections.Counter(r["direction"] for r in s)
        axes.append({
            "axis": a, "count": len(s), "share": round(len(s) / len(w), 3) if w else 0,
            "grow": g["커짐"], "shrink": g["작아짐"], "hold": g["유보"], "untagged": g["미표기"],
            "dir": {"+": dc["+"], "-": dc["-"], "±": dc["±"]},
            "avg_conf": round(sum(r["confidence"] for r in s) / len(s), 2) if s else None,
            "themes": collections.Counter(r["theme"] for r in s).most_common(3),
            "sectors": collections.Counter(t for r in s for t in r["sectors"]).most_common(5),
        })
    hits = [(r, pair(m)) for r in w if (m := CONF.search(r.get("note", "")))]
    pairs = collections.Counter(p for _, p in hits)
    return {
        "days": days, "from": (cut + datetime.timedelta(days=1)).isoformat(), "to": today.isoformat(),
        "total": len(w), "axes": axes,
        "tickers": tickers(w),
        "conflicts": {
            "total": len(hits),
            "pairs": [{"pair": p, "count": c} for p, c in pairs.most_common()],
            "rows": [{"line": r["line"], "date": r["date"], "axis": r["axis"], "theme": r["theme"],
                      "fact": r["fact"], "note": r["note"], "pair": p}
                     for r, p in sorted(hits, key=lambda x: x[0]["date"])],
        },
    }


def _slot(t: str) -> dict:
    return {"ticker": t, "n": 0, "dir": {"+": 0, "-": 0, "±": 0}}


def tickers(w: list[dict]) -> dict:
    """시그널에 언급된 티커 횟수. 같은 섹터(테마)끼리 묶고 티커별 합계도 따로 낸다.
    한 시그널에 같은 티커가 두 번 있어도 1회. 방향은 그 시그널의 direction 을 티커마다 센다."""
    sectors: dict[tuple, dict] = {}
    totals: dict[str, dict] = {}
    themes_of: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for r in w:
        s = sectors.setdefault((r["axis"], r["theme"]), {"axis": r["axis"], "theme": r["theme"], "signals": 0, "mentions": 0, "tickers": {}})
        s["signals"] += 1
        for t in dict.fromkeys(r.get("sectors", [])):
            for slot in (s["tickers"].setdefault(t, _slot(t)), totals.setdefault(t, _slot(t))):
                slot["n"] += 1
                if r.get("direction") in slot["dir"]:
                    slot["dir"][r["direction"]] += 1
            s["mentions"] += 1
            themes_of[t][r["theme"]] += 1
    by_n = lambda x: (-x["n"], x["ticker"])
    by_sector = sorted(sectors.values(), key=lambda s: (-s["signals"], -s["mentions"], AXES.index(s["axis"]) if s["axis"] in AXES else 99, s["theme"]))
    for s in by_sector:
        s["tickers"] = sorted(s["tickers"].values(), key=by_n)
    by_ticker = sorted(totals.values(), key=by_n)
    for t in by_ticker:
        t["themes"] = [th for th, _ in themes_of[t["ticker"]].most_common()]
    return {"by_sector": by_sector, "by_ticker": by_ticker}


def buckets(rows: list[dict], today: datetime.date) -> list[dict]:
    out = []
    for k in range(3):
        hi = today - datetime.timedelta(days=30 * k)
        lo = today - datetime.timedelta(days=30 * (k + 1))
        b = {"label": f"{30 * k}~{30 * k + 29}일 전", "from": (lo + datetime.timedelta(days=1)).isoformat(), "to": hi.isoformat(), "axes": []}
        for a in AXES:
            s = [r for r in rows if r["axis"] == a and lo < d(r["date"]) <= hi]
            g = collections.Counter(grow(r) for r in s)
            b["axes"].append({"axis": a, "count": len(s), "grow": g["커짐"], "shrink": g["작아짐"]})
        out.append(b)
    return out


def load_briefs() -> list[dict]:
    out = []
    for p in sorted((ROOT / "briefs").glob("*.md"), reverse=True):
        if not DATE_RE.match(p.stem):
            continue
        md = p.read_text(encoding="utf-8")
        structural = sum(1 for l in md.split("\n") if l.startswith("|") and re.search(r"\|\s*true\s*\|", l))
        m = re.search(r"^## 3~4년 논지 변화\?\s*\n+([^\n]+)", md, re.M)
        thesis = m.group(1).strip() if m else "확인 안 됨"
        out.append({"date": p.stem, "md": md, "structural": structural, "thesis": thesis,
                    "none_today": "오늘 구조적 시그널 없음" in md})
    return out


def load_raw(days: int = 14) -> dict:
    out: dict[str, dict] = {}
    base = ROOT / "raw"
    if not base.exists():
        return out
    for day in sorted((x for x in base.iterdir() if x.is_dir() and DATE_RE.match(x.name)), reverse=True)[:days]:
        counts = {}
        for f in sorted(day.glob("*.json")):
            try:
                j = json.loads(f.read_text(encoding="utf-8"))
                counts[j.get("source", f.stem)] = {"count": j.get("count", len(j.get("items", []))), "error": j.get("error")}
            except Exception:
                counts[f.stem] = {"count": 0, "error": "읽기 실패"}
        out[day.name] = counts
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="radar 정적 페이지 빌드")
    ap.add_argument("--date", default=None, help="기준일 YYYY-MM-DD (기본: 오늘, Asia/Seoul)")
    args = ap.parse_args(argv)
    now = datetime.datetime.now(ZoneInfo("Asia/Seoul"))
    today = d(args.date) if args.date else now.date()

    rows = load_ledger()
    for r in rows:
        r["grow"] = grow(r)  # data.json 전용 파생 필드. 장부 파일은 건드리지 않는다
    briefs = load_briefs()
    data = {
        "generated_at": now.replace(microsecond=0).isoformat(),
        "today": today.isoformat(),
        "briefs": briefs,
        "ledger": rows,
        "trend": {"w30": window(rows, today, 30), "w90": window(rows, today, 90), "buckets": buckets(rows, today)},
        "framework": {
            "axes_md": (ROOT / "framework/axes.md").read_text(encoding="utf-8"),
            "sector_map": (ROOT / "framework/sector_map.yaml").read_text(encoding="utf-8"),
        },
        "raw": load_raw(),
        "axes": list(AXES),
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.copyfile(SITE / "index.html", OUT / "index.html")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    print(f"built site/out: briefs {len(briefs)}, ledger {len(rows)}, today {today}, "
          f"30d {data['trend']['w30']['total']} / 90d {data['trend']['w90']['total']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
