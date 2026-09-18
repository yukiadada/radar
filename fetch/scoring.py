#!/usr/bin/env python3
"""섹터 정렬(3축) 점수와 추이, 관심 집계. site/build.py, fetch/ledger.py, /trend, /review 가 같은 함수를 쓴다. 이 파일이 유일한 구현이다.

정렬 점수 (framework/axes.md "3축 정렬"):
  시그널 가중치 w = impact(1~3) × horizon(분기 1, 1년 2, 다년 3). 필드가 없거나 이상하면 1.
  누적(days=None, 기본): 시그널은 horizon 별 유효기간(분기 90일, 1년 365일, 다년 730일) 동안 살아 있고, 그동안 w 가 직선으로 0까지
    줄어든다 (w × (1 − 지난 일수 ÷ 유효기간)). 유효기간이 지나면 점수에서 빠진다. 이것이 "수준"이다.
  창(days=30 등): cut < date <= today 인 시그널을 줄이지 않고 그대로 센다. 30일 창은 "새로 들어온 근거"(변화)를 보는 용도.
    PARAMS["windows"] 중 장부가 (n − grace)일 이상 쌓인 것만 연다 (enabled_windows). 첫 창(30)은 항상 연다.
  섹터의 축 점수 n = clamp(Σ 방향(+1/−1/±0) × w ÷ K, −1, +1), K = PARAMS["K"].
  정렬 % = 50 + 50 × (축 점수 합 ÷ 축 수). 살아 있는(창 안) 시그널이 없으면 None.
  정렬 상태 = 밀어주는 축(n>0)·막는 축(n<0) 수로 aligned3 / aligned2 / aligned1 / mixed(둘 다) / neutral(신호는 있는데 축 점수 0) / headwind / none.
  방향(내러티브)의 축 점수 = 신호 있는 소속 섹터의 축 점수 평균.
  추이(series) = 날마다 그날을 기준일로 같은 계산을 다시 한 값. 장부 첫날 전은 만들지 않는다.
관심(attention): 수집 헤드라인(raw/*/*.json 의 title)에서 sector_map 의 keywords 가 나온 건수. 같은 제목은 하루에 한 번만 센다.
  검색어 때문에 편향이 있으니 절대량보다 순위와 주간 변화를 본다.
"""
from __future__ import annotations

import collections
import datetime
import json
import re
from pathlib import Path

from config import AXES, ROOT, directions, load_sector_map

PARAMS = {"K": 6.0, "HW": {"분기": 1, "1년": 2, "다년": 3}, "validity": {"분기": 90, "1년": 365, "다년": 730},
          "windows": [30, 90, 180, 365], "grace": 7, "span_days": 90, "delta_days": 7}
DIRV = {"+": 1, "-": -1, "±": 0}
HW = PARAMS["HW"]
K = PARAMS["K"]
VALIDITY = PARAMS["validity"]
LABELS = {"aligned3": "3축 정렬", "aligned2": "2축 정렬", "aligned1": "1축", "mixed": "엇갈림", "neutral": "양쪽", "headwind": "역풍", "none": "신호 없음"}


def d(s: str) -> datetime.date:
    return datetime.date.fromisoformat(s)


def is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def weight(r: dict) -> int:
    imp = r.get("impact")
    return (imp if is_int(imp) and 1 <= imp <= 3 else 1) * HW.get(r.get("horizon"), 1)


def validity(r: dict) -> int:
    """유효기간(일). horizon 이 없거나 이상하면 가장 짧은 분기."""
    return VALIDITY.get(r.get("horizon"), VALIDITY["분기"])


def remaining(r: dict, today: datetime.date) -> float:
    """오늘 남은 비중 0~1. 시그널 당일 1, 유효기간 끝에 0. 기준일 뒤의 행은 0."""
    age = (today - d(r["date"])).days
    v = validity(r)
    return 0.0 if age < 0 or age >= v else 1 - age / v


def live_weight(r: dict, today: datetime.date) -> float:
    return weight(r) * remaining(r, today)


def first_sentence(s: str) -> str:
    """팩트의 첫 문장. 한국어 '다.' 또는 영문 '. ' 에서 자른다. 사이트가 카드 제목으로 쓰고, ledger.py 가 길이를 검사한다."""
    s = " ".join(s.split())
    m = re.search(r"(다\.|\. )(?=\s|$)", s)
    return s[: m.end()].rstrip() if m else s


