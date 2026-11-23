#!/usr/bin/env python3
"""시장 반응과 시장 온도. sector_map 티커와 SPY 의 일별 종가를 받아 두고, 장부 시그널마다 그 뒤 섹터 티커가 어떻게 움직였는지 계산한다.
같은 --update 가 금리·신용·변동성 같은 시장 온도 지표(MACRO)도 받아 둔다. 둘 다 판단 재료이지 매매 신호가 아니다.

가격 출처: 키 없이 열리는 곳을 차례로 시도한다 (PRICE_SOURCES 순서). 한 출처가 이번 실행에서 3번 연달아 실패하면(막힘·429·응답 없음) 남은 종목은 그 출처를 건너뛴다.
  전체 15분(PRICE_BUDGET)을 넘기면 남은 종목은 이전 자료를 둔다.
  cboe   Cboe 지연 시세 cdn.cboe.com/api/global/delayed_quotes/charts/historical/<티커>.json (2004년부터. 2026-11-20 부터 Actions 요청을 403 으로 막음)
  yahoo  Yahoo Finance chart API query1|query2.finance.yahoo.com/v8/finance/chart/<티커>?range=2y&interval=1d
  nasdaq api.nasdaq.com/api/quote/<티커>/historical (2026-11-23 Actions 에서 열림)
  stooq  stooq.com/q/d/l/?s=<티커>.us&i=d (CSV. 2026-11-23 Actions 에서는 HTML 만 돌려줌)
  장이 열려 있는 동안 받은 그날 값(미국 동부 16:20 전의 오늘 날짜)은 종가가 아니라서 버린다.
저장: prices/prices.json (prices/ 는 raw/ 처럼 비공개 radar-raw 의 prices/ 를 가리키는 심볼릭 링크. fetch.yml 이 매일 갱신·커밋한다)
  {"source": "출처별 종목 수", "updated_at": ISO, "keep_days": 730,
   "tickers": {"SMH": {"dates": ["2024-09-17", ...], "close": [123.4, ...]}, ...}, "src": {"SMH": "cboe"}, "errors": {"XXX": "..."}}
시장 온도: prices/macro.json. FRED(세인트루이스 연은) 공개 CSV fred.stlouisfed.org/graph/fredgraph.csv?id=<시리즈> 를 기본으로, 막히면 지표별 대체 출처
  (미 재무부 일별 금리표, Yahoo). {"updated_at", "series": {키: {"label", "unit", "src", "dates", "values"}}, "errors"}

반응 계산 (reactions):
  기준 종가 = 장부 날짜(date) 이틀 전 이전의 마지막 종가. 장부 날짜는 브리프를 쓴 날(KST)이고 사건은 보통 그 전날(ET)이므로
  "사건 전날 종가" 다. 그 뒤 1·5·20·60 거래일 종가의 수익률을 시그널의 티커 평균과 SPY 로 낸다. 초과 = 티커 평균 - SPY.
  판정(verdict): 완료된 가장 긴 구간(60 → 20 → 5 → 최신 3거래일 이상)의 초과수익 부호가 방향(+/-)과 같으면 "방향대로", 반대면 "반대로",
  ±0.5%p 안이면 "보합", 자료가 모자라면 "아직". ± 시그널은 판정하지 않는다. 판단 재료이지 매매 신호가 아니다.

사용:
  python3 fetch/market.py --update             prices/prices.json 과 prices/macro.json 갱신 (전 종목·지표, 최근 keep_days)
  python3 fetch/market.py --check              prices.json·macro.json 상태 (종목 수, 마지막 날짜, 빠진 종목, 실패)
  python3 fetch/market.py --report [--date D]  최근 30일 장부 시그널의 반응 표 (마크다운. 브리프 "시장 반응" 절)
  python3 fetch/market.py --macro [--date D]   시장 온도 표 (마크다운. 브리프 "시장 온도" 절)
종료 코드: 0 / 1 일부 종목 실패 또는 자료 없음 / 2 인자·환경 오류
"""
from __future__ import annotations

import argparse
import bisect
import csv
import datetime
import io
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import ROOT, all_tickers, load_sector_map  # noqa: E402

PRICES = ROOT / "prices/prices.json"
MACRO_PATH = ROOT / "prices/macro.json"
CBOE = "https://cdn.cboe.com/api/global/delayed_quotes/charts/historical/{t}.json"
SOURCE = "Cboe delayed quotes (cdn.cboe.com/api/global/delayed_quotes/charts/historical)"   # 옛 자료에 출처가 안 적혀 있을 때의 기본값
SOURCE_NAMES = {"cboe": "Cboe delayed quotes", "yahoo": "Yahoo Finance", "stooq": "Stooq", "nasdaq": "Nasdaq", "fred": "FRED", "treasury": "U.S. Treasury",
                "nyfed": "New York Fed", "dol": "U.S. Department of Labor", "chicagofed": "Chicago Fed"}
