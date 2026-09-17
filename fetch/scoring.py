#!/usr/bin/env python3
"""섹터 정렬(3축) 점수와 추이, 관심 집계. site/build.py, fetch/ledger.py, /trend 가 같은 함수를 쓴다.

정렬 점수 (framework/axes.md "3축 정렬"):
  시그널 가중치 w = impact(1~3) × horizon(분기 1, 1년 2, 다년 3). 옛 줄에 필드가 없으면 1.
  섹터의 축 점수 n = clamp(Σ 방향(+1/−1/±0) × w ÷ K, −1, +1), K = 6.
  정렬 % = 50 + 50 × (n기술 + n사회 + n정책) ÷ 3. 창 안에 시그널이 없으면 None.
  정렬 상태 = 밀어주는 축(n>0)·막는 축(n<0) 수로 aligned3 / aligned2 / aligned1 / mixed(둘 다) / neutral(신호는 있는데 축 점수 0) / headwind / none.
  방향(내러티브)의 축 점수 = 신호 있는 소속 섹터의 축 점수 평균.
  추이(series) = 날마다 그날을 기준일로 같은 창을 다시 계산한 값.
관심(attention): 수집 헤드라인(raw/*/*.json 의 title)에서 sector_map 의 keywords 가 나온 건수. 같은 제목은 하루에 한 번만 센다.
  검색어 때문에 편향이 있으니 절대량보다 순위와 주간 변화를 본다.
"""
from __future__ import annotations

import collections
import datetime
import glob
import json
import re
from pathlib import Path

from config import AXES, ROOT, directions, load_sector_map

DIRV = {"+": 1, "-": -1, "±": 0}
HW = {"분기": 1, "1년": 2, "다년": 3}
K = 6.0
LABELS = {"aligned3": "3축 정렬", "aligned2": "2축 정렬", "aligned1": "1축", "mixed": "엇갈림", "neutral": "양쪽", "headwind": "역풍", "none": "신호 없음"}


def d(s: str) -> datetime.date:
    return datetime.date.fromisoformat(s)


def is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def weight(r: dict) -> int:
    imp = r.get("impact")
    return (imp if is_int(imp) and 1 <= imp <= 3 else 1) * HW.get(r.get("horizon"), 1)


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


def clamp(x: float) -> float:
    return max(-1.0, min(1.0, x))


def score_of(nets: dict[str, float]) -> int:
    return int(round(50 + 50 * sum(nets[a] for a in AXES) / len(AXES)))


def label_of(nets: dict[str, float], n: int) -> str:
    if n == 0:
        return "none"
    push = sum(1 for a in AXES if nets[a] > 0)
    block = sum(1 for a in AXES if nets[a] < 0)
    if push and block:
        return "mixed"
    if block:
        return "headwind"
    return {3: "aligned3", 2: "aligned2", 1: "aligned1"}.get(push, "neutral")   # 신호는 있는데 축 점수가 모두 0 (± 만 있거나 상쇄)


def _cell() -> dict:
    return {"raw": 0.0, "n": 0, "up": 0, "down": 0, "both": 0}


def _tally(w: list[dict], smap: dict) -> dict[str, dict[str, dict]]:
    """창 안 행을 섹터×축으로 모은다. sector_map 에 없는 섹터·축은 무시한다."""
    cells = {s: {a: _cell() for a in AXES} for s in smap}
    for r in w:
        s, a = r.get("sector"), r.get("axis")
        if s not in cells or a not in AXES:
            continue
        c = cells[s][a]
        dirc = r.get("direction", "±")
        c["raw"] += DIRV.get(dirc, 0) * weight(r)
        c["n"] += 1
        c["up" if dirc == "+" else "down" if dirc == "-" else "both"] += 1
    return cells


def _nets(cells_s: dict[str, dict]) -> dict[str, float]:
    return {a: clamp(cells_s[a]["raw"] / K) for a in AXES}


def _direction_nets(active: list[dict[str, float]]) -> dict[str, float]:
    return {a: (sum(x[a] for x in active) / len(active)) if active else 0.0 for a in AXES}


def alignment(rows: list[dict], today: datetime.date, days: int, smap: dict | None = None) -> dict:
    """섹터·방향별 정렬 점수. 섹터는 sector_map 순서. 정렬은 화면(JS)에서 한다."""
    smap = smap or load_sector_map()
    w, span = in_window(rows, today, days)
    cells = _tally(w, smap)
    last = collections.defaultdict(str)
    for r in w:
        if r.get("sector") in smap:
            last[r["sector"]] = max(last[r["sector"]], r["date"])
    sectors = []
    nets_by: dict[str, tuple[dict, int]] = {}
    for s, cfg in smap.items():
        nets = _nets(cells[s])
        n = sum(cells[s][a]["n"] for a in AXES)
        nets_by[s] = (nets, n)
        sectors.append({
            "sector": s, "direction": cfg["direction"], "tickers": list(cfg["tickers"]), "n": n, "last": last[s],
            "axes": {a: {"net": round(nets[a], 2), "raw": round(cells[s][a]["raw"], 1), "n": cells[s][a]["n"],
                         "up": cells[s][a]["up"], "down": cells[s][a]["down"], "both": cells[s][a]["both"]} for a in AXES},
            "score": score_of(nets) if n else None, "label": label_of(nets, n),
        })
    dirs = []
    for dname, members in directions(smap):
        active = [nets_by[s][0] for s in members if nets_by[s][1]]
        nets = _direction_nets(active)
        n = sum(nets_by[s][1] for s in members)
        dirs.append({"direction": dname, "sectors": list(members), "n": n, "active": len(active),
                     "axes": {a: round(nets[a], 2) for a in AXES},
                     "score": score_of(nets) if n else None, "label": label_of(nets, n)})
    counts = collections.Counter(x["label"] for x in sectors)
    return {**span, "total": len(w), "sectors": sectors, "directions": dirs,
            "counts": {k: counts.get(k, 0) for k in LABELS}}


