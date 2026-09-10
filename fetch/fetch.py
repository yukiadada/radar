#!/usr/bin/env python3
"""market-brief 수집 스크립트.

고정 소스 (늘리지 않는다):
  federal_register          Federal Register documents RSS
  fed_press                 Federal Reserve Board 보도자료 RSS (press_all)
  gnews_tariff              Google News RSS 검색 "tariff"
  gnews_fed_rate            Google News RSS 검색 "Fed rate"
  gnews_big_tech_antitrust  Google News RSS 검색 "Big Tech antitrust"
  gnews_bitcoin_etf         Google News RSS 검색 "bitcoin ETF"

출력: raw/YYYY-MM-DD/{source}.json
  {
    "source": "...", "feed_url": "...", "fetched_at": "ISO 8601 UTC",
    "window_hours": 48, "count": n,
    "items": [{"title": "...", "link": "...", "published": "ISO 8601 UTC 또는 null", "summary": "..."}]
  }
  수집에 실패한 소스는 (그날 파일이 아직 없을 때만) "error" 필드가 있는 count 0 파일을 남긴다.

시간창:
  --hours N 이내에 발행된 항목만 저장한다. 기본은 48, 월요일(로컬)은 72 (금요일 ET 를 덮기 위해).
  Google News 검색은 관련도순 상위 100건만 주므로, 쿼리에 when:Nd (N = 시간창/24) 를 붙여
  최근 것만 받게 한다. --hours 0 이면 필터도 when: 도 없이 피드가 주는 전부를 저장한다.
  Federal Register 피드는 최근 발행일 순 200건 캡이 있다 (per_page 무시). 200건이 차면 경고한다.

의존성: 표준 라이브러리 + feedparser (feedparser 는 Python 3.10 이상)
  python3 -m pip install --user --break-system-packages feedparser

사용:
  python3 fetch/fetch.py                                  오늘(로컬 날짜) 폴더
  python3 fetch/fetch.py --hours 0                        시간 필터 없이 전부
  python3 fetch/fetch.py --date 2026-09-08 --only gnews_tariff,fed_press

같은 날 다시 실행하면 그 날 파일을 덮어쓴다 (실패한 소스의 기존 파일은 남긴다).
환경변수 MARKET_BRIEF_UA 로 User-Agent 를 바꿀 수 있다.
종료 코드: 0 전부 성공 / 1 일부 피드 실패 / 2 인자·환경 오류
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote_plus

try:
    import feedparser
except ImportError:
    sys.stderr.write(
        "feedparser 없음. 설치: python3 -m pip install --user --break-system-packages feedparser\n"
    )
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "raw"

FR_URL = "https://www.federalregister.gov/api/v1/documents.rss"
FED_URL = "https://www.federalreserve.gov/feeds/press_all.xml"
GNEWS_TMPL = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
GNEWS_QUERIES = {
    "gnews_tariff": "tariff",
    "gnews_fed_rate": "Fed rate",
    "gnews_big_tech_antitrust": "Big Tech antitrust",
    "gnews_bitcoin_etf": "bitcoin ETF",
}
SOURCE_NAMES = ["federal_register", "fed_press", *GNEWS_QUERIES]
FR_FEED_CAP = 200

# federalreserve.gov 는 User-Agent 를 가린다 (2026-09-08 확인):
#   Python 기본 UA -> 403, 브라우저형 UA -> 404, feedparser 형 UA -> 200
USER_AGENT = os.environ.get(
    "MARKET_BRIEF_UA", f"feedparser/{feedparser.__version__} +https://github.com/kurtmckee/feedparser/"
)
ACCEPT = "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.5"


def gnews_url(query: str, hours: int) -> str:
    q = query if hours <= 0 else f"{query} when:{-(-hours // 24)}d"
    return GNEWS_TMPL.format(q=quote_plus(q))


def build_sources(hours: int) -> dict[str, str]:
    urls = {"federal_register": FR_URL, "fed_press": FED_URL}
    urls.update({name: gnews_url(q, hours) for name, q in GNEWS_QUERIES.items()})
    return urls


def default_hours() -> int:
    return 72 if datetime.now().weekday() == 0 else 48  # 월요일은 금요일(ET)까지 덮는다


# ---------------------------------------------------------------- 텍스트 정리
def collapse_ws(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


class _TextExtractor(HTMLParser):
    """HTML 을 평문으로. 블록·font 경계는 줄바꿈으로 남겨서 나중에 ' | ' 로 잇는다."""

    _BREAK = {"br", "li", "p", "div", "tr", "h1", "h2", "h3", "h4", "ol", "ul", "table", "blockquote", "font"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._BREAK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BREAK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


_TAGLIKE = re.compile(r"</?[a-zA-Z][a-zA-Z0-9-]*(\s[^<>]*)?/?>")


def _strip_once(text: str) -> str:
    # 태그처럼 생기지 않은 홑 '<' ("<5 ppm", "a<b") 는 이스케이프. HTMLParser 는 미종결 '<x' 뒤를 통째로 버린다
    text = re.sub(r"<(?![a-zA-Z][a-zA-Z0-9-]*[\s/>]|/[a-zA-Z]|!|\?)", "&lt;", text)
    parser = _TextExtractor()
    try:
        parser.feed(text)
        parser.close()
    except Exception:  # 깨진 HTML 이면 태그만 거칠게 제거
        return collapse_ws(re.sub(r"<[^>]+>", " ", text))
    lines = [collapse_ws(x) for x in "".join(parser.parts).split("\n")]
    return " | ".join(x for x in lines if x)


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    if "<" not in text and "&" not in text:
        return collapse_ws(text)
    out = _strip_once(text)
    if _TAGLIKE.search(out):  # 이중 이스케이프된 HTML (feedparser 가 제목에 그렇게 준다) 은 한 번 더
        out = _strip_once(out)
    return out


def title_key(title: str) -> str:
    """같은 통신사 기사가 여러 매체에 실린 경우를 잡기 위한 제목 키. ' - 매체명' 꼬리를 뗀다."""
    t = re.sub(r"\s+-\s+[^-]+$", "", title)
    return re.sub(r"\W+", " ", t).strip().lower()


# ---------------------------------------------------------------- 날짜
def to_iso_utc(entry) -> str | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc).isoformat()
            except (TypeError, ValueError):
                pass
    for key in ("published", "updated"):
        s = entry.get(key)
        if s:
            try:
                d = parsedate_to_datetime(s)
                if d.tzinfo is None:
                    d = d.replace(tzinfo=timezone.utc)
                return d.astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError, IndexError):
                pass
    return None


# ---------------------------------------------------------------- 수집
def fetch_bytes(url: str, timeout: float, retries: int) -> bytes:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": ACCEPT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            last = e
            if isinstance(e, urllib.error.HTTPError) and 400 <= e.code < 500 and e.code not in (408, 429):
                break  # 4xx 는 다시 시도해도 같다 (408/429 제외)
            if attempt < retries:
                time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"{type(last).__name__}: {last}")


def parse_items(data: bytes) -> tuple[list[dict], str | None]:
    feed = feedparser.parse(data)
    if not feed.entries and (feed.get("bozo") or not feed.get("version")):
        raise RuntimeError(
            f"피드로 인식되지 않음 (version={feed.get('version')!r}, bozo={feed.get('bozo_exception')!r}). "
            "HTML 오류 페이지일 수 있음"
        )
    warn = f"bozo: {feed.get('bozo_exception')}" if feed.get("bozo") else None
    items: list[dict] = []
    for e in feed.entries:
        title = strip_html(e.get("title"))
        link = (e.get("link") or e.get("id") or "").strip()
        if not title and not link:
            continue
        items.append(
            {
                "title": title,
                "link": link,
                "published": to_iso_utc(e),
                "summary": strip_html(e.get("summary") or e.get("description")),
            }
        )
    return items, warn


def select(items: list[dict], hours: int, now: datetime, dedup_title: bool = False) -> tuple[list[dict], int, int]:
    """link (와 dedup_title 이면 제목) 기준 중복 제거 → 시간창 필터 → published 내림차순. (kept, n_old, n_dup)

    제목 중복 제거는 Google News 용이다 (같은 통신사 기사가 여러 매체 링크로 들어온다).
    Federal Register 는 제목이 같은 별개 문서가 흔해서 쓰지 않는다."""
    cutoff = now - timedelta(hours=hours) if hours > 0 else None
    seen: set[str] = set()
    kept: list[dict] = []
    n_old = n_dup = 0
    for it in items:
        keys = ["link:" + it["link"]] if it["link"] else []
        if dedup_title and it["title"]:
            keys.append("title:" + title_key(it["title"]))
        if any(k in seen for k in keys):
            n_dup += 1
            continue
        seen.update(keys)
        if cutoff and it["published"] and datetime.fromisoformat(it["published"]) < cutoff:
            n_old += 1
            continue
        kept.append(it)  # published 없는 항목은 판단 불가 → 남긴다
    kept.sort(key=lambda x: x["published"] or "", reverse=True)
    return kept, n_old, n_dup


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="market-brief RSS 수집 → raw/YYYY-MM-DD/{source}.json")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                    help="저장 폴더 날짜 YYYY-MM-DD (기본: 오늘, 로컬 시간 기준)")
    ap.add_argument("--hours", type=int, default=None,
                    help="이 시간 이내에 발행된 항목만 저장. 0 이면 필터 없음 (기본 48, 월요일은 72)")
    ap.add_argument("--only", default="", help="쉼표로 구분한 소스 이름. 비우면 전부. 가능: " + ", ".join(SOURCE_NAMES))
    ap.add_argument("--timeout", type=float, default=30.0, help="피드당 요청 타임아웃 초 (기본 30)")
    ap.add_argument("--retries", type=int, default=2, help="실패 시 재시도 횟수 (기본 2)")
    args = ap.parse_args(argv)

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
        ap.error("--date 는 YYYY-MM-DD 형식 (0 을 채운다)")
    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        ap.error("--date 가 실제 날짜가 아님")
    if args.hours is None:
        args.hours = default_hours()
    if args.hours < 0:
        ap.error("--hours 는 0 이상")
    if args.retries < 0:
        ap.error("--retries 는 0 이상")
    if args.timeout <= 0:
        ap.error("--timeout 은 0 보다 커야 함")
    names = [n.strip() for n in args.only.split(",") if n.strip()] or list(SOURCE_NAMES)
    unknown = [n for n in names if n not in SOURCE_NAMES]
    if unknown:
        ap.error(f"모르는 소스 {unknown}. 가능: {', '.join(SOURCE_NAMES)}")

    sources = build_sources(args.hours)
    out_dir = RAW_DIR / args.date
    now = datetime.now(timezone.utc).replace(microsecond=0)
    failed: list[str] = []
    for name in names:
        url = sources[name]
        path = out_dir / f"{name}.json"
        rel = path.relative_to(REPO_ROOT)
        try:
            data = fetch_bytes(url, args.timeout, args.retries)
            items, warn = parse_items(data)
            kept, n_old, n_dup = select(items, args.hours, now, dedup_title=name.startswith("gnews_"))
            write_json(path, {
                "source": name,
                "feed_url": url,
                "fetched_at": now.isoformat(),
                "window_hours": args.hours,
                "count": len(kept),
                "items": kept,
            })
            print(f"[ok]   {name:<24} {len(kept):>4} saved  "
                  f"({len(items)} fetched, {n_old} older than {args.hours}h, {n_dup} dup) -> {rel}")
            if warn:
                print(f"       {name}: {warn}", file=sys.stderr)
            if name == "federal_register" and len(items) >= FR_FEED_CAP and n_old == 0:
                print(f"       {name}: 피드 캡 {FR_FEED_CAP}건이 전부 시간창 안. 당일 문서가 잘렸을 수 있음", file=sys.stderr)
        except Exception as e:  # 한 피드 실패가 나머지를 막지 않는다
            failed.append(name)
            if path.exists():
                print(f"[fail] {name:<24} {e}  (기존 파일 유지: {rel})", file=sys.stderr)
            else:
                write_json(path, {
                    "source": name, "feed_url": url, "fetched_at": now.isoformat(),
                    "window_hours": args.hours, "count": 0, "error": str(e), "items": [],
                })
                print(f"[fail] {name:<24} {e}  -> {rel} (error 표시 파일)", file=sys.stderr)

    if failed:
        print(f"{len(failed)}/{len(names)} failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