def in_window(rows: list[dict], today: datetime.date, days: int) -> tuple[list[dict], dict]:
    """최근 days 일 창: cut < date <= today. from 은 cut+1 (포함), to 는 today (포함). 행의 date 는 ISO 여야 한다 (ledger.load_existing 이 검사)."""
    cut = today - datetime.timedelta(days=days)
    w = [r for r in rows if cut < d(r["date"]) <= today]
    return w, {"mode": "window", "days": days, "from": (cut + datetime.timedelta(days=1)).isoformat(), "to": today.isoformat()}


def live(rows: list[dict], today: datetime.date) -> tuple[list[dict], dict]:
    """기준일에 살아 있는 시그널 (남은 비중 > 0). from 은 그중 가장 오래된 날짜(없으면 today)."""
    w = [r for r in rows if remaining(r, today) > 0]
    return w, {"mode": "live", "days": None, "from": min((r["date"] for r in w), default=today.isoformat()), "to": today.isoformat()}


def select(rows: list[dict], today: datetime.date, days: int | None):
    """days=None 이면 누적(살아 있는 시그널, 줄어든 가중치), 아니면 창(그대로). (행, 범위, 가중치 함수)."""
    if days is None:
        w, span = live(rows, today)
        return w, span, (lambda r: live_weight(r, today))
    w, span = in_window(rows, today, days)
    return w, span, weight


def enabled_windows(rows: list[dict], today: datetime.date) -> list[int]:
    """열 수 있는 창. 첫 창은 항상, 나머지는 장부가 (n − grace)일 이상 쌓였을 때. 장부가 길어지면 저절로 열린다."""
    first = min((d(r["date"]) for r in rows), default=None)
    have = (today - first).days + 1 if first else 0
    return [n for i, n in enumerate(PARAMS["windows"]) if i == 0 or have >= n - PARAMS["grace"]]


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


def _tally(w: list[dict], smap: dict, wfn=weight) -> tuple[dict, collections.Counter]:
    """행을 섹터×축으로 모은다. wfn 이 행의 가중치(창은 weight, 누적은 live_weight). sector_map 에 없는 섹터·축의 행은 orphans 에 센다 (맵에서 이름이 바뀌거나 빠진 섹터)."""
    cells = {s: {a: _cell() for a in AXES} for s in smap}
    orphans: collections.Counter = collections.Counter()
    for r in w:
        s, a = r.get("sector"), r.get("axis")
        if s not in cells or a not in AXES:
            orphans[f"{s} ({a})" if a not in AXES else str(s)] += 1
            continue
        c = cells[s][a]
        dirc = r.get("direction", "±")
        c["raw"] += DIRV.get(dirc, 0) * wfn(r)
        c["n"] += 1
        c["up" if dirc == "+" else "down" if dirc == "-" else "both"] += 1
    return cells, orphans


def _scores(cells: dict, smap: dict, dirs: list[tuple[str, list[str]]]) -> tuple[dict, dict]:
    """섹터별 (nets, n) 과 방향별 (nets, n, active). alignment 와 series 가 같은 규칙을 쓴다.
    축 점수는 소수 2자리로 반올림한 값이 유일한 값이다: 점수(score_of)·상태(label_of)·표시(fmt_net)가 모두 이 값을 쓰므로
    감쇠로 0.005 미만이 된 축이 화면에는 0 으로 보이면서 상태에서만 밀어줌/막음으로 세는 일이 없다."""
    by_sector = {}
    for s in smap:
        nets = {a: round(clamp(cells[s][a]["raw"] / K), 2) for a in AXES}
        by_sector[s] = (nets, sum(cells[s][a]["n"] for a in AXES))
    by_dir = {}
    for dn, members in dirs:
        active = [by_sector[s][0] for s in members if by_sector[s][1]]
        nets = {a: round(sum(x[a] for x in active) / len(active), 2) if active else 0.0 for a in AXES}
        by_dir[dn] = (nets, sum(by_sector[s][1] for s in members), len(active))
    return by_sector, by_dir


