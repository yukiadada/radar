#!/usr/bin/env python3
"""섹터 보드와 관심 테마 계산. site/build.py 와 /trend 스크립트가 같은 함수를 쓴다.

섹터 보드: 장부(4축 시그널 + 기업 관찰)의 방향을 섹터(테마)·티커별로 합산한다.
  점수 = Σ 방향(+1/-1/±0) × 가중치. 4축 시그널의 가중치 = impact × horizon(분기 1, 1년 2, 다년 3), 옛 줄은 1.
  기업 관찰 행은 구조적 1, 미확정 0.5 로 세고, 그 티커가 속한 테마에 얹는다.
  점수는 "유리·불리 근거가 얼마나 쌓였는가"이지 수익률 예측이 아니다.
관심 테마: 수집 헤드라인(raw/*/*.json 의 title)에서 sector_map 의 keywords 가 나온 건수. 같은 제목은 하루에 한 번만 센다.
  기업 검색어 소스(gnews_co_*)는 그 기업 테마를 부풀리므로 뺀다. 남는 소스도 4축 검색어라 편향이 있다. 절대량보다 비중과 주간 변화를 본다.
"""
from __future__ import annotations

import collections
import datetime
import glob
import json
import re
from pathlib import Path

from config import AXES, ROOT, load_sector_map, theme_keywords

DIRV = {"+": 1, "-": -1, "±": 0}
HW = {"분기": 1, "1년": 2, "다년": 3}
GROW = re.compile(r"^(?:\[충돌:[^\]]*\]\s*)?(커짐|작아짐|유보)")


def d(s: str) -> datetime.date:
    return datetime.date.fromisoformat(s)


def grow(r: dict) -> str:
    m = GROW.match(r.get("note", ""))
    return m.group(1) if m else "미표기"


def weight(r: dict) -> int:
    imp = r.get("impact")
    return (imp if isinstance(imp, int) and not isinstance(imp, bool) else 1) * HW.get(r.get("horizon"), 1)


def in_window(rows: list[dict], today: datetime.date, days: int) -> tuple[list[dict], dict]:
    """최근 days 일 창: cut < date <= today. from 은 cut+1 (포함), to 는 today (포함)."""
    cut = today - datetime.timedelta(days=days)
    w = [r for r in rows if cut < d(r["date"]) <= today]
    return w, {"days": days, "from": (cut + datetime.timedelta(days=1)).isoformat(), "to": today.isoformat()}


def short_fact(s: str, limit: int = 110) -> str:
    """팩트의 첫 문장. 한국어 '다.' 또는 영문 '. ' 에서 자른다. 너무 길면 limit 에서 자른다."""
    s = " ".join(s.split())
    m = re.search(r"(다\.|\. )(?=\s|$)", s)
    first = s[: m.end()].rstrip() if m and m.end() <= limit + 30 else s
    return first if len(first) <= limit + 30 else first[:limit].rstrip() + "…"


