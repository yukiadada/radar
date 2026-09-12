#!/usr/bin/env python3
"""framework/*.yaml 최소 파서. 표준 라이브러리만.

fetch.py, site/build.py, fetch/ledger.py, .claude/commands 의 스크립트가 이 함수들을 같이 쓴다.
YAML 전체를 지원하지 않는다. 이 레포의 두 파일이 쓰는 형태만 읽는다:
  최상위키:              들여쓰기 없음, 콜론으로 끝남 (sector_map 의 축, companies 의 기업)
    하위키:              2칸 들여쓰기, 콜론으로 끝남 (sector_map 의 테마)
      tickers: [A, B]    인라인 리스트
      note: 문장
주석은 줄 첫 '#' 또는 ' #' 뒤. 값 안에 ' #' 을 쓰면 잘린다.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AXES = ("정치권력", "기술권력", "자본권력", "코인")
SECTOR_MAP = ROOT / "framework/sector_map.yaml"
COMPANIES = ROOT / "framework/companies.yaml"
TICKER = re.compile(r"[A-Z][A-Z0-9.\-]{0,6}")
SOURCE = re.compile(r"gnews_co_[a-z0-9_]+")


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


def load_sector_map(path: Path = SECTOR_MAP) -> dict[str, tuple[str, list[str]]]:
    """{테마: (축, [티커])}. 형식이 어긋나면 ValueError."""
    themes: dict[str, tuple[str, list[str]]] = {}
    axis = theme = None
    n_theme = 0
    for line in _lines(path):
        if re.match(r"^\S[^:]*:\s*$", line):
            axis, theme = line.strip()[:-1], None
            continue
        m = re.match(r"^  (\S[^:]*):\s*$", line)
        if m:
            theme, n_theme = m.group(1).strip(), n_theme + 1
            continue
        m = re.match(r"^\s+tickers:\s*(\[.*\])\s*$", line)
        if m and theme and axis:
            themes[theme] = (axis, _list(m.group(1)))
    axes = {a for a, _ in themes.values()}
    if axes != set(AXES):
        raise ValueError(f"sector_map 축 파싱 실패: {sorted(axes)}")
    if len(themes) != n_theme:
        raise ValueError(f"테마 {n_theme}개 중 {len(themes)}개만 파싱됨. sector_map.yaml 형식 확인")
    bad = [t for _, ts in themes.values() for t in ts if not TICKER.fullmatch(t)]
    if bad:
        raise ValueError(f"티커 형식 이상: {bad}")
    return themes


def all_tickers(themes: dict[str, tuple[str, list[str]]]) -> set[str]:
    return {t for _, ts in themes.values() for t in ts}


def load_companies(path: Path = COMPANIES) -> list[dict]:
    """[{name, source, query, tickers, note, error}]. 항목 하나의 문제는 그 항목의 error 에 적어 돌려주고,
    파일 전체의 문제(이름 중복, 들여쓰기 오류)만 ValueError. 파일이 없으면 []."""
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict] = []
    cur: dict | None = None
    for line in _lines(p):
        m = re.match(r"^(\S[^:]*):\s*$", line)
        if m:
            cur = {"name": m.group(1).strip(), "source": "", "query": "", "tickers": [], "note": "", "error": ""}
            out.append(cur)
            continue
        m = re.match(r"^\s+(source|query|tickers|note):\s*(.*?)\s*$", line)
        if m and cur is not None:
            k, v = m.groups()
            if k == "tickers":
                try:
                    cur[k] = _list(v)
                except ValueError as e:
                    cur["error"] = str(e)
            else:
                cur[k] = v
        elif cur is None:
            raise ValueError(f"companies.yaml: 최상위 키 앞에 들여쓴 줄이 있음: {line!r}")
    for c in out:
        problems = [c["error"]] if c["error"] else []
        if not SOURCE.fullmatch(c["source"]):
            problems.append(f"source 는 gnews_co_<이름> 형식이어야 함: {c['source']!r}")
        if not c["query"]:
            problems.append("query 없음")
        bad = [t for t in c["tickers"] if not TICKER.fullmatch(t)]
        if bad:
            problems.append(f"티커 형식 이상: {bad}")
        c["error"] = "; ".join(problems)
    names = [c["name"] for c in out]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ValueError(f"companies.yaml: 기업 이름 중복 {dup}")
    return out


if __name__ == "__main__":
    themes = load_sector_map()
    print(f"sector_map: {len(themes)}테마, 티커 {len(all_tickers(themes))}개")
    for c in load_companies():
        print(f"company {c['name']}: source={c['source']} tickers={c['tickers']}" + (f"  오류: {c['error']}" if c["error"] else ""))
