#!/usr/bin/env python3
"""framework/*.yaml 최소 파서. 표준 라이브러리만.

fetch.py, ledger.py, scoring.py, site/build.py, .claude/commands 의 스크립트가 이 함수들을 같이 쓴다.
YAML 전체를 지원하지 않는다. 이 레포의 두 파일이 쓰는 형태만 읽는다:
  최상위키:              들여쓰기 없음, 콜론으로 끝남 (sector_map 의 방향, sources 의 소스 이름)
    하위키:              2칸 들여쓰기, 콜론으로 끝남 (sector_map 의 섹터)
      tickers: [A, B]    인라인 리스트
      note: 문장         한 줄 값
주석은 줄 첫 '#' 또는 ' #' 뒤. 값 안에 ' #' 을 쓰면 잘린다. 리스트 값 안에 쉼표는 못 쓴다.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AXES = ("기술", "사회", "정책")
SECTOR_MAP = ROOT / "framework/sector_map.yaml"
SOURCES = ROOT / "framework/sources.yaml"
TICKER = re.compile(r"[A-Z][A-Z0-9.\-]{0,6}")
SOURCE_NAME = re.compile(r"[a-z][a-z0-9_]*")


def _lines(path: Path):
    for raw in Path(path).read_text(encoding="utf-8").split("\n"):
        line = re.sub(r"\s#.*$|^#.*$", "", raw).rstrip()
        if line.strip():
            yield line


def _list(v: str) -> list[str]:
    v = v.strip()
    if not (v.startswith("[") and v.endswith("]")):
        raise ValueError(f"인라인 리스트가 아님: {v!r}")
    return [t.strip().strip("'\"") for t in v[1:-1].split(",") if t.strip()]


def load_sector_map(path: Path = SECTOR_MAP) -> dict[str, dict]:
    """{섹터: {"direction": 방향, "tickers": [...], "keywords": [...], "note": str}}. 파일 순서 유지. 형식이 어긋나면 ValueError."""
    sectors: dict[str, dict] = {}
    direction = sector = None
    for line in _lines(path):
        if re.match(r"^\S[^:]*:\s*$", line):
            direction, sector = line.strip()[:-1], None
            continue
        m = re.match(r"^  (\S[^:]*):\s*$", line)
        if m:
            if direction is None:
                raise ValueError(f"sector_map: 방향 없이 섹터가 나옴: {line.strip()!r}")
            sector = m.group(1).strip()
            if sector in sectors:
                raise ValueError(f"sector_map: 섹터 이름 중복 {sector!r}")
            sectors[sector] = {"direction": direction, "tickers": [], "keywords": [], "note": ""}
            continue
        m = re.match(r"^\s+(tickers|keywords|note):\s*(.*?)\s*$", line)
        if m and sector:
            k, v = m.groups()
            if k == "note":
                sectors[sector][k] = v
            elif k == "tickers":
                sectors[sector][k] = _list(v)
            else:
                sectors[sector][k] = [x.lower() for x in _list(v)]
    if not sectors:
        raise ValueError("sector_map 에 섹터가 없음")
    empty = [s for s, c in sectors.items() if not c["tickers"]]
    if empty:
        raise ValueError(f"sector_map: tickers 없는 섹터 {empty}")
    bad = [t for c in sectors.values() for t in c["tickers"] if not TICKER.fullmatch(t)]
    if bad:
        raise ValueError(f"sector_map: 티커 형식 이상 {bad}")
    owner: dict[str, str] = {}
    for s, c in sectors.items():
        for t in c["tickers"]:
            if t in owner:
                raise ValueError(f"sector_map: 티커 {t} 가 두 섹터에 있음 ({owner[t]}, {s}). 티커는 한 섹터에만")
            owner[t] = s
    return sectors


def directions(sectors: dict[str, dict]) -> list[tuple[str, list[str]]]:
    """[(방향, [섹터...])] 파일 순서."""
    out: dict[str, list[str]] = {}
    for s, c in sectors.items():
        out.setdefault(c["direction"], []).append(s)
    return list(out.items())


def all_tickers(sectors: dict[str, dict]) -> set[str]:
    return {t for c in sectors.values() for t in c["tickers"]}


def sector_of_ticker(sectors: dict[str, dict]) -> dict[str, str]:
    return {t: s for s, c in sectors.items() for t in c["tickers"]}


def load_sources(path: Path = SOURCES) -> list[dict]:
    """[{name, type, url, query, axis, note}]. 형식이 어긋나면 ValueError (수집 전체가 멈춘다. 소스 하나의 오류도 파일을 고쳐야 한다)."""
    out: list[dict] = []
    cur: dict | None = None
    for line in _lines(path):
        m = re.match(r"^(\S[^:]*):\s*$", line)
        if m:
            cur = {"name": m.group(1).strip(), "type": "", "url": "", "query": "", "axis": "", "note": ""}
            out.append(cur)
            continue
        m = re.match(r"^\s+(type|url|query|axis|note):\s*(.*?)\s*$", line)
        if m and cur is not None:
            cur[m.group(1)] = m.group(2)
        elif cur is None:
            raise ValueError(f"sources.yaml: 소스 이름 앞에 들여쓴 줄이 있음: {line!r}")
    if not out:
        raise ValueError("sources.yaml 에 소스가 없음")
    problems = []
    for s in out:
        if not SOURCE_NAME.fullmatch(s["name"]):
            problems.append(f"{s['name']!r}: 이름은 소문자·숫자·밑줄")
        if s["type"] == "rss":
            if not re.match(r"^https?://", s["url"]):
                problems.append(f"{s['name']}: rss 는 url 이 필요")
        elif s["type"] == "gnews":
            if not s["query"]:
                problems.append(f"{s['name']}: gnews 는 query 가 필요")
        else:
            problems.append(f"{s['name']}: type 은 rss 또는 gnews ({s['type']!r})")
        if s["axis"] not in AXES:
            problems.append(f"{s['name']}: axis 는 {' / '.join(AXES)} 중 하나 ({s['axis']!r})")
    names = [s["name"] for s in out]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        problems.append(f"소스 이름 중복 {dup}")
    if problems:
        raise ValueError("sources.yaml: " + "; ".join(problems))
    return out


if __name__ == "__main__":
    smap = load_sector_map()
    print(f"sector_map: 방향 {len(directions(smap))}개, 섹터 {len(smap)}개, 티커 {len(all_tickers(smap))}개")
    for dname, members in directions(smap):
        print(f"  {dname}: {', '.join(members)}")
    srcs = load_sources()
    print(f"sources: {len(srcs)}개 — " + ", ".join(f"{s['name']}({s['axis']})" for s in srcs))
