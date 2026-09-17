#!/usr/bin/env python3
"""radar 웹페이지 빌드. briefs/, ledger/, framework/, raw/ 를 읽어 site/out/ 에 정적 페이지를 만든다.

  python3 site/build.py                     → site/out/index.html, site/out/data.json, site/out/briefs/<날짜>.md
  python3 site/build.py --date 2026-09-18   기준일 지정 (기본: 오늘, Asia/Seoul)

표준 라이브러리만 쓴다 (framework/*.yaml 은 fetch/config.py, 점수는 fetch/scoring.py). .github/workflows/pages.yml 이 main 에 push 될 때마다 실행해 GitHub Pages 로 올린다.
브리프 본문은 site/out/briefs/<날짜>.md 로 따로 내보내고 data.json 에는 메타만 둔다.
data.json:
  today, generated_at, axes, directions[{name, sectors}], sectors{이름: {direction, tickers, note}}, sources[{name, axis, type}]
  ledger[행 + line], board{w30, w90}(scoring.alignment + delta), series{w30, w90}(scoring.series, 90일)
  activity{w30, w90}(축별 건수·방향·상위 섹터), attention(scoring.attention), briefs[{date, structural, none_today}], raw{날짜: {소스: {count, error}}}, framework{axes_md, sector_map, sources}
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
sys.path.insert(0, str(ROOT / "fetch"))
from config import AXES, directions, load_sector_map, load_sources  # noqa: E402
from scoring import alignment, attach_deltas, attention, in_window, series  # noqa: E402

SITE = ROOT / "site"
OUT = SITE / "out"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def d(s: str) -> datetime.date:
    return datetime.date.fromisoformat(s)


def load_ledger(path: Path) -> list[dict]:
    """장부 한 줄 = JSON 하나. line(줄 번호)을 붙인다. data.json 전용 파생 필드이며 장부 파일은 건드리지 않는다."""
    rows: list[dict] = []
    if not path.exists():
        return rows
    for n, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            d(r["date"])
        except Exception as e:  # 장부는 수정 금지. 빌드만 멈춘다
            sys.exit(f"{path.name} {n}번째 줄 파싱 실패: {e}")
        r["line"] = n
        rows.append(r)
    return rows


def activity(rows: list[dict], today: datetime.date, days: int) -> dict:
    """축별 건수·방향·상위 섹터 (트렌드 표)."""
    w, span = in_window(rows, today, days)
    axes = []
    for a in AXES:
        s = [r for r in w if r.get("axis") == a]
        dc = collections.Counter(r.get("direction") for r in s)
        axes.append({"axis": a, "count": len(s), "share": round(len(s) / len(w), 3) if w else 0,
                     "dir": {"+": dc["+"], "-": dc["-"], "±": dc["±"]},
                     "avg_conf": round(sum(r["confidence"] for r in s) / len(s), 2) if s else None,
                     "sectors": collections.Counter(r.get("sector") for r in s).most_common(5),
                     "tickers": collections.Counter(t for r in s for t in dict.fromkeys(r.get("tickers", []))).most_common(5)})
    return {**span, "total": len(w), "axes": axes}


def load_briefs() -> list[dict]:
    out = []
    for p in sorted((ROOT / "briefs").glob("*.md"), reverse=True):
        if not DATE_RE.match(p.stem):
            continue
        md = p.read_text(encoding="utf-8")
        structural = 0
        for a in AXES:   # 구조적 건수는 세 축 절의 표만 센다
            sec = re.search(rf"^## {re.escape(a)}\s*$\n(.*?)(?=^## |\Z)", md, re.M | re.S)
            structural += sum(1 for l in (sec.group(1) if sec else "").split("\n") if l.startswith("|") and re.search(r"\|\s*true\s*\|", l))
        out.append({"date": p.stem, "md": md, "structural": structural, "none_today": "오늘 구조적 시그널 없음" in md})
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


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="radar 정적 페이지 빌드")
    ap.add_argument("--date", default=None, help="기준일 YYYY-MM-DD (기본: 오늘, Asia/Seoul)")
    args = ap.parse_args(argv)
    now = datetime.datetime.now(ZoneInfo("Asia/Seoul"))
    today = d(args.date) if args.date else now.date()

    rows = load_ledger(ROOT / "ledger/signals.jsonl")
    smap = load_sector_map()
    try:
        sources = [{"name": s["name"], "axis": s["axis"], "type": s["type"]} for s in load_sources()]
    except ValueError as e:
        print(f"경고 sources.yaml: {e}", file=sys.stderr)
        sources = []
    briefs = load_briefs()
    ser = {f"w{n}": series(rows, today, n, 90, smap) for n in (30, 90)}
    board = {f"w{n}": attach_deltas(alignment(rows, today, n, smap), ser[f"w{n}"]) for n in (30, 90)}
    data = {
        "generated_at": now.replace(microsecond=0).isoformat(),
        "today": today.isoformat(),
        "axes": list(AXES),
        "directions": [{"name": dn, "sectors": members} for dn, members in directions(smap)],
        "sectors": {s: {"direction": c["direction"], "tickers": c["tickers"], "note": c["note"]} for s, c in smap.items()},
        "sources": sources,
        "ledger": rows,
        "board": board,
        "series": ser,
        "activity": {f"w{n}": activity(rows, today, n) for n in (30, 90)},
        "attention": attention(today, 14, smap=smap),
        "briefs": [{k: v for k, v in b.items() if k != "md"} for b in briefs],
        "raw": load_raw(),
        "framework": {
            "axes_md": read(ROOT / "framework/axes.md"),
            "sector_map": read(ROOT / "framework/sector_map.yaml"),
            "sources": read(ROOT / "framework/sources.yaml"),
        },
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "briefs").mkdir(exist_ok=True)
    for b in briefs:
        (OUT / "briefs" / f"{b['date']}.md").write_text(b["md"], encoding="utf-8")
    (OUT / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.copyfile(SITE / "index.html", OUT / "index.html")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    b30 = board["w30"]
    print(f"built site/out: briefs {len(briefs)}, ledger {len(rows)}, today {today}, 30d {b30['total']} / 90d {board['w90']['total']}, "
          f"sectors {b30['counts']}, attention days {data['attention']['days_present7']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