def sector_board(signals: list[dict], crows: list[dict], today: datetime.date, days: int, themes=None) -> dict:
    themes = themes or load_sector_map()
    of_ticker: dict[str, list[str]] = collections.defaultdict(list)
    for th, (_, ts) in themes.items():
        for t in ts:
            of_ticker[t].append(th)
    board = {th: {"axis": ax, "theme": th, "tickers": list(ts), "score": 0.0, "up": 0, "down": 0, "both": 0, "n": 0, "structural": 0,
                  "recent": [], "per_ticker": {t: 0.0 for t in ts}} for th, (ax, ts) in themes.items()}
    tk: dict[str, dict] = {}
    for t, ths in of_ticker.items():
        tk[t] = {"ticker": t, "themes": ths, "axis": themes[ths[0]][0], "score": 0.0, "up": 0, "down": 0, "both": 0, "n": 0, "last": ""}

    def bump(b: dict, v: float, dirc: str, r: dict, src: str, wt: float) -> None:
        b["score"] += v
        b["n"] += 1
        b["structural"] += 1 if r.get("structural") is True else 0
        b["up" if dirc == "+" else "down" if dirc == "-" else "both"] += 1
        b["recent"].append({"date": r["date"], "fact": short_fact(r["fact"]), "dir": dirc, "structural": r.get("structural") is True,
                            "source": r.get("source", ""), "src": src, "weight": wt, "line": r.get("line"),
                            "company": r.get("company"), "note": short_fact(r.get("note", ""), 90)})

    def bump_t(t: str, v: float, dirc: str, date: str) -> None:
        x = tk.get(t)
        if not x:
            return
        x["score"] += v
        x["n"] += 1
        x["up" if dirc == "+" else "down" if dirc == "-" else "both"] += 1
        x["last"] = max(x["last"], date)

    w, span = in_window(signals, today, days)
    for r in w:
        b = board.get(r.get("theme"))
        dirc = r.get("direction", "±")
        wt = float(weight(r))
        v = DIRV.get(dirc, 0) * wt
        if b:
            bump(b, v, dirc, r, "signals", wt)
        for t in dict.fromkeys(r.get("sectors", [])):
            if b and t in b["per_ticker"]:
                b["per_ticker"][t] += v
            bump_t(t, v, dirc, r["date"])
    cw, _ = in_window(crows, today, days)
    for r in cw:
        dirc = r.get("direction", "±")
        wt = 1.0 if r.get("structural") is True else 0.5
        v = DIRV.get(dirc, 0) * wt
        for t in dict.fromkeys(r.get("tickers", [])):
            for th in of_ticker.get(t, []):
                bump(board[th], v, dirc, r, "companies", wt)
                board[th]["per_ticker"][t] += v
            bump_t(t, v, dirc, r["date"])
    for b in board.values():
        b["recent"] = sorted(b["recent"], key=lambda x: (x["date"], x["line"] or 0), reverse=True)[:3]
        b["score"] = round(b["score"], 1)
        b["per_ticker"] = {t: round(v, 1) for t, v in b["per_ticker"].items()}
        b["group"] = "none" if b["n"] == 0 else "mixed" if (b["up"] and b["down"]) or (b["score"] == 0) else "up" if b["score"] > 0 else "down"
    order = lambda b: (-abs(b["score"]), -b["n"], AXES.index(b["axis"]) if b["axis"] in AXES else 99, b["theme"])
    active = sorted((b for b in board.values() if b["n"]), key=order)
    none = [{"axis": b["axis"], "theme": b["theme"], "tickers": b["tickers"]} for b in board.values() if not b["n"]]
    none.sort(key=lambda b: (AXES.index(b["axis"]) if b["axis"] in AXES else 99, b["theme"]))
    tickers = sorted((x for x in tk.values() if x["n"]), key=lambda x: (-abs(x["score"]), -x["n"], x["ticker"]))
    for x in tickers:
        x["score"] = round(x["score"], 1)
    return {**span, "themes": active, "none": none, "tickers": tickers,
            "counts": {"up": sum(1 for b in active if b["group"] == "up"), "down": sum(1 for b in active if b["group"] == "down"),
                       "mixed": sum(1 for b in active if b["group"] == "mixed"), "none": len(none)}}


def _title_key(t: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]", "", t.lower().split(" - ")[0])


def attention(today: datetime.date, days: int = 14, raw_dir: Path = ROOT / "raw", keywords=None, themes=None, exclude_prefix: str = "gnews_co_") -> dict:
    keywords = keywords if keywords is not None else theme_keywords()
    themes = themes or load_sector_map()
    regs = {th: [re.compile(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", re.I) for k in kws] for th, kws in keywords.items() if kws}
    dates = [(today - datetime.timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    counts = {dt: collections.Counter() for dt in dates}
    total = collections.Counter()
    present = []
    for dt in dates:
        files = sorted(f for f in glob.glob(str(raw_dir / dt / "*.json")) if not (exclude_prefix and Path(f).name.startswith(exclude_prefix)))
        if not files:
            continue
        present.append(dt)
        seen: set[str] = set()
        for f in files:
            try:
                items = json.loads(Path(f).read_text(encoding="utf-8")).get("items", [])
            except Exception:
                continue
            for it in items:
                title = it.get("title") or ""
                key = _title_key(title)
                if not key or key in seen:
                    continue
                seen.add(key)
                total[dt] += 1
                for th, rs in regs.items():
                    if any(r.search(title) for r in rs):
                        counts[dt][th] += 1
    last7, prev7 = dates[-7:], dates[-14:-7]
    out = []
    for th, (ax, _) in themes.items():
        if th not in regs:
            continue
        n7 = sum(counts[dt][th] for dt in last7)
        p7 = sum(counts[dt][th] for dt in prev7)
        h7, hp = sum(total[dt] for dt in last7), sum(total[dt] for dt in prev7)
        share7 = round(100 * n7 / h7, 1) if h7 else 0.0
        sharep = round(100 * p7 / hp, 1) if hp else 0.0
        out.append({"axis": ax, "theme": th, "n7": n7, "prev7": p7, "share7": share7, "share_prev7": sharep, "delta_pp": round(share7 - sharep, 1),
                    "series": [counts[dt][th] for dt in dates]})
    out.sort(key=lambda x: (-x["n7"], x["theme"]))
    return {"dates": dates, "present": present, "headlines7": sum(total[dt] for dt in last7), "headlines_prev7": sum(total[dt] for dt in prev7),
            "days_present7": sum(1 for dt in last7 if dt in present), "days_present_prev7": sum(1 for dt in prev7 if dt in present),
            "comparable": sum(1 for dt in prev7 if dt in present) >= 4, "themes": out}
