#!/usr/bin/env python3
"""radar 웹페이지 빌드. briefs/, ledger/, framework/, raw/ 를 읽어 site/out/ 에 정적 페이지를 만든다.

  python3 site/build.py                     → site/out/index.html, site/out/data.json
  python3 site/build.py --date 2026-09-10   기준일 지정 (기본: 오늘, Asia/Seoul)

표준 라이브러리만 쓴다 (framework/*.yaml 은 fetch/config.py 로 읽는다). .github/workflows/pages.yml 이 main 에 push 될 때마다 실행해 GitHub Pages 로 올린다.
브리프 본문은 site/out/briefs/<날짜>.md 로 따로 내보내고 data.json 에는 메타만 둔다 (페이지가 보는 브리프만 받도록).
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
sys.path.insert(0, str(ROOT / "fetch"))
from config import AXES, load_companies, load_sector_map, theme_keywords  # noqa: E402
from scoring import attention, grow, in_window, sector_board, weight  # noqa: E402

SITE = ROOT / "site"
OUT = SITE / "out"
GROW = re.compile(r"^(?:\[충돌:[^\]]*\]\s*)?(커짐|작아짐|유보)")
CONF = re.compile(r"\[충돌:\s*(\S+)\s+vs\s+(\S+)\s*\]", re.I)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
THESIS_RE = re.compile(r"^## (T\d+)\s+(.+?)\s*$", re.M)
THESIS_TAG = re.compile(r"^(T\d+)([+-])$")


def load_theses() -> list[dict]:
    p = ROOT / "framework/thesis.md"
    if not p.exists():
        return []
    md = p.read_text(encoding="utf-8")
    heads = list(THESIS_RE.finditer(md))
    out = []
    for i, m in enumerate(heads):
        block = md[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(md)]
        st = re.search(r"^- 상태:\s*(.+?)\s*$", block, re.M)
        chk = re.search(r"^- 마지막 검토:\s*(.+?)\s*$", block, re.M)
        out.append({"id": m.group(1), "title": m.group(2), "status": st.group(1) if st else "미표기",
                    "reviewed": chk.group(1) if chk else ""})
    return out


def thesis_counts(w: list[dict]) -> list[dict]:
    ev: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    for r in w:
        for x in r.get("thesis") or []:
            m = THESIS_TAG.match(str(x))
            if m:
                ev[m.group(1)][0 if m.group(2) == "+" else 1] += 1
    return [{"id": k, "confirm": v[0], "refute": v[1]} for k, v in sorted(ev.items(), key=lambda x: int(x[0][1:]))]


def d(s: str) -> datetime.date:
    return datetime.date.fromisoformat(s)


def load_jsonl(path: Path) -> list[dict]:
    """장부 한 줄 = JSON 하나. line(줄 번호)과 grow(note 첫 단어)를 붙인다. data.json 전용 파생 필드이며 장부 파일은 건드리지 않는다."""
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
        r["grow"] = grow(r)
        rows.append(r)
    return rows


def window(rows: list[dict], today: datetime.date, days: int) -> dict:
    w, span = in_window(rows, today, days)
    axes = []
    for a in AXES:
        s = [r for r in w if r["axis"] == a]
        g = collections.Counter(grow(r) for r in s)
        dc = collections.Counter(r["direction"] for r in s)
        axes.append({
            "axis": a, "count": len(s), "share": round(len(s) / len(w), 3) if w else 0,
            "grow": g["커짐"], "shrink": g["작아짐"], "hold": g["유보"], "untagged": g["미표기"],
            "wgrow": sum(weight(r) for r in s if grow(r) == "커짐"), "wshrink": sum(weight(r) for r in s if grow(r) == "작아짐"),
            "unweighted": sum(1 for r in s if "horizon" not in r),
            "dir": {"+": dc["+"], "-": dc["-"], "±": dc["±"]},
            "avg_conf": round(sum(r["confidence"] for r in s) / len(s), 2) if s else None,
            "themes": collections.Counter(r["theme"] for r in s).most_common(3),
            "sectors": collections.Counter(t for r in s for t in r["sectors"]).most_common(5),
        })
    hits = [(r, pair(m)) for r in w if (m := CONF.search(r.get("note", "")))]
    pairs = collections.Counter(p for _, p in hits)
    return {
        **span,
        "total": len(w), "axes": axes,
        "tickers": tickers(w),
        "thesis": thesis_counts(w),
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


def companies_cfg() -> list[dict]:
    """framework/companies.yaml. 항목 오류는 경고만 하고 그 기업은 뺀다."""
    try:
        cfg = load_companies()
    except ValueError as e:
        print(f"경고 companies.yaml: {e}", file=sys.stderr)
        return []
    out = []
    for c in cfg:
        if c["error"]:
            print(f"경고 companies.yaml {c['name']}: {c['error']} (사이트에서 제외)", file=sys.stderr)
        else:
            out.append({k: c[k] for k in ("name", "tickers", "note")})
    return out


def companies_data(cfg: list[dict], rows: list[dict], today: datetime.date) -> dict:
    """기업 × 축 매트릭스 (30/90일). count 는 전체, structural 은 true 만, grow/shrink 는 note 첫 단어.
    설정에 없는 기업의 행은 orphans 로 따로 세고 화면 합계에서 뺀다."""
    names = {c["name"] for c in cfg}
    orphans = sorted({r.get("company", "?") for r in rows if r.get("company") not in names})
    if orphans:
        print(f"경고 companies.jsonl: companies.yaml 에 없는 기업 {orphans} 의 행은 매트릭스에 나오지 않음", file=sys.stderr)

    def win(days: int) -> dict:
        w, span = in_window(rows, today, days)
        out = []
        for c in cfg:
            cr = [r for r in w if r.get("company") == c["name"]]
            cells = []
            for a in AXES:
                s = [r for r in cr if r.get("axis") == a]
                g = collections.Counter(grow(r) for r in s)
                cells.append({"axis": a, "count": len(s), "structural": sum(1 for r in s if r.get("structural") is True),
                              "grow": g["커짐"], "shrink": g["작아짐"], "hold": g["유보"]})
            dc = collections.Counter(r.get("direction") for r in cr)
            out.append({"name": c["name"], "count": len(cr), "structural": sum(1 for r in cr if r.get("structural") is True),
                        "dir": {"+": dc["+"], "-": dc["-"], "±": dc["±"]}, "axes": cells})
        return {**span, "total": sum(c["count"] for c in out), "orphans": sum(1 for r in w if r.get("company") not in names), "companies": out}
    return {"config": cfg, "rows": rows, "orphans": orphans, "w30": win(30), "w90": win(90)}


def load_briefs() -> list[dict]:
    out = []
    for p in sorted((ROOT / "briefs").glob("*.md"), reverse=True):
        if not DATE_RE.match(p.stem):
            continue
        md = p.read_text(encoding="utf-8")
        # 구조적 건수는 "오늘의 축 시그널" 섹션의 표만 센다. "기업 관찰" 표에도 구조적 열이 있어 전체를 세면 부풀려진다
        sec = re.search(r"^## 오늘의 축 시그널[^\n]*\n(.*?)(?=^## |\Z)", md, re.M | re.S)
        structural = sum(1 for l in (sec.group(1) if sec else "").split("\n") if l.startswith("|") and re.search(r"\|\s*true\s*\|", l))
        m = re.search(r"^## (?:3~4년 논지 변화\?|논지 점검)[^\n]*\n+([^\n]+)", md, re.M)
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

    rows = load_jsonl(ROOT / "ledger/signals.jsonl")
    crows = load_jsonl(ROOT / "ledger/companies.jsonl")
    try:
        themes = load_sector_map()
    except ValueError as e:
        print(f"경고 sector_map.yaml: {e}. 섹터 보드·관심 테마 생략", file=sys.stderr)
        themes = {}
    briefs = load_briefs()
    data = {
        "generated_at": now.replace(microsecond=0).isoformat(),
        "today": today.isoformat(),
        "briefs": [{k: v for k, v in b.items() if k != "md"} for b in briefs],
        "ledger": rows,
        "trend": {"w30": window(rows, today, 30), "w90": window(rows, today, 90), "buckets": buckets(rows, today)},
        "framework": {
            "axes_md": (ROOT / "framework/axes.md").read_text(encoding="utf-8"),
            "sector_map": (ROOT / "framework/sector_map.yaml").read_text(encoding="utf-8"),
            "thesis_md": (ROOT / "framework/thesis.md").read_text(encoding="utf-8") if (ROOT / "framework/thesis.md").exists() else "",
        },
        "raw": load_raw(),
        "axes": list(AXES),
        "theses": load_theses(),
        "companies": companies_data(companies_cfg(), crows, today),
        "sectors": {"w30": sector_board(rows, crows, today, 30, themes), "w90": sector_board(rows, crows, today, 90, themes)} if themes else None,
        "attention": attention(today, 14, themes=themes, keywords=theme_keywords()) if themes else None,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "briefs").mkdir(exist_ok=True)
    for b in briefs:
        (OUT / "briefs" / f"{b['date']}.md").write_text(b["md"], encoding="utf-8")
    (OUT / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.copyfile(SITE / "index.html", OUT / "index.html")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    att = data["attention"]
    print(f"built site/out: briefs {len(briefs)}, ledger {len(rows)}, companies {len(crows)}, today {today}, "
          f"30d {data['trend']['w30']['total']} / 90d {data['trend']['w90']['total']}, "
          f"sectors up/down/mixed {data['sectors']['w30']['counts'] if data['sectors'] else '-'}, attention days {att['days_present7'] if att else 0}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
