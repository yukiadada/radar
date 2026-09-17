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
        m = re.match(r"^\s+(\S[^:]*):\s*(.*?)\s*$", line)
        if not m or not sector:
            raise ValueError(f"sector_map: 읽을 수 없는 줄 {line.strip()!r}")
        k, v = m.group(1).strip(), m.group(2)
        if k == "note":
            sectors[sector][k] = v
        elif k == "tickers":
            sectors[sector][k] = _list(v)
        elif k == "keywords":
            sectors[sector][k] = [x.lower() for x in _list(v)]
        else:
            raise ValueError(f"sector_map: {sector!r} 에 모르는 키 {k!r} (tickers / keywords / note 만)")
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


def load_sources(path: Path = SOURCES) -> list[dict]:
    """[{name, type, url, query, axis, note, ua, error}]. 항목 하나의 문제는 그 항목의 error 에 적어 돌려주고(fetch.py 가 그 소스만 건너뛴다),
    파일 전체의 문제(소스 없음, 이름 중복, 들여쓰기 오류)만 ValueError. ua 는 빈 값(기본 UA) 또는 browser."""
    out: list[dict] = []
    cur: dict | None = None
    for line in _lines(path):
        m = re.match(r"^(\S[^:]*):\s*$", line)
        if m:
            cur = {"name": m.group(1).strip(), "type": "", "url": "", "query": "", "axis": "", "note": "", "ua": "", "error": ""}
            out.append(cur)
            continue
        m = re.match(r"^\s+(\S[^:]*):\s*(.*?)\s*$", line)
        if cur is None or not m:
            raise ValueError(f"sources.yaml: 읽을 수 없는 줄 {line.strip()!r}")
        k, v = m.group(1).strip(), m.group(2)
        if k in ("type", "url", "query", "axis", "note", "ua"):
            cur[k] = v
        else:
            cur["error"] = f"모르는 키 {k!r}"
    if not out:
        raise ValueError("sources.yaml 에 소스가 없음")
    for s in out:
        problems = [s["error"]] if s["error"] else []
        if not SOURCE_NAME.fullmatch(s["name"]):
            problems.append("이름은 소문자·숫자·밑줄")
        if s["type"] == "rss":
            if not re.match(r"^https?://", s["url"]):
                problems.append("rss 는 url 이 필요")
        elif s["type"] == "gnews":
            if not s["query"]:
                problems.append("gnews 는 query 가 필요")
        else:
            problems.append(f"type 은 rss 또는 gnews ({s['type']!r})")
        if s["axis"] not in AXES:
            problems.append(f"axis 는 {' / '.join(AXES)} 중 하나 ({s['axis']!r})")
        if s["ua"] not in ("", "browser"):
            problems.append(f"ua 는 비우거나 browser ({s['ua']!r})")
        s["error"] = "; ".join(problems)
    names = [s["name"] for s in out]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ValueError(f"sources.yaml: 소스 이름 중복 {dup}")
    return out


if __name__ == "__main__":
    smap = load_sector_map()
    print(f"sector_map: 방향 {len(directions(smap))}개, 섹터 {len(smap)}개, 티커 {len(all_tickers(smap))}개")
    for dname, members in directions(smap):
        print(f"  {dname}: {', '.join(members)}")
    srcs = load_sources()
    print(f"sources: {len(srcs)}개 — " + ", ".join(f"{s['name']}({s['axis']})" + (f" 오류: {s['error']}" if s["error"] else "") for s in srcs))
