#!/usr/bin/env python3
"""Google News RSS 리다이렉트 링크(news.google.com/rss/articles/...)를 실제 기사 URL로 바꾼다.

  python3 fetch/gn_decode.py URL [URL ...]                 링크를 직접
  python3 fetch/gn_decode.py --raw 2026-09-10 gnews_tariff 86 50   raw 파일의 항목 번호로

표준 라이브러리만 쓴다. Google 의 batchexecute 엔드포인트를 호출하므로 네트워크가 필요하다.
/brief 에서 structural=true 후보의 기사를 열 때 쓴다 (WebFetch 는 리다이렉트 페이지를 못 읽는다).
"""
from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
ROOT = Path(__file__).resolve().parent.parent


def decode(gn_url: str, timeout: float = 30) -> str | None:
    m = re.search(r"/articles/([^/?]+)", gn_url)
    if not m:
        return None
    aid = m.group(1)
    req = urllib.request.Request(f"https://news.google.com/articles/{aid}", headers={"User-Agent": UA})
    html = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
    sig = re.search(r'data-n-a-sg="([^"]+)"', html)
    ts = re.search(r'data-n-a-ts="([^"]+)"', html)
    if not sig or not ts:  # 옛 형식: 페이지 안의 외부 링크
        m2 = re.search(r'<a[^>]+href="(https?://(?!news\.google)[^"]+)"', html)
        return m2.group(1) if m2 else None
    inner = json.dumps(["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1],
                                       "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0], aid, ts.group(1), sig.group(1)])
    payload = json.dumps([[["Fbv4je", inner, None, "generic"]]])
    data = urllib.parse.urlencode({"f.req": payload}).encode()
    req = urllib.request.Request("https://news.google.com/_/DotsSplashUi/data/batchexecute", data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "User-Agent": UA})
    resp = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
    for line in resp.split("\n"):
        if line.startswith('[["wrb.fr"'):
            try:
                inner_s = json.loads(line)[0][2]
                arr = json.loads(inner_s) if inner_s else None
            except (ValueError, IndexError, TypeError):
                continue
            if isinstance(arr, list) and len(arr) > 1 and isinstance(arr[1], str) and arr[1].startswith("http"):
                return arr[1]
    m3 = re.search(r'https?://(?!news\.google)[^"\\\s]+', resp)
    return m3.group(0) if m3 else None


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    targets: list[tuple[str, str]] = []
    if argv[0] == "--raw":
        if len(argv) < 4:
            print("--raw DATE SOURCE IDX [IDX ...]", file=sys.stderr)
            return 2
        date, source, idxs = argv[1], argv[2], argv[3:]
        items = json.loads((ROOT / "raw" / date / f"{source}.json").read_text(encoding="utf-8"))["items"]
        for i in idxs:
            it = items[int(i)]
            targets.append((f"[{source} {i}] {it['title'][:80]}", it["link"]))
    else:
        targets = [(u[:80], u) for u in argv]
    rc = 0
    for label, url in targets:
        try:
            out = decode(url)
        except Exception as e:  # 네트워크·형식 오류는 줄 단위로 보고
            out, rc = f"ERROR {type(e).__name__}: {e}", 1
        if out is None:
            out, rc = "ERROR 디코딩 실패", 1
        print(f"{label}\n  -> {out}")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