PRICE_SOURCES = ("cboe", "yahoo", "nasdaq", "stooq")   # 2026-11-23 Actions 점검: Stooq 는 HTML 만 돌려줘 맨 뒤로
MACRO_STALE_DAYS = 45   # 시장 온도 지표의 마지막 값이 이보다 오래되면 실패로 보고 표에도 안 보인다 (예: 갱신이 멈춘 파일)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
CHROME_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
ET = ZoneInfo("America/New_York")
DOWN_AFTER = 3      # 한 출처가 이번 실행에서 연달아 이만큼 실패하면(막힘·429·응답 없음·자료 없음) 남은 종목은 건너뛴다
FALLBACK_TIMEOUT = 20   # 대체 출처(cboe 밖)의 요청 제한 시간 초. 응답 없는 출처가 종목마다 몇 분씩 잡아먹지 않게
PRICE_BUDGET = 15 * 60  # 종가 갱신 전체 시간 상한 초. 넘으면 남은 종목은 이전 자료를 둔다 (fetch.yml 은 이 단계 뒤에 raw 를 push 한다)
# 시장 온도 지표. (키, 이름, 단위, 변화 표시, FRED 시리즈, 대체 출처). 변화 표시 diff = 차이(금리·지수), pct = 변화율(가격·건수)
MACRO = [
    ("vix", "VIX 변동성지수", "pt", "diff", "VIXCLS", ("yahoo", "^VIX")),
    ("ust2y", "미 국채 2년 금리", "%", "diff", "DGS2", ("treasury", "2 Yr")),
    ("ust10y", "미 국채 10년 금리", "%", "diff", "DGS10", ("treasury", "10 Yr")),
    ("curve", "10년−2년 금리차", "%p", "diff", "T10Y2Y", ("treasury_spread", "10 Yr − 2 Yr")),
    ("hy", "하이일드 신용 스프레드", "%p", "diff", "BAMLH0A0HYM2", None),
    ("hyg", "하이일드 채권 ETF(HYG)", "$", "pct", None, ("yahoo", "HYG")),   # FRED 가 막혀도 보이는 신용 걱정 온도계. 스프레드가 넓어지면 값이 내려간다
    ("be5y", "5년 기대인플레이션", "%", "diff", "T5YIE", ("treasury_be", "5 Yr − 실질 5 Yr")),
    ("ffr", "연방기금금리 상단", "%", "diff", "DFEDTARU", ("nyfed", "EFFR 목표 상단")),
    ("usd", "달러 지수", "", "pct", "DTWEXBGS", ("yahoo", "DX-Y.NYB")),
    ("wti", "WTI 유가", "$", "pct", "DCOILWTICO", ("yahoo", "CL=F")),
    ("btc", "비트코인", "$", "pct", "CBBTCUSD", ("yahoo", "BTC-USD")),
    ("claims", "신규 실업수당 청구(주간)", "건", "pct", "ICSA", ("dol", "ETA 539 주별 합계, 계절조정 전")),
    ("nfci", "금융여건지수 NFCI(주간)", "", "diff", "NFCI", ("chicagofed", "NFCI")),
]
DRAWDOWN = [("SPY", "S&P 500(SPY) 52주 고점 대비"), ("QQQ", "나스닥 100(QQQ) 52주 고점 대비")]   # prices.json 에서 계산
MACRO_KEEP_DAYS = 400
BENCH = "SPY"
HORIZONS = (1, 5, 20, 60)
KEEP_DAYS = 730
DEAD_ZONE = 0.005   # 초과수익 ±0.5%p 안은 보합
PACE = 1.2          # 요청 간격 초. 빠르면 429


# ---------------------------------------------------------------- 가격 저장
class Blocked(RuntimeError):
    """출처가 요청을 막았다 (401·403). 같은 실행에서 연달아 나오면 그 출처를 건너뛴다."""


def _get(url: str, headers: dict, retries: int = 2, timeout: float = 60, wait429: float = 15) -> bytes:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (401, 403):
                raise Blocked(f"HTTP {e.code}") from None
            if e.code == 429 and attempt < retries:
                time.sleep(wait429 * (attempt + 1))
                continue
            if 400 <= e.code < 500 and e.code != 408:
                break
        except Exception as e:  # 네트워크
            last = e
        if attempt < retries:
            time.sleep(3)
    raise RuntimeError(f"{type(last).__name__}: {last}")


def _closed(dates: list[str], close: list[float], keep_from: str, tz: str = "America/New_York") -> tuple[list[str], list[float]]:
    """날짜순 정렬·keep_from 이후·값 있는 것만. 끝나지 않은 그날 값(장중 가격)은 버린다.
    미국 시장(기본): 동부 16:20 전의 오늘 날짜 값과 주말 날짜 값(선물의 일요일 저녁 거래)을 버린다.
    tz 가 UTC 인 24시간 자산(비트코인): UTC 오늘 날짜 값을 버린다."""
    utc = tz.upper() in ("UTC", "GMT", "ETC/UTC")
    now = datetime.datetime.now(datetime.timezone.utc if utc else ET)
    today = now.date().isoformat()
    rows = sorted({d: float(c) for d, c in zip(dates, close)
                   if c is not None and d >= keep_from and (utc or datetime.date.fromisoformat(d).weekday() < 5)}.items())
    if rows and rows[-1][0] == today and (utc or (now.hour, now.minute) < (16, 20)):
        rows = rows[:-1]
    return [d for d, _ in rows], [c for _, c in rows]


def _cboe(t: str, keep_from: str) -> tuple[list[str], list[float]]:
    d = json.loads(_get(CBOE.format(t=t), {"User-Agent": UA, "Accept": "application/json"}))
    rows = [x for x in d.get("data", []) if x.get("close") is not None]
    return _closed([str(x["date"]) for x in rows], [x["close"] for x in rows], keep_from)


def _yahoo(t: str, keep_from: str) -> tuple[list[str], list[float]]:
    sym = urllib.parse.quote(t.replace(".", "-") if re.fullmatch(r"[A-Z]+\.[A-Z]", t) else t, safe="")   # BRK.B → BRK-B, DX-Y.NYB 는 그대로
    days = (datetime.date.today() - datetime.date.fromisoformat(keep_from)).days
    rng = "2y" if days <= 730 else "5y"
    last: Exception | None = None
    for host in ("query1", "query2"):
        try:
            b = _get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d&includePrePost=false",
                     {"User-Agent": CHROME_UA, "Accept": "application/json"}, retries=1, timeout=FALLBACK_TIMEOUT, wait429=5)
            res = json.loads(b)["chart"]["result"][0]
            tzname = res.get("meta", {}).get("exchangeTimezoneName") or "America/New_York"
            tz = ZoneInfo(tzname)
            ts, close = res.get("timestamp") or [], res["indicators"]["quote"][0].get("close") or []
            return _closed([datetime.datetime.fromtimestamp(x, tz).date().isoformat() for x in ts], close, keep_from, tzname)
        except Blocked:
            raise
        except Exception as e:  # 다른 호스트로 한 번 더
            last = e
    raise RuntimeError(f"{type(last).__name__}: {last}")


def _stooq(t: str, keep_from: str) -> tuple[list[str], list[float]]:
    txt = _get(f"https://stooq.com/q/d/l/?s={t.lower()}.us&i=d", {"User-Agent": CHROME_UA}, retries=1, timeout=FALLBACK_TIMEOUT, wait429=5).decode("utf-8", "replace")
    if not txt.startswith("Date,"):
        raise RuntimeError(f"CSV 아님: {txt[:80]!r}")
    rows = [r for r in csv.DictReader(io.StringIO(txt)) if r.get("Close") not in (None, "", "N/D")]
    return _closed([r["Date"] for r in rows], [r["Close"] for r in rows], keep_from)


