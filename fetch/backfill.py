#!/usr/bin/env python3
"""과거 raw 채우기. 날짜 범위의 raw/<날짜>/<소스>.json 을 소스별 과거 조회 방법으로 만든다. 이미 있는 파일은 건드리지 않는다.

  python3 fetch/backfill.py --from 2026-06-19 --to 2026-09-16 [--only a,b] [--out DIR] [--dry-run]

소스별 방법 (sources.yaml 의 이름 기준):
  gnews_*            Google News 검색 + after:/before: (2일 청크, 청크당 관련도순 100건 캡). 그날 원래 수집(when:2d, 최대 100건/일)보다 성기다
  federal_register   API documents.json 날짜 조건. type RULE·PRESDOCU 전부 + NOTICE 는 관세·수출통제·반도체·AI·디지털자산 검색어만
  fed_press          federalreserve.gov/json/ne-press.json (2016년부터 전부, 제목·링크·분류만)
  wh_actions         피드 ?paged=N 으로 거슬러 감
  pew_research       피드 ?paged=N 으로 거슬러 감
  court_opinions     sources.yaml 의 검색 피드 + filed_after/filed_before (5일 청크, 20건 캡)
  그 밖의 rss         피드가 주는 것만 (sec 25건, doj 25건, bea 48건, census 18건, ftc·ustr·doe 10건). 피드가 닿지 않는 날은 파일을 만들지 않는다

항목은 published 의 KST 날짜 폴더에 넣는다 (그날 04:30 KST 수집이 이틀 창으로 담았을 항목과 하루쯤 어긋날 수 있다).
파일에는 "backfill": true 와 "method" 를 적는다. 사이트의 관심 집계는 제목만 세므로 그대로 쓰인다.
의존성: feedparser (fetch.py 와 같음)
종료 코드: 0 / 1 일부 소스 실패 / 2 인자 오류
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus, urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch  # noqa: E402  (SOURCES, fetch_bytes, parse_items, write_json, title_key, BROWSER_UA, GNEWS_TMPL)

KST = datetime.timezone(datetime.timedelta(hours=9))
FR_API = "https://www.federalregister.gov/api/v1/documents.json"
FR_NOTICE_TERM = '"section 301" | "section 232" | tariff | "export controls" | semiconductor | "artificial intelligence" | "digital asset" | stablecoin'
FED_JSON = "https://www.federalreserve.gov/json/ne-press.json"
GNEWS_CHUNK_DAYS = 2
COURT_CHUNK_DAYS = 5
PACE = {"gnews": 1.5, "fr": 1.0, "page": 1.0, "court": 1.0}


def kst_date(published: str | None) -> str | None:
    if not published:
        return None
    try:
        return datetime.datetime.fromisoformat(published).astimezone(KST).date().isoformat()
    except ValueError:
        return None


def daterange(a: datetime.date, b: datetime.date, step: int = 1):
    d = a
    while d <= b:
        yield d
        d += datetime.timedelta(days=step)


def dedup(items: list[dict], by_title: bool = False) -> list[dict]:
    seen: set[str] = set()
    out = []
    for it in items:
        keys = ["link:" + it["link"]] if it["link"] else []
        if by_title and it["title"]:
            keys.append("title:" + fetch.title_key(it["title"]))
        if any(k in seen for k in keys):
            continue
        seen.update(keys)
        out.append(it)
    return out


def get_items(url: str, ua: str | None = None) -> list[dict]:
    items, _ = fetch.parse_items(fetch.fetch_bytes(url, 60, 2, ua))
    return items


# ---------------------------------------------------------------- 소스별
def gnews_range(query: str, a: datetime.date, b: datetime.date) -> list[dict]:
    q = f"({query})" if " OR " in query else query
    out = []
    for d in daterange(a, b, GNEWS_CHUNK_DAYS):
        lo, hi = d - datetime.timedelta(days=1), d + datetime.timedelta(days=GNEWS_CHUNK_DAYS)   # 경계 포함/제외가 불명확해 하루씩 겹친다
        url = fetch.GNEWS_TMPL.format(q=quote_plus(f"{q} after:{lo} before:{hi}"))
        out += get_items(url)
        time.sleep(PACE["gnews"])
    return dedup(out, by_title=True)


def fr_range(a: datetime.date, b: datetime.date) -> list[dict]:
    base = {"conditions[publication_date][gte]": a.isoformat(), "conditions[publication_date][lte]": b.isoformat(),
            "per_page": 1000, "order": "newest",
            "fields[]": ["title", "type", "agencies", "html_url", "publication_date", "abstract", "document_number"]}
    queries = [dict(base, **{"conditions[type][]": ["RULE", "PRESDOCU"]}),
               dict(base, **{"conditions[type][]": ["NOTICE"], "conditions[term]": FR_NOTICE_TERM})]
    out = []
    for params in queries:
        page = 1
        while True:
            url = FR_API + "?" + urlencode(dict(params, page=page), doseq=True)
            d = json.loads(fetch.fetch_bytes(url, 90, 2))
            for r in d.get("results", []):
                agency = (r.get("agencies") or [{}])[0].get("name") or ""
                out.append({"title": fetch.strip_html(r.get("title")), "link": r.get("html_url") or "",
                            "published": f"{r['publication_date']}T04:00:00+00:00",
                            "summary": fetch.strip_html(f"{r.get('type', '')} · {agency}. {r.get('abstract') or ''}")})
            if page >= int(d.get("total_pages") or 1):
                break
            page += 1
            time.sleep(PACE["fr"])
        time.sleep(PACE["fr"])
    return dedup(out)


def fed_range(a: datetime.date, b: datetime.date) -> list[dict]:
    data = json.loads(fetch.fetch_bytes(FED_JSON, 60, 2).decode("utf-8-sig"))
    out = []
    for x in data:
        try:
            dt = datetime.datetime.strptime(x["d"], "%m/%d/%Y %I:%M:%S %p")
        except (KeyError, ValueError):
            continue
        if not (a <= dt.date() <= b):
            continue
        # 시각은 ET. 3월 둘째 일요일~11월 첫째 일요일 EDT(UTC-4), 그 외 EST(UTC-5)
        y = dt.year
        dst_a = datetime.date(y, 3, 8) + datetime.timedelta(days=(6 - datetime.date(y, 3, 8).weekday()) % 7)
        dst_b = datetime.date(y, 11, 1) + datetime.timedelta(days=(6 - datetime.date(y, 11, 1).weekday()) % 7)
        off = 4 if dst_a <= dt.date() < dst_b else 5
        pub = dt.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=-off))).astimezone(datetime.timezone.utc)
        out.append({"title": fetch.strip_html(x.get("t")), "link": "https://www.federalreserve.gov" + x.get("l", ""),
                    "published": pub.isoformat(), "summary": fetch.strip_html(x.get("pt") or "")})
    return dedup(out)


def paged_feed(url: str, a: datetime.date, ua: str | None = None, max_pages: int = 30) -> list[dict]:
    out = []
    for page in range(1, max_pages + 1):
        u = url + ("&" if "?" in url else "?") + f"paged={page}"
        try:
            items = get_items(u, ua)
        except RuntimeError:
            break   # 마지막 페이지 뒤는 404
        if not items:
            break
        out += items
        oldest = min((kst_date(i["published"]) or "9999" for i in items), default="9999")
        if oldest < a.isoformat():
            break
        time.sleep(PACE["page"])
    return dedup(out)


def court_range(url: str, a: datetime.date, b: datetime.date) -> list[dict]:
    out = []
    for d in daterange(a, b, COURT_CHUNK_DAYS):
        hi = min(d + datetime.timedelta(days=COURT_CHUNK_DAYS - 1), b)
        u = url + f"&filed_after={d.strftime('%m/%d/%Y')}&filed_before={hi.strftime('%m/%d/%Y')}"
        out += get_items(u)
        time.sleep(PACE["court"])
    return dedup(out)


def collect(name: str, src: dict, a: datetime.date, b: datetime.date) -> tuple[list[dict], str, bool]:
    """(항목, 방법, 전 기간을 덮는가). 덮지 않는 소스는 피드에 있는 가장 오래된 날짜부터만 파일을 만든다."""
    ua = fetch.BROWSER_UA if src["ua"] == "browser" else None
    if src["type"] == "gnews":
        return gnews_range(src["query"], a, b), f"Google News after:/before: {GNEWS_CHUNK_DAYS}일 청크(청크당 100건 캡)", True
    if name == "federal_register":
        return fr_range(a, b), "federalregister.gov API 날짜 조건 (RULE·PRESDOCU 전부, NOTICE 는 검색어)", True
    if name == "fed_press":
        return fed_range(a, b), "federalreserve.gov/json/ne-press.json (제목·링크·분류)", True
    if name in ("wh_actions", "pew_research"):
        return paged_feed(src["url"], a, ua), "피드 ?paged=N", True
    if name == "court_opinions":
        return court_range(src["url"], a, b), f"검색 피드 filed_after/filed_before {COURT_CHUNK_DAYS}일 청크(20건 캡)", True
    return get_items(src["url"], ua), "피드에 남아 있는 항목만", False


# ---------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="과거 raw 채우기")
    ap.add_argument("--from", dest="a", required=True, help="YYYY-MM-DD (포함)")
    ap.add_argument("--to", dest="b", required=True, help="YYYY-MM-DD (포함)")
    ap.add_argument("--only", default="", help="쉼표로 구분한 소스 이름. 비우면 전부")
    ap.add_argument("--out", default=None, help="raw 폴더 (기본 raw/)")
    ap.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 날짜별 건수만")
    args = ap.parse_args(argv)
    try:
        a, b = datetime.date.fromisoformat(args.a), datetime.date.fromisoformat(args.b)
    except ValueError:
        ap.error("--from/--to 는 YYYY-MM-DD")
    if a > b:
        ap.error("--from 이 --to 보다 늦음")
    if fetch.feedparser is None:
        sys.stderr.write("feedparser 없음\n")
        return 2
    names = [n.strip() for n in args.only.split(",") if n.strip()] or list(fetch.SOURCE_NAMES)
    unknown = [n for n in names if n not in fetch.SOURCES]
    if unknown:
        ap.error(f"모르는 소스 {unknown}")
    raw_dir = Path(args.out) if args.out else fetch.RAW_DIR
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    failed = []
    for name in names:
        src = fetch.SOURCES[name]
        t0 = time.time()
        try:
            items, method, full = collect(name, src, a, b)
        except Exception as e:
            failed.append(name)
            print(f"[fail] {name:<24} {type(e).__name__}: {e}", file=sys.stderr)
            continue
        by_day: dict[str, list[dict]] = {}
        for it in items:
            dt = kst_date(it["published"])
            if dt and a.isoformat() <= dt <= b.isoformat():
                by_day.setdefault(dt, []).append(it)
        start = a if full else (datetime.date.fromisoformat(min(by_day)) if by_day else None)
        written = skipped = 0
        total = 0
        if start:
            for d in daterange(start, b):
                ds = d.isoformat()
                day = sorted(by_day.get(ds, []), key=lambda x: x["published"] or "", reverse=True)
                path = raw_dir / ds / f"{name}.json"
                if path.exists():
                    skipped += 1
                    continue
                total += len(day)
                if args.dry_run:
                    written += 1
                    continue
                fetch.write_json(path, {"source": name, "feed_url": method, "fetched_at": now.isoformat(), "window_hours": 0,
                                        "count": len(day), "items": day, "backfill": True,
                                        "method": f"{method}. {a} ~ {b} 를 한 번에 받아 published 의 KST 날짜별로 나눔"})
                written += 1
        print(f"[ok]   {name:<24} {len(items):>5} fetched, {sum(len(v) for v in by_day.values()):>5} in range"
              f" -> {written} files ({total} items){f', {skipped} existing kept' if skipped else ''}"
              f"{'' if full else f', coverage from {start}' if start else ', nothing in range'}  {time.time() - t0:.0f}s")
    if failed:
        print(f"{len(failed)}/{len(names)} failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