def alignment(rows: list[dict], today: datetime.date, days: int | None = None, smap: dict | None = None) -> dict:
    """섹터·방향별 정렬 점수. days=None 은 누적, 정수는 창. 섹터는 sector_map 순서. 정렬은 화면(JS)에서 한다."""
    smap = load_sector_map() if smap is None else smap
    dirs = directions(smap)
    w, span, wfn = select(rows, today, days)
    cells, orphans = _tally(w, smap, wfn)
    by_sector, by_dir = _scores(cells, smap, dirs)
    sectors = []
    for s, cfg in smap.items():
        nets, n = by_sector[s]
        sectors.append({
            "sector": s, "direction": cfg["direction"], "tickers": list(cfg["tickers"]), "n": n,
            "axes": {a: {"net": round(nets[a], 2), "raw": round(cells[s][a]["raw"], 1), "n": cells[s][a]["n"],
                         "up": cells[s][a]["up"], "down": cells[s][a]["down"], "both": cells[s][a]["both"]} for a in AXES},
            "score": score_of(nets) if n else None, "label": label_of(nets, n),
        })
    out_dirs = []
    for dn, members in dirs:
        nets, n, active = by_dir[dn]
        out_dirs.append({"direction": dn, "sectors": list(members), "n": n, "active": active,
                         "axes": {a: round(nets[a], 2) for a in AXES},
                         "score": score_of(nets) if n else None, "label": label_of(nets, n)})
    counts = collections.Counter(x["label"] for x in sectors)
    return {**span, "total": len(w), "sectors": sectors, "directions": out_dirs,
            "counts": {k: counts.get(k, 0) for k in LABELS},
            "orphans": dict(orphans), "orphan_total": sum(orphans.values())}


def series(rows: list[dict], today: datetime.date, days: int | None = None, span_days: int = PARAMS["span_days"], smap: dict | None = None) -> dict:
    """날짜별 정렬 %. days=None 은 누적, 정수는 창. dates 는 오래된 순, 장부 첫날(또는 span_days 전) 부터 today 까지. 신호 없는 날은 None. 장부가 비면 dates 도 비어 있다."""
    smap = load_sector_map() if smap is None else smap
    dirs = directions(smap)
    out_s: dict[str, list] = {s: [] for s in smap}
    out_d: dict[str, list] = {dn: [] for dn, _ in dirs}
    first = min((d(r["date"]) for r in rows), default=None)
    start = max(first, today - datetime.timedelta(days=span_days - 1)) if first else None
    dates = [start + datetime.timedelta(days=i) for i in range((today - start).days + 1)] if start and start <= today else []
    for t in dates:
        w, _span, wfn = select(rows, t, days)
        cells, _o = _tally(w, smap, wfn)
        by_sector, by_dir = _scores(cells, smap, dirs)
        for s in smap:
            nets, n = by_sector[s]
            out_s[s].append(score_of(nets) if n else None)
        for dn, _m in dirs:
            nets, n, active = by_dir[dn]
            out_d[dn].append(score_of(nets) if active else None)
    return {"mode": "live" if days is None else "window", "days": days, "dates": [x.isoformat() for x in dates], "sectors": out_s, "directions": out_d}


def delta(values: list, back: int = PARAMS["delta_days"]):
    """마지막 값 − back 일 전 값. 둘 중 하나라도 없으면 None."""
    if len(values) <= back or values[-1] is None or values[-1 - back] is None:
        return None
    return values[-1] - values[-1 - back]


def attach_deltas(board: dict, ser: dict, back: int = PARAMS["delta_days"]) -> dict:
    """board 의 섹터·방향에 series 기준 back 일 변화(delta)를 붙인다. 같은 기준(누적끼리, 같은 창끼리) 써야 한다."""
    for x in board["sectors"]:
        x["delta"] = delta(ser["sectors"].get(x["sector"], []), back)
    for x in board["directions"]:
        x["delta"] = delta(ser["directions"].get(x["direction"], []), back)
    return board


def fmt_net(v: float) -> str:
    return "0" if abs(v) < 0.005 else f"{v:+.2f}"


def fmt_delta(v) -> str:
    return "–" if v is None else ("0p" if v == 0 else f"{v:+d}p")


def span_text(span: dict) -> str:
    """범위 한 줄. 누적이면 유효기간 설명, 창이면 날짜 범위."""
    if span.get("mode") == "live":
        v = " · ".join(f"{h} {n}일" for h, n in VALIDITY.items())
        return f"{span['to']} 기준 살아 있는 시그널. 유효기간 {v}, 그동안 가중치가 서서히 0으로"
    return f"최근 {span['days']}일 {span['from']} ~ {span['to']}"


