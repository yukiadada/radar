#!/usr/bin/env python3
"""radar 웹페이지 빌드. briefs/, ledger/, framework/, raw/ 를 읽어 site/out/ 에 정적 페이지를 만든다.

  python3 site/build.py                     → site/out/index.html, data.json, briefs/<날짜>.md, framework/*
  python3 site/build.py --date 2026-09-18   기준일 지정 (기본: 오늘, Asia/Seoul)

표준 라이브러리만 쓴다 (framework/*.yaml 은 fetch/config.py, 점수는 fetch/scoring.py, 장부 읽기는 fetch/ledger.py). .github/workflows/pages.yml 이 main 에 push 될 때마다 실행해 GitHub Pages 로 올린다.
자료 문제(깨진 장부 줄, sector_map 오류, 맵에 없는 섹터, 브리프 형식)로는 빌드를 멈추지 않는다. data.json 의 warnings 에 적고 사이트가 배너로 보여준다. 사이트가 조용히 멈춰 있는 것보다 낫다.
data.json:
  today, generated_at, first_date, axes, labels, params, sectors{이름: {direction, tickers, note}}
  ledger[행 + line], board{w30, w90}(scoring.alignment + delta + orphans), series{w30, w90}(scoring.series)
  activity{w30, w90}(축별 건수·방향·상위 섹터), attention(scoring.attention), briefs[{date, structural, none_today, signals, md(최신 것만)}]
  raw{날짜: {소스: {count, error, current, backfill}}}, market{장부 줄: 시장 반응(market.reaction)}, market_meta{source, asof, updated_at} | null,
  direction_brief(briefs/direction.md 본문. 홈 "지금 세상의 방향" 서술) | null, warnings[]
  브리프 signals 에는 장부와 (날짜, 출처 URL, 섹터) 가 같은 행의 line 을 붙인다 (카드에 시장 반응을 보이기 위해).
브리프 카드는 여기서 마크다운을 구조화(parse_brief)해 signals 로 준다. 사이트는 나머지 절만 마크다운으로 그린다.
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
from config import AXES, load_sector_map, load_sources  # noqa: E402
from ledger import load_existing  # noqa: E402
from scoring import LABELS, PARAMS, alignment, attach_deltas, attention, in_window, raw_scan, series  # noqa: E402
from market import SOURCE as PRICE_SOURCE, asof as price_asof, load_prices, reactions  # noqa: E402

SITE = ROOT / "site"
OUT = SITE / "out"
URL_IN = re.compile(r"\((https?://[^)\s]+)\)")   # 브리프 팩트 셀의 ([출처](URL)) 에서 URL
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EASY_KEYS = ("무슨 일", "왜 중요", "누가 이득·손해")


def d(s: str) -> datetime.date:
    return datetime.date.fromisoformat(s)


def activity(rows: list[dict], today: datetime.date, days: int) -> dict:
    """축별 건수·방향·상위 섹터 (추이 표)."""
    w, span = in_window(rows, today, days)
    axes = []
    for a in AXES:
        s = [r for r in w if r.get("axis") == a]
        dc = collections.Counter(r.get("direction") for r in s)
        confs = [r["confidence"] for r in s if isinstance(r.get("confidence"), (int, float))]
        axes.append({"axis": a, "count": len(s), "share": round(len(s) / len(w), 3) if w else 0,
                     "dir": {"+": dc["+"], "-": dc["-"], "±": dc["±"]},
                     "avg_conf": round(sum(confs) / len(confs), 2) if confs else None,
                     "sectors": collections.Counter(r.get("sector") for r in s).most_common(5),
                     "tickers": collections.Counter(t for r in s for t in dict.fromkeys(r.get("tickers") or [])).most_common(5)})
    return {**span, "total": len(w), "axes": axes}


# ---------------------------------------------------------------- 브리프 구조화
def _sections(md: str) -> list[tuple[str, str]]:
    parts = re.split(r"^## ", md, flags=re.M)[1:]
    out = []
    for p in parts:
        nl = p.find("\n")
        out.append((p[:nl].strip() if nl >= 0 else p.strip(), p[nl + 1:] if nl >= 0 else ""))
    return out


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _easy(body: str) -> list[dict]:
    items, cur = [], None
    for raw in body.split("\n"):
        m = re.match(r"^- \*\*(.+?)\*\*\s*$", raw)
        if m:
            cur = {"name": m.group(1), "parts": []}
            items.append(cur)
            continue
        m = re.match(r"^\s+- (무슨 일|왜 중요|누가 이득·손해)\s*[:：]\s*(.+)$", raw)
        if m and cur:
            cur["parts"].append([m.group(1), m.group(2)])
    return items


def parse_brief(md: str) -> dict:
    """세 축 절의 표를 signals 로. 표의 행 i 는 "쉬운 말로" i 번째 항목(기술→사회→정책 순서로 이어 붙임)과 같은 시그널이다 (brief.md 규칙).
    셀 안의 '|' 는 팩트에 합쳐 넣는다. 형식 문제는 warnings 에 적고 그 행은 건너뛴다 (쉬운 말로 번호는 건너뛴 행만큼 같이 넘긴다)."""
    secs = _sections(md)
    titles = {t: b for t, b in secs}
    easy = _easy(next((b for t, b in secs if t.startswith("쉬운 말로")), ""))
    signals, warnings, k = [], [], 0
    for a in AXES:
        if a not in titles:
            warnings.append(f"'## {a}' 절 없음")
            continue
        body = titles[a]
        lines = [l for l in body.split("\n") if l.strip().startswith("|")]
        interp = [l[2:].strip() for l in body.split("\n") if re.match(r"^- 해석", l)]
        rows = [l for l in lines[2:]] if len(lines) >= 3 else []
        for i, line in enumerate(rows):
            c = _cells(line)
            if len(c) < 5:
                warnings.append(f"{a} 표 {i + 1}행: 칸이 {len(c)}개 (5개 필요). 카드에서 뺌")
                k += 1
                continue
            fact, st, sec, dirc, conf = " | ".join(c[:-4]), c[-4], c[-3], c[-2], c[-1]
            sector, _, tk = sec.partition("·")
            structural = True if st.lower() == "true" else False if st.lower() == "false" else None
            if structural is None:
                warnings.append(f"{a} 표 {i + 1}행: 구조적 칸이 true/false 가 아님 ({st!r})")
            signals.append({"axis": a, "fact": fact, "structural": structural, "sector": sector.strip(),
                            "tickers": [t.strip() for t in tk.split(",") if t.strip()], "direction": dirc, "confidence": conf,
                            "interp": interp[i] if i < len(interp) else "", "easy": easy[k] if k < len(easy) else None})
            k += 1
    if easy and len(easy) != k:
        warnings.append(f"쉬운 말로 항목 {len(easy)}개, 시그널 표 행 {k}개. 카드 제목이 어긋날 수 있음")
    return {"signals": signals, "structural": sum(1 for s in signals if s["structural"] is True),
            "none_today": "오늘 구조적 시그널 없음" in md, "warnings": warnings}


def load_briefs(warnings: list[str]) -> list[dict]:
    out = []
    for p in sorted((ROOT / "briefs").glob("*.md"), reverse=True):
        if not DATE_RE.match(p.stem):
            continue
        md = p.read_text(encoding="utf-8")
        b = parse_brief(md)
        warnings.extend(f"briefs/{p.stem}.md: {w}" for w in b.pop("warnings"))
        out.append({"date": p.stem, "md": md, **b})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="radar 정적 페이지 빌드")
    ap.add_argument("--date", default=None, help="기준일 YYYY-MM-DD (기본: 오늘, Asia/Seoul)")
    args = ap.parse_args(argv)
    now = datetime.datetime.now(ZoneInfo("Asia/Seoul"))
    today = d(args.date) if args.date else now.date()
    warnings: list[str] = []

    rows, _ = load_existing(ROOT / "ledger/signals.jsonl", warnings)
    try:
        smap = load_sector_map()
    except ValueError as e:
        warnings.append(f"framework/sector_map.yaml: {e}. 섹터·정렬 없이 빌드함")
        smap = {}
    try:
        sources = load_sources()
        warnings.extend(f"framework/sources.yaml {s['name']}: {s['error']}" for s in sources if s["error"])
        current = {s["name"] for s in sources if not s["error"]}
    except (ValueError, OSError) as e:
        warnings.append(f"framework/sources.yaml: {e}")
        current = None
    briefs = load_briefs(warnings)
    prices = load_prices()
    market = reactions(rows, prices)
    market_meta = None
    if prices:
        pa = price_asof(prices)
        market_meta = {"source": PRICE_SOURCE, "asof": pa, "updated_at": prices.get("updated_at"), "n": len(market)}
        if pa and (today - d(pa)).days > 5:
            warnings.append(f"가격 자료(prices/prices.json)가 {pa} 까지라 시장 반응이 오래됐다. fetch.yml 의 market.py --update 를 확인")
    by_key = {(r["date"], r["source"], r["sector"]): r["line"] for r in rows}
    for b in briefs:
        for s in b["signals"]:
            m = URL_IN.search(s["fact"])
            s["line"] = by_key.get((b["date"], m.group(1), s["sector"])) if m else None
    ser = {f"w{n}": series(rows, today, n, PARAMS["span_days"], smap) for n in PARAMS["windows"]}
    board = {f"w{n}": attach_deltas(alignment(rows, today, n, smap), ser[f"w{n}"]) for n in PARAMS["windows"]}
    for n in PARAMS["windows"]:
        b = board[f"w{n}"]
        if b["orphan_total"]:
            warnings.append(f"최근 {n}일 장부 {b['orphan_total']}건이 sector_map 에 없는 섹터라 정렬에서 빠짐: " + ", ".join(f"{k} {v}건" for k, v in b["orphans"].items()))
            break
    scan = raw_scan(today, 14, current=current)
    data = {
        "generated_at": now.replace(microsecond=0).isoformat(),
        "today": today.isoformat(),
        "first_date": min((r["date"] for r in rows), default=None),
        "axes": list(AXES),
        "labels": LABELS,
        "params": {"K": PARAMS["K"], "HW": PARAMS["HW"], "delta_days": PARAMS["delta_days"], "windows": PARAMS["windows"]},
        "sectors": {s: {"direction": c["direction"], "tickers": c["tickers"], "note": c["note"]} for s, c in smap.items()},
        "ledger": rows,
        "board": board,
        "series": ser,
        "activity": {f"w{n}": activity(rows, today, n) for n in PARAMS["windows"]},
        "attention": attention(scan, smap),
        "briefs": [{k: v for k, v in b.items() if k != "md" or b is briefs[0]} for b in briefs],   # 본문은 최신 브리프만 싣는다 (홈 첫 화면용)
        "direction_brief": (ROOT / "briefs/direction.md").read_text(encoding="utf-8") if (ROOT / "briefs/direction.md").exists() else None,   # 홈 "지금 세상의 방향" 서술 (쉬운 말). 날짜는 본문 제목에
        "raw": scan["days"],
        "market": market,
        "market_meta": market_meta,
        "warnings": warnings,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "briefs").mkdir(exist_ok=True)
    (OUT / "framework").mkdir(exist_ok=True)
    for b in briefs:
        (OUT / "briefs" / f"{b['date']}.md").write_text(b["md"], encoding="utf-8")
    for name in ("axes.md", "sector_map.yaml", "sources.yaml"):
        src = ROOT / "framework" / name
        if src.exists():
            shutil.copyfile(src, OUT / "framework" / name)
    (OUT / "data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    shutil.copyfile(SITE / "index.html", OUT / "index.html")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    for w in warnings:
        print(f"경고 {w}", file=sys.stderr)
    b30 = board["w30"]
    print(f"built site/out: briefs {len(briefs)}, ledger {len(rows)}, today {today}, 30d {b30['total']} / 90d {board['w90']['total']}, "
          f"sectors {b30['counts']}, attention days {data['attention']['days_present7']}, warnings {len(warnings)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