def series(rows: list[dict], today: datetime.date, days: int, span_days: int = 90, smap: dict | None = None) -> dict:
    """날짜별 정렬 %. dates 는 오래된 순. 신호 없는 날은 None."""
    smap = smap or load_sector_map()
    dates = [today - datetime.timedelta(days=i) for i in range(span_days - 1, -1, -1)]
    out_s: dict[str, list] = {s: [] for s in smap}
    out_d: dict[str, list] = {dn: [] for dn, _ in directions(smap)}
    first = min((d(r["date"]) for r in rows), default=None)
    for t in dates:
        if first is None or t < first:   # 장부 시작 전은 계산할 것이 없다
            for s in out_s: out_s[s].append(None)
            for dn in out_d: out_d[dn].append(None)
            continue
        w, _ = in_window(rows, t, days)
        cells = _tally(w, smap)
        nets_by = {}
        for s in smap:
            nets = _nets(cells[s])
            n = sum(cells[s][a]["n"] for a in AXES)
            nets_by[s] = (nets, n)
            out_s[s].append(score_of(nets) if n else None)
        for dn, members in directions(smap):
            active = [nets_by[s][0] for s in members if nets_by[s][1]]
            out_d[dn].append(score_of(_direction_nets(active)) if active else None)
    return {"days": days, "dates": [x.isoformat() for x in dates], "sectors": out_s, "directions": out_d}


def delta(values: list, back: int = 7):
    """마지막 값 − back 일 전 값. 둘 중 하나라도 없으면 None."""
    if len(values) <= back or values[-1] is None or values[-1 - back] is None:
        return None
    return values[-1] - values[-1 - back]


def attach_deltas(board: dict, ser: dict, back: int = 7) -> dict:
    """board 의 섹터·방향에 series 기준 back 일 변화(delta)를 붙인다. 같은 창(days)끼리 써야 한다."""
    for x in board["sectors"]:
        x["delta"] = delta(ser["sectors"].get(x["sector"], []), back)
    for x in board["directions"]:
        x["delta"] = delta(ser["directions"].get(x["direction"], []), back)
    return board


def fmt_net(v: float) -> str:
    return "0" if abs(v) < 0.005 else f"{v:+.2f}"


def board_table(board: dict) -> list[str]:
    """브리프 "섹터 정렬" 절에 그대로 붙이는 마크다운 표. 신호 있는 섹터만, 정렬 % 높은 순."""
    rows = sorted((x for x in board["sectors"] if x["n"]), key=lambda x: (-x["score"], -x["n"], x["sector"]))
    out = ["| 섹터 | 기술 | 사회 | 정책 | 정렬 | 상태 | 7일 변화 |", "|---|---|---|---|---|---|---|"]
    for x in rows:
        dl = "–" if x.get("delta") is None else ("0p" if x["delta"] == 0 else f"{x['delta']:+d}p")
        out.append(f"| {x['sector']} | " + " | ".join(fmt_net(x["axes"][a]["net"]) for a in AXES) +
                   f" | {x['score']}% | {LABELS[x['label']]} | {dl} |")
    if not rows:
        out.append("| (신호 있는 섹터 없음) | | | | | | |")
    return out


def _title_key(t: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]", "", t.lower().split(" - ")[0])


def attention(today: datetime.date, days: int = 14, raw_dir: Path = ROOT / "raw", smap: dict | None = None,
              exclude_prefix: str = "gnews_co_") -> dict:
    """최근 days 일 수집 헤드라인에서 섹터 keywords 언급 건수. exclude_prefix 는 옛 기업 검색어 소스(gnews_co_*)를 빼기 위한 것."""
    smap = smap or load_sector_map()
    regs = {s: [re.compile(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", re.I) for k in c["keywords"]]
            for s, c in smap.items() if c["keywords"]}
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
                for s, rs in regs.items():
                    if any(r.search(title) for r in rs):
                        counts[dt][s] += 1
    last7, prev7 = dates[-7:], dates[-14:-7]
    out = []
    for s, cfg in smap.items():
        if s not in regs:
            continue
        n7 = sum(counts[dt][s] for dt in last7)
        p7 = sum(counts[dt][s] for dt in prev7)
        h7, hp = sum(total[dt] for dt in last7), sum(total[dt] for dt in prev7)
        share7 = round(100 * n7 / h7, 1) if h7 else 0.0
        sharep = round(100 * p7 / hp, 1) if hp else 0.0
        out.append({"sector": s, "direction": cfg["direction"], "n7": n7, "prev7": p7, "share7": share7, "share_prev7": sharep,
                    "delta_pp": round(share7 - sharep, 1), "series": [counts[dt][s] for dt in dates]})
    out.sort(key=lambda x: (-x["n7"], x["sector"]))
    return {"dates": dates, "present": present, "headlines7": sum(total[dt] for dt in last7), "headlines_prev7": sum(total[dt] for dt in prev7),
            "days_present7": sum(1 for dt in last7 if dt in present), "days_present_prev7": sum(1 for dt in prev7 if dt in present),
            "comparable": sum(1 for dt in prev7 if dt in present) >= 4, "sectors": out}