def _nasdaq(t: str, keep_from: str) -> tuple[list[str], list[float]]:
    h = {"User-Agent": CHROME_UA, "Accept": "application/json, text/plain, */*", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
    for cls in ("etf", "stocks"):
        d = json.loads(_get(f"https://api.nasdaq.com/api/quote/{t}/historical?assetclass={cls}&fromdate={keep_from}&limit=9999", h,
                            retries=1, timeout=FALLBACK_TIMEOUT, wait429=5))
        dates, close = [], []
        for r in (((d.get("data") or {}).get("tradesTable") or {}).get("rows")) or []:
            try:   # 'N/A' 같은 값은 그 줄만 버린다
                c = float(str(r.get("close")).replace("$", "").replace(",", ""))
                dates.append(datetime.datetime.strptime(str(r.get("date")), "%m/%d/%Y").date().isoformat())
                close.append(c)
            except ValueError:
                continue
        if dates:
            return _closed(dates, close, keep_from)
    raise RuntimeError("자료 없음")


FETCHERS = {"cboe": _cboe, "yahoo": _yahoo, "stooq": _stooq, "nasdaq": _nasdaq}


def fetch_ticker(t: str, keep_from: str, skip: set[str] | frozenset = frozenset(), blocked: dict | None = None) -> tuple[list[str], list[float], str]:
    """(날짜, 종가, 출처). PRICE_SOURCES 를 차례로 시도한다. blocked 를 주면 출처마다 연속 실패 횟수를 거기에 센다 (성공하면 0)."""
    errs = []
    for src in PRICE_SOURCES:
        if src in skip:
            continue
        try:
            dates, close = FETCHERS[src](t, keep_from)
            if not dates:
                raise RuntimeError("자료 없음")
            if blocked is not None:
                blocked[src] = 0
            return dates, close, src
        except Exception as e:   # 막힘(401·403)뿐 아니라 429·응답 없음·자료 없음도 센다. 그래야 죽은 출처가 종목마다 시간을 잡아먹지 않는다
            if blocked is not None:
                blocked[src] = blocked.get(src, 0) + 1
            errs.append(f"{src} {e}" if isinstance(e, Blocked) else f"{src} {type(e).__name__}: {e}")
    raise RuntimeError("; ".join(errs) or "시도할 출처 없음")


def probe_sources(used: set[str], t0: float, t: str = BENCH) -> dict:
    """이번 실행에 쓰지 않은 가격 출처가 지금 열리는지 SPY 한 종목으로 확인한다. 앞 출처가 막혔을 때 실제로 넘어갈 수 있는지 미리 알기 위해서다.
    {"checked_at", 출처: "ok n일 ~ 마지막 날짜" | "fail 오류"}. 시간 상한을 넘겼으면 건너뛴다."""
    res: dict[str, str] = {"checked_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()}
    keep_from = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    for src in PRICE_SOURCES:
        if src in used:
            res[src] = "used"
            continue
        if time.monotonic() - t0 > PRICE_BUDGET:
            res[src] = "skip 시간 상한"
            continue
        try:
            dates, _ = FETCHERS[src](t, keep_from)
            res[src] = f"ok {len(dates)}일 ~ {dates[-1]}" if dates else "fail 자료 없음"
        except Exception as e:
            res[src] = f"fail {e if isinstance(e, Blocked) else type(e).__name__ + ': ' + str(e)}"[:200]
        print(f"[probe] {src:<6} {t} {res[src]}")
    return res


def source_label(prices: dict | None) -> str:
    """사이트·브리프에 적는 가격 출처 한 줄. 출처가 적혀 있지 않은 옛 자료는 Cboe."""
    if not prices:
        return SOURCE_NAMES["cboe"]
    src = prices.get("src")
    if isinstance(src, dict) and src:
        c: dict[str, int] = {}
        for v in src.values():
            c[v] = c.get(v, 0) + 1
        return " · ".join(SOURCE_NAMES.get(k, k) + (f" {n}종목" if len(c) > 1 else "") for k, n in sorted(c.items(), key=lambda x: -x[1]))
    return str(prices.get("source") or SOURCE).split(" (")[0]


def update(path: Path = PRICES, keep_days: int = KEEP_DAYS) -> int:
    smap = load_sector_map()
    tickers = sorted(all_tickers(smap) | {BENCH})
    keep_from = (datetime.date.today() - datetime.timedelta(days=keep_days)).isoformat()
    old = load_prices(path) or {}
    out = {"source": "", "updated_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
           "keep_days": keep_days, "tickers": {}, "src": {}, "errors": {}}
    old_src = old.get("src") if isinstance(old.get("src"), dict) else {}
    blocked: dict[str, int] = {}
    t0 = time.monotonic()
    for i, t in enumerate(tickers):
        skip = {s for s, n in blocked.items() if n >= DOWN_AFTER}
        try:
            if time.monotonic() - t0 > PRICE_BUDGET:
                raise RuntimeError(f"시간 상한 {PRICE_BUDGET // 60}분 초과로 건너뜀")
            dates, close, src = fetch_ticker(t, keep_from, skip, blocked)
            out["tickers"][t] = {"dates": dates, "close": close}
            out["src"][t] = src
            print(f"[ok]   {t:<6} {len(dates):>4}일  {dates[0]} ~ {dates[-1]}  종가 {close[-1]}  ({src})")
        except Exception as e:
            prev = (old.get("tickers") or {}).get(t)
            out["errors"][t] = str(e)
            if prev:
                out["tickers"][t] = prev   # 실패한 종목은 이전 자료 유지
                out["src"][t] = old_src.get(t, "cboe")
                print(f"[fail] {t:<6} {e}  (이전 자료 유지, 마지막 {prev['dates'][-1]})", file=sys.stderr)
            else:
                print(f"[fail] {t:<6} {e}", file=sys.stderr)
        if i < len(tickers) - 1:
            time.sleep(PACE)
    out["source"] = source_label(out)
    out["probe"] = probe_sources(set(out["src"][t] for t in out["src"] if t not in out["errors"]), t0)
    down = sorted(s for s, n in blocked.items() if n >= DOWN_AFTER)
    if down:
        print(f"이번 실행에서 건너뛴 출처: {', '.join(down)} (연달아 {DOWN_AFTER}번 실패, 남은 종목은 다음 출처로)", file=sys.stderr)
    _write(path, out)
    n_err = len(out["errors"])
    print(f"{len(out['tickers'])}/{len(tickers)} 종목 저장 -> {path} ({out['source']})" + (f", 실패 {n_err}: {', '.join(out['errors'])}" if n_err else ""))
    update_macro()   # 시장 온도 실패는 [fail] 줄로만 알린다. 종료 코드는 종가 기준 (fetch.yml 이 "종가 일부 종목 실패"로 읽는다)
    return 1 if n_err else 0


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- 시장 온도 (macro.json)
def _fred(series: str, keep_from: str) -> tuple[list[str], list[float]]:
    txt = _get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={keep_from}", {"User-Agent": CHROME_UA, "Accept": "text/csv,*/*"}, retries=1, timeout=FALLBACK_TIMEOUT, wait429=5).decode("utf-8", "replace")
    rows = list(csv.reader(io.StringIO(txt)))
    if not rows or len(rows[0]) < 2 or rows[0][1] != series:
        raise RuntimeError(f"CSV 아님: {txt[:80]!r}")
    out = [(r[0], float(r[1])) for r in rows[1:] if len(r) > 1 and r[1] not in ("", ".") and r[0] >= keep_from]
    return [d for d, _ in out], [v for _, v in out]


_TREASURY_CACHE: dict[tuple[str, int], list[dict]] = {}


def _treasury(column: str, keep_from: str, kind: str = "daily_treasury_yield_curve") -> tuple[list[str], list[float]]:
    """미 재무부 일별 국채 금리표 (home.treasury.gov). 해마다 파일이 나뉘어 있어 keep_from 의 해부터 올해까지 받는다.
    kind: daily_treasury_yield_curve (명목) | daily_treasury_real_yield_curve (실질, TIPS). 열 이름은 대소문자를 가리지 않는다. 한 실행 안에서는 받은 표를 다시 쓴다."""
    vals: dict[str, float] = {}
    for y in range(int(keep_from[:4]), datetime.date.today().year + 1):
        if (kind, y) not in _TREASURY_CACHE:
            url = (f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all"
                   f"?type={kind}&field_tdr_date_value={y}&page&_format=csv")
            _TREASURY_CACHE[(kind, y)] = list(csv.DictReader(io.StringIO(
                _get(url, {"User-Agent": CHROME_UA}, retries=1, timeout=FALLBACK_TIMEOUT, wait429=5).decode("utf-8-sig", "replace"))))
        for r in _TREASURY_CACHE[(kind, y)]:
            row = {k.strip().lower(): v for k, v in r.items() if k}
            v = row.get(column.lower())
            if v not in (None, "", "N/A"):
                vals[datetime.datetime.strptime(row["date"], "%m/%d/%Y").date().isoformat()] = float(v)
    out = sorted((d, v) for d, v in vals.items() if d >= keep_from)
    if not out:
        raise RuntimeError(f"'{column}' 열 없음 ({kind})")
    return [d for d, _ in out], [v for _, v in out]


def _diff(a: tuple[list[str], list[float]], b: tuple[list[str], list[float]]) -> tuple[list[str], list[float]]:
    """같은 날짜끼리 a − b."""
    bm = dict(zip(*b))
    out = [(d, round(v - bm[d], 4)) for d, v in zip(*a) if d in bm]
    return [d for d, _ in out], [v for _, v in out]


def _nyfed_target_upper(keep_from: str) -> tuple[list[str], list[float]]:
    """뉴욕 연은 EFFR 자료의 목표 범위 상단 (markets.newyorkfed.org, 키 없음)."""
    d = json.loads(_get(f"https://markets.newyorkfed.org/api/rates/unsecured/effr/search.json?startDate={keep_from}&endDate={datetime.date.today().isoformat()}",
                        {"User-Agent": CHROME_UA, "Accept": "application/json"}, retries=1, timeout=FALLBACK_TIMEOUT, wait429=5))
    out = sorted((r["effectiveDate"], float(r["targetRateTo"])) for r in d.get("refRates") or [] if r.get("targetRateTo") is not None)
    return [x for x, _ in out], [v for _, v in out]


def _parse_day(x: str) -> str | None:
    for f in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(x.strip(), f).date().isoformat()
        except ValueError:
            continue
    return None


def _chicagofed_nfci(keep_from: str) -> tuple[list[str], list[float]]:
    """시카고 연은 NFCI CSV. 열 이름이 바뀌어도 되게 날짜 열(첫 열)과 이름이 NFCI 인 열을 찾는다. 형식이 다르면 첫 줄을 오류에 담는다."""
    txt = _get("https://www.chicagofed.org/-/media/publications/nfci/nfci-data-series-csv.csv", {"User-Agent": CHROME_UA, "Accept": "text/csv,*/*"},
               retries=1, timeout=FALLBACK_TIMEOUT, wait429=5).decode("utf-8-sig", "replace")
    rows = list(csv.reader(io.StringIO(txt)))
    head = [h.strip().lower() for h in rows[0]] if rows else []
    if "nfci" not in head:
        raise RuntimeError(f"NFCI 열 없음: {txt[:120]!r}")
    j = head.index("nfci")
    out = []
    for r in rows[1:]:
        d = _parse_day(r[0]) if r else None
        if d and len(r) > j and r[j].strip() not in ("", "."):
            out.append((d, float(r[j])))
    out = sorted(x for x in out if x[0] >= keep_from)
    if not out or not -5 < out[-1][1] < 10:
        raise RuntimeError(f"값이 이상함: {out[-1:]!r} / {txt[:120]!r}")
    return [d for d, _ in out], [v for _, v in out]


def _dol_claims(keep_from: str) -> tuple[list[str], list[float]]:
    """노동부 ETA 539 주별 주(州) 자료(oui.doleta.gov ar539.csv)의 신규 청구(c3)를 주마다 더한다. 계절조정 전이라 FRED ICSA 와 수준이 다르다.
    주간 끝 날짜는 c2(반영 주 끝)를 쓴다. 열이 없거나 합계가 전국 신규 청구로 보기 어려운 크기면 실패로 둔다."""
    txt = _get("https://oui.doleta.gov/unemploy/csv/ar539.csv", {"User-Agent": CHROME_UA, "Accept": "text/csv,*/*"},
               retries=1, timeout=45, wait429=5).decode("utf-8-sig", "replace")
    rd = csv.DictReader(io.StringIO(txt))
    cols = [c.strip().lower() for c in (rd.fieldnames or [])]
    if not {"st", "c2", "c3"} <= set(cols):
        raise RuntimeError(f"열 없음(st·c2·c3): {txt[:120]!r}")
    tot: dict[str, float] = {}
    n: dict[str, int] = {}
    for r in rd:
        r = {k.strip().lower(): v for k, v in r.items() if k}
        d = _parse_day(r.get("c2") or "")
        if not d or d < keep_from:
            continue
        try:
            tot[d] = tot.get(d, 0.0) + float(r["c3"])
            n[d] = n.get(d, 0) + 1
        except (TypeError, ValueError):
            continue
    full = max(n.values(), default=0)
    out = sorted((d, v) for d, v in tot.items() if n[d] >= full - 3)   # 아직 모든 주가 보고하지 않은 주는 뺀다
    if not out or not 100_000 <= out[-1][1] <= 1_200_000:
        raise RuntimeError(f"합계가 이상함: {out[-1:]!r}, 주 {full}개")
    return [d for d, _ in out], [v for _, v in out]


def _alt_fetch(alt: tuple[str, str], keep_from: str) -> tuple[list[str], list[float]]:
    kind, arg = alt
    if kind == "yahoo":
        return _yahoo(arg, keep_from)
    if kind == "treasury":
        return _treasury(arg, keep_from)
    if kind == "treasury_spread":   # 10년 − 2년
        return _diff(_treasury("10 Yr", keep_from), _treasury("2 Yr", keep_from))
    if kind == "treasury_be":       # 5년 명목 − 5년 실질 = 손익분기 기대인플레이션 (FRED T5YIE 와 같은 정의)
        return _diff(_treasury("5 Yr", keep_from), _treasury("5 YR", keep_from, "daily_treasury_real_yield_curve"))
    if kind == "nyfed":
        return _nyfed_target_upper(keep_from)
    if kind == "dol":
        return _dol_claims(keep_from)
    if kind == "chicagofed":
        return _chicagofed_nfci(keep_from)
    raise RuntimeError(f"모르는 대체 출처 {kind}")


def update_macro(path: Path = MACRO_PATH, keep_days: int = MACRO_KEEP_DAYS) -> int:
    """시장 온도 지표를 받아 macro.json 에 쓴다. 지표마다 FRED → 대체 출처 순서. 실패한 지표는 이전 자료를 둔다. 0 / 1 일부 실패."""
    keep_from = (datetime.date.today() - datetime.timedelta(days=keep_days)).isoformat()
    old = load_macro(path) or {}
    out = {"updated_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(), "keep_days": keep_days, "series": {}, "errors": {}}
    fails: dict[str, int] = {}   # 출처별 연속 실패. DOWN_AFTER 번이면 남은 지표는 그 출처를 건너뛴다
    for i, (key, label, unit, chg, fred_id, alt) in enumerate(MACRO):
        tries = [("fred", lambda: _fred(fred_id, keep_from))] if fred_id else []
        if alt:
            tries.append((alt[0].split("_")[0], lambda a=alt: _alt_fetch(a, keep_from)))
        errs = []
        for src, fn in tries:
            if fails.get(src, 0) >= DOWN_AFTER:
                errs.append(f"{src} 건너뜀(연달아 {DOWN_AFTER}번 실패)")
                continue
            try:
                dates, values = fn()
                if not dates:
                    raise RuntimeError("자료 없음")
                if not _fresh(dates[-1]):
                    raise RuntimeError(f"오래된 자료(마지막 {dates[-1]})")
                out["series"][key] = {"label": label, "unit": unit, "chg": chg, "id": fred_id if src == "fred" else alt[1], "src": src, "dates": dates, "values": values}
                print(f"[ok]   {key:<7} {label:<24} {len(dates):>4}개  {dates[-1]}  {values[-1]}  ({src})")
                fails[src] = 0
                break
            except Exception as e:
                fails[src] = fails.get(src, 0) + 1
                errs.append(f"{src} {type(e).__name__}: {e}")
        else:
            out["errors"][key] = "; ".join(errs)
            prev = (old.get("series") or {}).get(key)
            if prev and prev.get("dates") and _fresh(prev["dates"][-1]):
                out["series"][key] = prev
            print(f"[fail] {key:<7} {label} {'; '.join(errs)}" + (f"  (이전 자료 유지, 마지막 {prev['dates'][-1]})" if prev else ""), file=sys.stderr)
        if i < len(MACRO) - 1:
            time.sleep(0.6)
    _write(path, out)
    print(f"시장 온도 {len(out['series'])}/{len(MACRO)} 지표 저장 -> {path}" + (f", 실패 {len(out['errors'])}: {', '.join(out['errors'])}" if out["errors"] else ""))
    return 1 if out["errors"] else 0


def _fresh(day: str, today: datetime.date | None = None) -> bool:
    return ((today or datetime.date.today()) - datetime.date.fromisoformat(day)).days <= MACRO_STALE_DAYS


def load_macro(path: Path = MACRO_PATH) -> dict | None:
    """없거나 깨졌으면 None."""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and isinstance(d.get("series"), dict) else None
    except (OSError, ValueError):
        return None


def _at_or_before(dates: list[str], values: list[float], day: str) -> float | None:
    i = bisect.bisect_right(dates, day) - 1
    return values[i] if i >= 0 else None


def macro_rows(macro: dict | None, prices: dict | None, today: datetime.date | None = None, spark_n: int = 60) -> list[dict]:
    """시장 온도 표의 행. 지표마다 마지막 값과 날짜, 1주·1달 전 값, 52주 범위, 최근 spark_n 개 값.
    today 를 주면 그날 이전(포함) 자료만 본다. S&P 500·나스닥 100 의 52주 고점 대비 하락폭은 prices.json 에서 계산한다."""
    cut = today.isoformat() if today else "9999-12-31"
    rows = []
    def row(key, label, unit, chg, dates, values, src, sid):
        i = bisect.bisect_right(dates, cut) - 1
        if i < 0:
            return
        d, v = dates[i], values[i]
        dd = datetime.date.fromisoformat(d)
        if not _fresh(d, today):   # 갱신이 멈춘 지표는 지금 값처럼 보이지 않게 뺀다
            return
        w1 = _at_or_before(dates, values, (dd - datetime.timedelta(days=7)).isoformat())
        m1 = _at_or_before(dates, values, (dd - datetime.timedelta(days=30)).isoformat())
        y0 = (dd - datetime.timedelta(days=365)).isoformat()
        yr = [x for t, x in zip(dates[: i + 1], values[: i + 1]) if t > y0 and x is not None]
        if v is None or not yr:
            return
        rows.append({"key": key, "label": label, "unit": unit, "chg": chg, "date": d, "value": v, "w1": w1, "m1": m1,
                     "lo": min(yr), "hi": max(yr), "src": src, "id": sid, "spark": values[max(0, i + 1 - spark_n): i + 1]})
    for key, label, unit, chg, fred_id, _alt in MACRO:
        s = ((macro or {}).get("series") or {}).get(key)
        if s and s.get("dates"):
            row(key, label, unit, chg, s["dates"], s["values"], s.get("src", "fred"), s.get("id", fred_id))
    for t, label in DRAWDOWN:
        s = ((prices or {}).get("tickers") or {}).get(t)
        if not s or not s.get("dates"):
            continue
        dates, close = s["dates"], s["close"]
        dd = []
        for j, d in enumerate(dates):   # 그날까지 52주(365일) 고점 대비
            y0 = (datetime.date.fromisoformat(d) - datetime.timedelta(days=365)).isoformat()
            lo = bisect.bisect_right(dates, y0)
            hi = max(close[lo: j + 1])
            dd.append(round((close[j] / hi - 1) * 100, 2) if hi else None)
        row(f"dd_{t.lower()}", label, "%", "diff", dates, dd, (prices or {}).get("src", {}).get(t, "cboe") if isinstance((prices or {}).get("src"), dict) else "cboe", t)
    return rows


# ---------------------------------------------------------------- 시장 온도 읽는 법
# 숫자마다 흔히 쓰는 읽는 법(어림 기준)을 한 줄로 붙인다. 원인을 단정하지 않고 "흔히 ~로 읽는다"로 쓴다. 판단 재료이지 매매 신호가 아니다.
def _pos(r: dict) -> str:
    lo, hi, v = r["lo"], r["hi"], r["value"]
    if hi - lo <= 0:
        return ""
    q = (v - lo) / (hi - lo)
    return " 52주 최고 수준." if q >= 0.95 else " 52주 최저 수준." if q <= 0.05 else ""


def _m1(r: dict) -> float | None:
    """1달 전 대비 변화. diff 는 차이, pct 는 % 변화."""
    if r["m1"] is None:
        return None
    if r["chg"] == "pct":
        return (r["value"] / r["m1"] - 1) * 100 if r["m1"] else None
    return r["value"] - r["m1"]


def macro_reading(r: dict) -> str:
    k, v, m = r["key"], r["value"], _m1(r)
    pos = _pos(r)
    if k == "vix":
        band = "공포 구간" if v >= 30 else "불안 구간" if v >= 20 else "보통" if v >= 15 else "평온"
        return f"{band}. 앞으로 30일 주가가 크게 흔들릴 것으로 보는 정도로, 흔히 20 위를 불안, 30 위를 공포로 읽는다.{pos}"
    if k.startswith("dd_"):
        if v <= -20:
            band = "약세장 구간(고점 대비 −20% 아래)"
        elif v <= -10:
            band = "조정 구간(고점 대비 −10% 아래)" + (f". 흔히 약세장이라고 부르는 −20% 까지 {v + 20:.1f}%p" if v > -20 and v <= -15 else "")
        elif v <= -5:
            band = "얕은 하락"
        else:
            band = "고점 근처"
        return f"{band}."
    if k == "ust2y":
        d = "1달 새 큰 변화 없음" if m is None or abs(m) < 0.15 else f"1달 새 {m:+.2f}%p: " + ("연준이 금리를 덜 올리거나 내릴 것으로 보는 쪽, 또는 안전자산으로 돈이 몰린 쪽으로 흔히 읽는다" if m < 0 else "연준이 금리를 더 올릴 것으로 보는 쪽으로 흔히 읽는다")
        return f"연준 기준금리 예상에 민감한 금리. {d}.{pos}"
    if k == "ust10y":
        d = "1달 새 큰 변화 없음" if m is None or abs(m) < 0.15 else f"1달 새 {m:+.2f}%p: " + ("안전자산 수요나 경기 둔화 걱정 쪽으로 흔히 읽는다" if m < 0 else "대출·회사채 금리가 오르고 성장주 값에 부담이 되는 쪽으로 흔히 읽는다")
        return f"주택담보대출·회사채 금리의 기준. {d}.{pos}"
    if k == "curve":
        if v < 0:
            return f"역전(2년 금리가 10년보다 높음). 경기 둔화를 예상하는 신호로 흔히 본다.{pos}"
        return ("평평한 편(0 근처). 장기 금리가 단기보다 조금만 높다." if v < 0.5 else "정상(장기 금리가 단기보다 높음).") + pos
    if k == "hy":
        band = "신용 걱정이 큰 편" if v >= 5 else "다소 높음" if v >= 4 else "낮은 편(신용 걱정 적음)"
        d = "" if m is None or abs(m) < 0.25 else f" 1달 새 {m:+.2f}%p " + ("넓어짐: 신용등급 낮은 회사가 돈 빌리기 어려워지는 쪽." if m > 0 else "좁아짐: 신용 걱정이 줄어든 쪽.")
        return f"{band}.{d}{pos}"
    if k == "hyg":
        d = "1달 새 큰 변화 없음" if m is None or abs(m) < 1.5 else f"1달 {m:+.1f}%: " + ("신용등급 낮은 회사채 값이 떨어져 신용 걱정이 커진 쪽" if m < 0 else "신용 걱정이 줄어든 쪽")
        return f"신용등급 낮은 회사채 묶음의 값. 신용 걱정이 커지면 내려간다. {d}.{pos}"
    if k == "be5y":
        band = "연준 목표(2%) 근처" if 1.8 <= v <= 2.5 else "연준 목표(2%)보다 높음" if v > 2.5 else "연준 목표(2%)보다 낮음"
        d = "" if m is None or abs(m) < 0.15 else f" 1달 새 {m:+.2f}%p: " + ("시장이 물가보다 경기 둔화를 더 걱정하는 쪽으로 흔히 읽는다." if m < 0 else "물가 걱정이 커진 쪽으로 흔히 읽는다.")
        return f"채권값에 담긴 앞으로 5년 물가 예상. {band}.{d}{pos}"
    if k == "ffr":
        d = "1달 새 변화 없음" if m is None or abs(m) < 0.01 else f"1달 새 {m:+.2f}%p " + ("올림" if m > 0 else "내림")
        return f"연준이 정한 기준금리 범위의 위쪽 끝. {d}. 다음 회의 예상은 이 표에 없다."
    if k == "usd":
        d = "1달 새 큰 변화 없음" if m is None or abs(m) < 1.5 else f"1달 {m:+.1f}%: " + ("달러 강세. 해외 매출이 큰 미국 기업과 신흥국에 부담이고, 불안할 때 흔히 오른다" if m > 0 else "달러 약세. 해외 매출이 큰 미국 기업에 도움")
        return f"주요 통화 대비 달러 값. {d}.{pos}"
    if k == "wti":
        d = "1달 새 큰 변화 없음" if m is None or abs(m) < 10 else f"1달 {m:+.1f}%: " + ("경기 둔화 걱정이나 공급 증가를 반영하는 경우가 많고, 물가에는 내림 압력" if m < 0 else "물가에 오름 압력")
        return f"{d}.{pos}"
    if k == "btc":
        d = "1달 새 큰 변화 없음" if m is None or abs(m) < 15 else f"1달 {m:+.1f}%: " + ("위험한 자산을 피하는 분위기(위험 회피)" if m < 0 else "위험한 자산을 찾는 분위기(위험 선호)")
        return f"위험 선호의 온도계로 흔히 본다. {d}.{pos}"
    if k == "claims":
        band = "많은 편(해고가 늘어나는 쪽)" if v >= 300_000 else "늘어나는 편" if v >= 250_000 else "낮은 편(해고가 적음)"
        note = " 계절조정 전 합계라 명절 주간에 튄다." if r["src"] == "dol" else ""
        return f"한 주 동안 새로 실업수당을 신청한 사람 수. {band}.{note}"
    if k == "nfci":
        band = "평소보다 긴축(돈 구하기 어려움)" if v > 0 else "평소보다 느슨(돈 구하기 쉬움)"
        d = "" if m is None or abs(m) < 0.05 else (" 1달 새 조여짐." if m > 0 else " 1달 새 풀림.")
        return f"0 이 평균. {band}.{d}"
    return ""


def macro_hot(rows: list[dict]) -> list[str]:
    """긴장 쪽으로 읽히는 숫자들 (어림 기준은 macro_reading 과 같다)."""
    by = {r["key"]: r for r in rows}
    hot = []
    v = by.get("vix")
    if v and v["value"] >= 20:
        hot.append(f"변동성 {'공포' if v['value'] >= 30 else '불안'} 구간(VIX {v['value']:.1f})")
    dds = [(by[k]["value"], n) for k, n in (("dd_spy", "S&P 500"), ("dd_qqq", "나스닥 100")) if k in by]
    if dds and min(x for x, _ in dds) <= -10:
        hot.append("주가가 52주 고점 대비 " + ", ".join(f"{n} {x:.1f}%" for x, n in dds))
    c = by.get("curve")
    if c and c["value"] < 0:
        hot.append("장단기 금리 역전")
    h = by.get("hy")
    if h and h["value"] >= 5:
        hot.append(f"신용 스프레드 {h['value']:.2f}%p")
    g = by.get("hyg")
    if g and (_m1(g) or 0) <= -1.5:
        hot.append(f"하이일드 채권 1달 {_m1(g):+.1f}%")
    n = by.get("nfci")
    if n and n["value"] > 0:
        hot.append("금융여건 긴축")
    t, b = by.get("ust10y"), by.get("be5y")
    if t and (_m1(t) or 0) <= -0.15 and (b is None or (_m1(b) or 0) < 0):
        hot.append("금리·기대인플레이션 하락(안전자산·경기 걱정 쪽)")
    u = by.get("usd")
    if u and (_m1(u) or 0) >= 1.5:
        hot.append("달러 강세")
    w = by.get("btc")
    if w and (_m1(w) or 0) <= -15:
        hot.append(f"비트코인 1달 {_m1(w):+.0f}%")
    return hot


def macro_summary(rows: list[dict]) -> str:
    """시장 온도 한 줄 요약."""
    hot = macro_hot(rows)
    if not hot:
        return "한 줄로: 긴장 쪽으로 읽히는 숫자가 눈에 띄지 않는다(VIX 20 아래, 주가 고점 대비 −10% 안)."
    return f"한 줄로: 긴장 쪽으로 읽히는 숫자 {len(hot)}개. " + " · ".join(hot) + "."


def fmt_macro(v: float | None, unit: str) -> str:
    if v is None:
        return "없음"
    if unit in ("%", "%p"):
        return f"{v:.2f}{unit}"
    if unit == "$":
        return f"${v:,.0f}" if abs(v) >= 1000 else f"${v:,.2f}"
    if unit == "건":
        return f"{v:,.0f}"
    if unit == "pt":
        return f"{v:.1f}"
    return f"{v:.2f}"


def fmt_change(v: float | None, base: float | None, unit: str, chg: str) -> str:
    if v is None or base is None:
        return "없음"
    if chg == "pct":
        return "없음" if not base else f"{(v / base - 1) * 100:+.1f}%"
    d = v - base
    return f"{d:+.2f}%p" if unit in ("%", "%p") else f"{d:+.1f}" if unit == "pt" else f"{d:+.2f}"


def macro_report(macro: dict | None, prices: dict | None, today: datetime.date) -> str:
    """브리프 "시장 온도" 절. 사실 숫자만 적는다. 판단 재료이지 매매 신호가 아니다."""
    rows = macro_rows(macro, prices, today)
    if not rows:
        return "시장 온도 자료 없음 (prices/macro.json). fetch.yml 의 market.py --update 가 만든다."
    srcs = sorted({SOURCE_NAMES.get(r["src"], r["src"]) for r in rows})
    lines = [f"기준: 지표마다 {today} 이전 마지막 값. 출처 {', '.join(srcs)}. 읽는 법은 흔히 쓰는 어림 기준이고, 판단 재료이지 매매 신호가 아니다.", "",
             macro_summary(rows), "",
             "| 지표 | 값 | 날짜 | 1주 전 대비 | 1달 전 대비 | 52주 범위 | 읽는 법 |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        u, c = r["unit"], r["chg"]
        lines.append(f"| {r['label']} | {fmt_macro(r['value'], u)} | {r['date'][5:].replace('-', '/')} | {fmt_change(r['value'], r['w1'], u, c)} | "
                     f"{fmt_change(r['value'], r['m1'], u, c)} | {fmt_macro(r['lo'], u)} ~ {fmt_macro(r['hi'], u)} | {macro_reading(r)} |")
    return "\n".join(lines)


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


def lagging(prices: dict | None, days: int = 5) -> list[tuple[str, str]]:
    """[(티커, 마지막 종가 날짜)] 가장 최근 종가(asof)보다 days 일 넘게 뒤처진 종목. 갱신이 계속 실패해 이전 자료로 남은 종목이다.
    asof 는 종목 중 최댓값이라 일부만 멈춘 것은 거기서 드러나지 않는다. 그 종목이 든 시그널의 시장 반응은 멈춘다."""
    a = asof(prices)
    if not a:
        return []
    cut = (datetime.date.fromisoformat(a) - datetime.timedelta(days=days)).isoformat()
    return sorted((t, s["dates"][-1]) for t, s in prices["tickers"].items() if s.get("dates") and s["dates"][-1] < cut)


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


def _close_at(series: dict, date: str) -> float | None:
    """date 이전(포함) 마지막 종가. 그날 거래가 비었으면 전날 종가. date 보다 앞선 자료가 없으면 None."""
    i = bisect.bisect_right(series["dates"], date) - 1
    return series["close"][i] if i >= 0 and series["close"][i] not in (0, None) else None


def reaction(row: dict, prices: dict) -> dict | None:
    """장부 행 하나의 시장 반응. 자료가 없으면 None.
    구간은 SPY 거래일로 센다: 기준일 = SPY 의 기준 종가 날짜, h 거래일 뒤 = SPY 의 ib+h 번째 날짜. 각 티커는 그 두 날짜의 종가로 잰다
    (티커에 그날이 비었으면 전날 종가). 티커 자료가 그 날짜까지 아직 없으면(Cboe 가 늦게 채움) 그 구간은 None.
    {"base": 기준일, "asof": 마지막 종가일, "tickers": [있는 티커], "h": {"1": {"r", "spy", "x"} | None, ...},
     "latest": {"days", "r", "spy", "x"} | None, "verdict": "방향대로"|"반대로"|"보합"|"아직"|None}"""
    tick = prices.get("tickers") or {}
    bench = tick.get(BENCH)
    used = [t for t in row.get("tickers", []) if t in tick and tick[t].get("dates")]
    if not used or not bench:
        return None
    ib = _base_index(bench["dates"], row["date"])
    if ib is None:
        return None
    base = bench["dates"][ib]
    if all(_close_at(tick[t], base) is None for t in used):
        return None

    def at(k: int) -> dict | None:
        """SPY 의 k 번째 날짜까지의 수익률. 한 종목이라도 자료가 모자라면 None."""
        if k >= len(bench["dates"]) or bench["close"][ib] in (0, None):
            return None
        target = bench["dates"][k]
        rs = []
        for t in used:
            s = tick[t]
            c0, c1 = _close_at(s, base), _close_at(s, target)
            if c0 is None or c1 is None or s["dates"][-1] < target:
                return None
            rs.append(c1 / c0 - 1)
        r, sp = sum(rs) / len(rs), bench["close"][k] / bench["close"][ib] - 1
        return {"r": round(r, 4), "spy": round(sp, 4), "x": round(r - sp, 4)}

    out_h = {str(h): at(ib + h) for h in HORIZONS}
    # 최신: 모든 티커와 SPY 에 다 있는 마지막 날짜까지 (거래일 수는 SPY 기준)
    common = min([bench["dates"][-1]] + [tick[t]["dates"][-1] for t in used])
    k = bisect.bisect_right(bench["dates"], common) - 1
    latest = None
    if k - ib >= 1:
        v = at(k)
        if v:
            latest = {"days": k - ib, **v}
    verdict = None
    if row.get("direction") in ("+", "-"):
        pick = out_h["60"] or out_h["20"] or out_h["5"] or (latest if latest and latest["days"] >= 3 else None)
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
    return "없음" if v is None else f"{v * 100:+.1f}%"


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
    lines = [f"기준: 장부 날짜 이틀 전(사건 전날) 종가. 티커 평균과 SPY. 종가 {asof(prices)} 까지 ({source_label(prices)}).",
             "", "| 날짜 | 축 · 섹터 | 시그널 | 방향 | 1일 | 5일 | 20일 | 60일 | 판정 |", "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(w, key=lambda r: (r["date"], r.get("line", 0)), reverse=True):
        x = rx.get(int(r.get("line", 0)))
        fact = " ".join(str(r["fact"]).split())
        if len(fact) > 40:
            fact = fact[:39] + "…"
        if x:
            cells = [f"{pct(v['r'])} / {pct(v['spy'])}" if v else "—" for v in (x["h"]["1"], x["h"]["5"], x["h"]["20"], x["h"]["60"])]
            verdict = x["verdict"] or "—"
        else:
            cells, verdict = ["—", "—", "—", "—"], "자료 없음"
        lines.append(f"| {r['date']} | {r['axis']} · {r['sector']} | {fact} | {r['direction']} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} | {verdict} |")
    return "\n".join(lines)


# ---------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="시장 반응: 가격 갱신·상태·보고")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--update", action="store_true", help="prices/prices.json 갱신")
    g.add_argument("--check", action="store_true", help="prices.json 상태")
    g.add_argument("--report", action="store_true", help="최근 30일 장부 시그널의 반응 표")
    g.add_argument("--macro", action="store_true", help="시장 온도 표 (금리·신용·변동성 등)")
    ap.add_argument("--date", default=None, help="--report·--macro 기준일 YYYY-MM-DD (기본 오늘)")
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
        print(f"{PRICES}: {len(prices['tickers'])}종목, 마지막 종가 {asof(prices)}, 갱신 {prices.get('updated_at')}, 출처 {source_label(prices)}")
        if missing:
            print(f"빠진 종목: {', '.join(missing)}")
        lag = lagging(prices)
        if lag:
            print("멈춘 종목 (최근 종가보다 5일 넘게 뒤): " + ", ".join(f"{t} {dt}" for t, dt in lag))
        if prices.get("errors"):
            print("마지막 갱신 실패: " + ", ".join(f"{k} ({v})" for k, v in prices["errors"].items()))
        m = load_macro()
        if not m:
            print(f"{MACRO_PATH}: 없음 또는 깨짐")
        else:
            last = {k: s["dates"][-1] for k, s in m["series"].items() if s.get("dates")}
            print(f"{MACRO_PATH}: {len(m['series'])}/{len(MACRO)}지표, 마지막 {max(last.values(), default='-')}, 갱신 {m.get('updated_at')}"
                  + (f", 실패 {', '.join(m['errors'])}" if m.get("errors") else ""))
        return 1 if missing else 0
    today = datetime.date.fromisoformat(args.date) if args.date else datetime.date.today()
    if args.macro:
        print(macro_report(load_macro(), prices, today))
        return 0 if load_macro() else 1
    from ledger import load_existing  # noqa: E402  (여기서만 쓴다)
    rows, _ = load_existing(warnings=[])
    print(report(rows, prices, today, args.days))
    return 0 if prices else 1


if __name__ == "__main__":
    sys.exit(main())