def board_table(board: dict) -> list[str]:
    """브리프 "섹터 정렬" 절에 그대로 붙이는 마크다운 표. 신호 있는 섹터만, 정렬 % 높은 순."""
    rows = sorted((x for x in board["sectors"] if x["n"]), key=lambda x: (-x["score"], -x["n"], x["sector"]))
    out = ["| 섹터 | " + " | ".join(AXES) + " | 정렬 | 상태 | 7일 변화 |", "|---|" + "---|" * (len(AXES) + 3)]
    for x in rows:
        out.append(f"| {x['sector']} | " + " | ".join(fmt_net(x["axes"][a]["net"]) for a in AXES) +
                   f" | {x['score']}% | {LABELS[x['label']]} | {fmt_delta(x.get('delta'))} |")
    if not rows:
        out.append("| (신호 있는 섹터 없음) |" + " |" * (len(AXES) + 3))
    return out


def pending_review(rows: list[dict], today: datetime.date, days: int | None = None) -> list[dict]:
    """확인 대기: 30일 넘은 + 시그널 중 horizon 1년 이상, 번복되지 않은 것. days=None 이면 살아 있는(유효기간 안) 시그널 전부,
    정수면 그 창 안. 점수를 밀어 올리는 동안은 계속 확인 대상이어야 하므로 기본이 누적이다. /trend 와 /review 가 같은 목록을 본다. 행에 line 이 있어야 한다."""
    reversed_lines = {r["reverses"] for r in rows if r.get("reverses")}
    cut = today - datetime.timedelta(days=30)
    w, _span, _wfn = select(rows, today, days)
    return [r for r in w if d(r["date"]) <= cut and r.get("direction") == "+" and r.get("horizon", "1년") != "분기" and r.get("line") not in reversed_lines]


# ---------------------------------------------------------------- raw (수집 원문)
def _title_key(t: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]", "", t.lower().split(" - ")[0])


def raw_scan(today: datetime.date, days: int = 14, raw_dir: Path = ROOT / "raw", current: set[str] | None = None) -> dict:
    """raw/<날짜>/*.json 을 한 번만 읽어 날짜별 소스 현황과 제목을 돌려준다.
    {"dates": [오래된 순], "present": [자료 있는 날짜], "days": {날짜: {소스: {count, error, current, backfill}}}, "titles": {날짜: [제목...]}}.
    backfill 은 fetch/backfill.py 가 소급 수집한 파일 (그날 수집분보다 성기다).
    current 를 주면 그 목록에 없는 소스(옛 sources.yaml 의 소스, 예: gnews_co_*)는 current=false 로 표시하고 제목 집계에서 뺀다."""
    dates = [(today - datetime.timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    out = {"dates": dates, "present": [], "days": {}, "titles": {}}
    for dt in dates:
        day = raw_dir / dt
        if not day.is_dir():
            continue
        files = sorted(day.glob("*.json"))
        if not files:
            continue
        out["present"].append(dt)
        srcs, titles, seen = {}, [], set()
        for f in files:
            try:
                j = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                srcs[f.stem] = {"count": 0, "error": "읽기 실패", "current": current is None or f.stem in current}
                continue
            name = j.get("source", f.stem)
            cur = current is None or name in current
            items = j.get("items", [])
            srcs[name] = {"count": j.get("count", len(items)), "error": j.get("error"), "current": cur, "backfill": bool(j.get("backfill"))}
            if not cur:
                continue
            for it in items:
                key = _title_key(it.get("title") or "")
                if key and key not in seen:
                    seen.add(key)
                    titles.append(it.get("title") or "")
        out["days"][dt] = srcs
        out["titles"][dt] = titles
    return out


def attention(scan: dict, smap: dict | None = None) -> dict:
    """raw_scan 결과에서 섹터 keywords 언급 건수. 최근 7일과 그 전 7일을 비교한다."""
    smap = load_sector_map() if smap is None else smap
    regs = {s: [re.compile(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", re.I) for k in c["keywords"]]
            for s, c in smap.items() if c["keywords"]}
    dates, present = scan["dates"], scan["present"]
    counts = {dt: collections.Counter() for dt in dates}
    total = collections.Counter()
    for dt in present:
        for title in scan["titles"].get(dt, []):
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
        out.append({"sector": s, "direction": cfg["direction"], "n7": n7, "share7": share7, "delta_pp": round(share7 - sharep, 1)})
    out.sort(key=lambda x: (-x["n7"], x["sector"]))
    return {"headlines7": sum(total[dt] for dt in last7),
            "days_present7": sum(1 for dt in last7 if dt in present), "days_present_prev7": sum(1 for dt in prev7 if dt in present),
            "comparable": sum(1 for dt in prev7 if dt in present) >= 4, "sectors": out}
