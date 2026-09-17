#!/usr/bin/env python3
"""시장 반응. sector_map 티커와 SPY 의 일별 종가를 받아 두고, 장부 시그널마다 그 뒤 섹터 티커가 어떻게 움직였는지 계산한다.

가격 출처: Cboe 지연 시세 (https://cdn.cboe.com/api/global/delayed_quotes/charts/historical/<티커>.json). 키 없이 열리고 2004년부터 있다.
저장: prices/prices.json (prices/ 는 raw/ 처럼 비공개 radar-raw 의 prices/ 를 가리키는 심볼릭 링크. fetch.yml 이 매일 갱신·커밋한다)
  {"source": "...", "updated_at": ISO, "keep_days": 730,
   "tickers": {"SMH": {"dates": ["2024-09-17", ...], "close": [123.4, ...]}, ...}, "errors": {"XXX": "..."}}

반응 계산 (reactions):
  기준 종가 = 장부 날짜(date) 이틀 전 이전의 마지막 종가. 장부 날짜는 브리프를 쓴 날(KST)이고 사건은 보통 그 전날(ET)이므로
  "사건 전날 종가" 다. 그 뒤 1·5·20·60 거래일 종가의 수익률을 시그널의 티커 평균과 SPY 로 낸다. 초과 = 티커 평균 - SPY.
  판정(verdict): 완료된 가장 긴 구간(20 → 5 → 최신 3거래일 이상)의 초과수익 부호가 방향(+/-)과 같으면 "방향대로", 반대면 "반대로",
  ±0.5%p 안이면 "보합", 자료가 모자라면 "아직". ± 시그널은 판정하지 않는다. 판단 재료이지 매매 신호가 아니다.

사용:
  python3 fetch/market.py --update             prices/prices.json 갱신 (전 종목, 최근 keep_days)
  python3 fetch/market.py --check              prices.json 상태 (종목 수, 마지막 날짜, 빠진 종목)
  python3 fetch/market.py --report [--date D]  최근 30일 장부 시그널의 반응 표 (마크다운. 브리프 "시장 반응" 절)
종료 코드: 0 / 1 일부 종목 실패 또는 자료 없음 / 2 인자·환경 오류
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import ROOT, all_tickers, load_sector_map  # noqa: E402

PRICES = ROOT / "prices/prices.json"
CBOE = "https://cdn.cboe.com/api/global/delayed_quotes/charts/historical/{t}.json"
SOURCE = "Cboe delayed quotes (cdn.cboe.com/api/global/delayed_quotes/charts/historical)"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
BENCH = "SPY"
HORIZONS = (1, 5, 20, 60)
KEEP_DAYS = 730
DEAD_ZONE = 0.005   # 초과수익 ±0.5%p 안은 보합
PACE = 1.2          # 요청 간격 초. 빠르면 429


# ---------------------------------------------------------------- 가격 저장
def fetch_ticker(t: str, keep_from: str, retries: int = 3) -> tuple[list[str], list[float]]:
    url = CBOE.format(t=t)
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                d = json.load(resp)
            rows = [x for x in d.get("data", []) if x.get("close") is not None and str(x.get("date", "")) >= keep_from]
            rows.sort(key=lambda x: x["date"])
            return [x["date"] for x in rows], [float(x["close"]) for x in rows]
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429 and attempt < retries:
                time.sleep(15 * (attempt + 1))
                continue
            if 400 <= e.code < 500:
                break
        except Exception as e:  # 네트워크·JSON
            last = e
        if attempt < retries:
            time.sleep(3)
    raise RuntimeError(f"{type(last).__name__}: {last}")


def update(path: Path = PRICES, keep_days: int = KEEP_DAYS) -> int:
    smap = load_sector_map()
    tickers = sorted(all_tickers(smap) | {BENCH})
    keep_from = (datetime.date.today() - datetime.timedelta(days=keep_days)).isoformat()
    old = load_prices(path) or {}
    out = {"source": SOURCE, "updated_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
           "keep_days": keep_days, "tickers": {}, "errors": {}}
    for i, t in enumerate(tickers):
        try:
            dates, close = fetch_ticker(t, keep_from)
            if not dates:
                raise RuntimeError("자료 없음")
            out["tickers"][t] = {"dates": dates, "close": close}
            print(f"[ok]   {t:<6} {len(dates):>4}일  {dates[0]} ~ {dates[-1]}  종가 {close[-1]}")
        except Exception as e:
            prev = (old.get("tickers") or {}).get(t)
            out["errors"][t] = str(e)
            if prev:
                out["tickers"][t] = prev   # 실패한 종목은 이전 자료 유지
                print(f"[fail] {t:<6} {e}  (이전 자료 유지, 마지막 {prev['dates'][-1]})", file=sys.stderr)
            else:
                print(f"[fail] {t:<6} {e}", file=sys.stderr)
        if i < len(tickers) - 1:
            time.sleep(PACE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(path)
    n_err = len(out["errors"])
    print(f"{len(out['tickers'])}/{len(tickers)} 종목 저장 -> {path}" + (f", 실패 {n_err}: {', '.join(out['errors'])}" if n_err else ""))
    return 1 if n_err else 0


def load_prices(path: Path = PRICES) -> dict | None:
    """없거나 깨졌으면 None (사이트 빌드는 시장 반응 없이 진행)."""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(d, dict) or not isinstance(d.get("tickers"), dict):
            return None
        return d
    except (OSError, ValueError):
        return None


def asof(prices: dict | None) -> str | None:
    """가장 최근 종가 날짜 (종목 중 최댓값)."""
    if not prices:
        return None
    return max((s["dates"][-1] for s in prices["tickers"].values() if s.get("dates")), default=None)


# ---------------------------------------------------------------- 반응 계산
def _base_index(dates: list[str], date: str) -> int | None:
    """장부 날짜 이틀 전 이전의 마지막 종가 인덱스. 없으면 None."""
    cut = (datetime.date.fromisoformat(date) - datetime.timedelta(days=2)).isoformat()
    i = None
    for k, dt in enumerate(dates):
        if dt <= cut:
            i = k
        else:
            break
    return i


def _ret(series: dict, i0: int, h: int) -> float | None:
    close = series["close"]
    j = i0 + h
    if j >= len(close) or close[i0] in (0, None) or close[j] is None:
        return None
    return close[j] / close[i0] - 1


def reaction(row: dict, prices: dict) -> dict | None:
    """장부 행 하나의 시장 반응. 자료가 없으면 None.
    {"base": 기준일, "asof": 마지막 종가일, "tickers": [있는 티커], "h": {"1": {"r", "spy", "x"} | None, ...},
     "latest": {"days", "r", "spy", "x"} | None, "verdict": "방향대로"|"반대로"|"보합"|"아직"|None}"""
    tick = prices.get("tickers") or {}
    bench = tick.get(BENCH)
    used = [t for t in row.get("tickers", []) if t in tick and tick[t].get("dates")]
    if not used or not bench:
        return None
    base = None
    for t in used:
        i0 = _base_index(tick[t]["dates"], row["date"])
        if i0 is not None:
            base = tick[t]["dates"][i0] if base is None else min(base, tick[t]["dates"][i0])
    if base is None:
        return None
    ib = _base_index(bench["dates"], row["date"])
    if ib is None:
        return None

    def avg(h: int):
        rs = []
        for t in used:
            s = tick[t]
            i0 = _base_index(s["dates"], row["date"])
            if i0 is None:
                continue
            r = _ret(s, i0, h)
            if r is not None:
                rs.append(r)
        if len(rs) != len(used):   # 한 종목이라도 자료가 모자라면 그 구간은 아직
            return None
        return sum(rs) / len(rs)

    out_h = {}
    for h in HORIZONS:
        r, sp = avg(h), _ret(bench, ib, h)
        out_h[str(h)] = None if r is None or sp is None else {"r": round(r, 4), "spy": round(sp, 4), "x": round(r - sp, 4)}
    # 최신: 기준일 이후 지금까지 (거래일 수는 SPY 기준)
    days = len(bench["dates"]) - 1 - ib
    latest = None
    if days >= 1:
        r, sp = avg(days), _ret(bench, ib, days)
        if r is not None and sp is not None:
            latest = {"days": days, "r": round(r, 4), "spy": round(sp, 4), "x": round(r - sp, 4)}
    verdict = None
    if row.get("direction") in ("+", "-"):
        pick = out_h["20"] or out_h["5"] or (latest if latest and latest["days"] >= 3 else None)
        if pick is None:
            verdict = "아직"
        elif abs(pick["x"]) < DEAD_ZONE:
            verdict = "보합"
        else:
            same = (pick["x"] > 0) == (row["direction"] == "+")
            verdict = "방향대로" if same else "반대로"
    return {"base": base, "asof": bench["dates"][-1], "tickers": used, "h": out_h, "latest": latest, "verdict": verdict}


def reactions(rows: list[dict], prices: dict | None) -> dict[int, dict]:
    """{장부 줄 번호: reaction}. prices 가 없으면 빈 dict."""
    if not prices:
        return {}
    out = {}
    for r in rows:
        try:
            x = reaction(r, prices)
        except (KeyError, TypeError, ValueError):
            x = None
        if x and r.get("line") is not None:
            out[int(r["line"])] = x
    return out


def pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:+.1f}%"


def comment(x: dict | None) -> str:
    """한 줄 요약. 브리프·채팅용."""
    if not x:
        return "가격 자료 없음"
    parts = [f"{h}일 {pct(v['r'])} (SPY {pct(v['spy'])})" for h, v in x["h"].items() if v]
    if not parts and x["latest"]:
        parts = [f"{x['latest']['days']}거래일 {pct(x['latest']['r'])} (SPY {pct(x['latest']['spy'])})"]
    s = f"기준 {x['base']} 종가 대비 " + (" · ".join(parts) if parts else "아직 거래일 없음")
    return s + (f" — {x['verdict']}" if x["verdict"] else "")


def report(rows: list[dict], prices: dict | None, today: datetime.date, days: int = 30) -> str:
    """브리프 "시장 반응" 절. 최근 days 일 장부 행."""
    if not prices:
        return "가격 자료 없음 (prices/prices.json). fetch.yml 의 market.py --update 가 만든다."
    cut = today - datetime.timedelta(days=days)
    w = [r for r in rows if cut < datetime.date.fromisoformat(r["date"]) <= today]
    if not w:
        return f"최근 {days}일 장부 행 없음"
    rx = reactions(w, prices)
    lines = [f"기준: 장부 날짜 이틀 전(사건 전날) 종가. 티커 평균과 SPY. 종가 {asof(prices)} 까지 ({SOURCE.split(' (')[0]}).",
             "", "| 날짜 | 축 · 섹터 | 시그널 | 방향 | 1일 | 5일 | 20일 | 판정 |", "|---|---|---|---|---|---|---|---|"]
    for r in sorted(w, key=lambda r: (r["date"], r.get("line", 0)), reverse=True):
        x = rx.get(int(r.get("line", 0)))
        fact = " ".join(str(r["fact"]).split())
        if len(fact) > 40:
            fact = fact[:39] + "…"
        if x:
            cells = [f"{pct(v['r'])} / {pct(v['spy'])}" if v else "—" for v in (x["h"]["1"], x["h"]["5"], x["h"]["20"])]
            verdict = x["verdict"] or "—"
        else:
            cells, verdict = ["—", "—", "—"], "자료 없음"
        lines.append(f"| {r['date']} | {r['axis']} · {r['sector']} | {fact} | {r['direction']} | {cells[0]} | {cells[1]} | {cells[2]} | {verdict} |")
    return "\n".join(lines)


# ---------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="시장 반응: 가격 갱신·상태·보고")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--update", action="store_true", help="prices/prices.json 갱신")
    g.add_argument("--check", action="store_true", help="prices.json 상태")
    g.add_argument("--report", action="store_true", help="최근 30일 장부 시그널의 반응 표")
    ap.add_argument("--date", default=None, help="--report 기준일 YYYY-MM-DD (기본 오늘)")
    ap.add_argument("--days", type=int, default=30, help="--report 창 (기본 30)")
    args = ap.parse_args(argv)
    if args.update:
        try:
            return update()
        except ValueError as e:   # sector_map 오류
            print(f"sector_map: {e}", file=sys.stderr)
            return 2
    prices = load_prices()
    if args.check:
        if not prices:
            print(f"{PRICES}: 없음 또는 깨짐")
            return 1
        smap = load_sector_map()
        want = sorted(all_tickers(smap) | {BENCH})
        missing = [t for t in want if t not in prices["tickers"]]
        print(f"{PRICES}: {len(prices['tickers'])}종목, 마지막 종가 {asof(prices)}, 갱신 {prices.get('updated_at')}")
        if missing:
            print(f"빠진 종목: {', '.join(missing)}")
        if prices.get("errors"):
            print("마지막 갱신 실패: " + ", ".join(f"{k} ({v})" for k, v in prices["errors"].items()))
        return 1 if missing else 0
    from ledger import load_existing  # noqa: E402  (여기서만 쓴다)
    today = datetime.date.fromisoformat(args.date) if args.date else datetime.date.today()
    rows, _ = load_existing(warnings=[])
    print(report(rows, prices, today, args.days))
    return 0 if prices else 1


if __name__ == "__main__":
    sys.exit(main())
