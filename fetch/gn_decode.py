#!/usr/bin/env python3
"""Google News RSS 리다이렉트 링크(news.google.com/rss/articles/...)를 실제 기사 URL로 바꾼다.

  python3 fetch/gn_decode.py URL [URL ...]
  python3 fetch/gn_decode.py --raw DATE SOURCE IDX [IDX ...]    IDX 는 raw 파일 items 배열의 위치 (0부터)

- Google News 링크가 아니면(federalreserve.gov, federalregister.gov 같은 직접 링크) 그대로 돌려준다.
- 구조화된 응답(batchexecute)이 없으면 추측하지 않고 실패로 보고한다.
- 요청 사이 1.5초 간격. 429(Too Many Requests)면 20초 뒤 한 번 더 시도한다.
- 종료코드: 0 전부 성공 / 1 하나라도 실패(항목별 "ERROR ..." 줄) / 2 인자 오류.
표준 라이브러리만 쓴다. /brief 에서 structural=true 후보의 기사를 열 때 쓴다 (WebFetch 는 리다이렉트 페이지를 못 읽는다).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
ROOT = Path(__file__).resolve().parent.parent
GN_RE = re.compile(r"^https?://news\.google\.com/(?:rss/)?articles/([^/?#]+)")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PAUSE = 1.5


class DecodeError(Exception):
    pass


def _get(url: str, timeout: float, data: bytes | None = None, extra: dict | None = None) -> str:
    headers = {"User-Agent": UA, **(extra or {})}
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 1:
                time.sleep(20)
                continue
            raise
    raise DecodeError("재시도 실패")


def decode(url: str, timeout: float = 30) -> str:
    """Google News 링크면 실제 기사 URL, 아니면 입력 그대로. 실패는 예외."""
    m = GN_RE.match(url)
    if not m:
        return url
    aid = m.group(1)
    html = _get(f"https://news.google.com/articles/{aid}", timeout)
    sig = re.search(r'data-n-a-sg="([^"]+)"', html)
    ts = re.search(r'data-n-a-ts="([^"]+)"', html)
    if not sig or not ts:
        raise DecodeError("서명/타임스탬프 없음 (동의 페이지·차단·형식 변경). 다른 기사나 1차 출처를 연다")
    time.sleep(PAUSE)
    inner = json.dumps(["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1],
                                       "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0], aid, ts.group(1), sig.group(1)])
    payload = urllib.parse.urlencode({"f.req": json.dumps([[["Fbv4je", inner, None, "generic"]]])}).encode()
    resp = _get("https://news.google.com/_/DotsSplashUi/data/batchexecute", timeout, data=payload,
                extra={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
    for line in resp.split("\n"):
        if not line.startswith('[["wrb.fr"'):
            continue
        try:
            inner_s = json.loads(line)[0][2]
            arr = json.loads(inner_s) if inner_s else None
        except (ValueError, IndexError, TypeError):
            continue
        if isinstance(arr, list) and len(arr) > 1 and isinstance(arr[1], str) and arr[1].startswith("http"):
            return arr[1]
    raise DecodeError("batchexecute 응답에 기사 URL 없음")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Google News 리다이렉트 링크 → 실제 기사 URL",
                                 epilog="--raw 의 IDX 는 raw/DATE/SOURCE.json 의 items 배열 위치(0부터)다.")
    ap.add_argument("targets", nargs="+", metavar="URL|IDX", help="링크들, 또는 --raw 와 함께 items 위치(0부터)")
    ap.add_argument("--raw", nargs=2, metavar=("DATE", "SOURCE"), help="raw/DATE/SOURCE.json 의 항목 위치로 지정")
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args(argv)

    targets: list[tuple[str, str | None, str | None]] = []  # (label, url, error)
    if args.raw:
        date, source = args.raw
        if not DATE_RE.match(date):
            ap.error(f"DATE 는 YYYY-MM-DD: {date!r}")
        path = ROOT / "raw" / date / f"{source}.json"
        if not path.exists():
            ap.error(f"raw 파일 없음: {path.relative_to(ROOT)} (로컬이면 fetch.py 로 먼저 만든다)")
        items = json.loads(path.read_text(encoding="utf-8")).get("items", [])
        for t in args.targets:
            if not t.isdigit():
                targets.append((f"[{source} {t}]", None, f"위치는 0 이상의 정수여야 함: {t!r}")); continue
            i = int(t)
            if i >= len(items):
                targets.append((f"[{source} {t}]", None, f"위치 범위 밖 (items {len(items)}개, 0~{len(items) - 1})")); continue
            targets.append((f"[{source} {i}] {items[i]['title'][:80]}", items[i]["link"], None))
    else:
        for u in args.targets:
            if not re.match(r"^https?://", u):
                targets.append((u[:80], None, "URL 이 아님")); continue
            targets.append((u[:80], u, None))

    rc = 0
    first = True
    for label, url, err in targets:
        if err is None:
            if not first:
                time.sleep(PAUSE)
            first = False
            try:
                out = decode(url, args.timeout)
                out = out if GN_RE.match(url) else f"{out} (직접 링크, 변환 없음)"
            except Exception as e:  # 네트워크·형식 오류는 항목별로 보고
                out, rc = f"ERROR {type(e).__name__}: {e}", 1
        else:
            out, rc = f"ERROR {err}", 1
        print(f"{label}\n  -> {out}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
