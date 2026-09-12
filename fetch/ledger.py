#!/usr/bin/env python3
"""장부(ledger/*.jsonl) 검증·추가. 장부에 쓰는 유일한 수단이다.

  python3 fetch/ledger.py --ledger signals   --date 2026-09-13 --rows /tmp/rows.json            검증 + 30일 집계
  python3 fetch/ledger.py --ledger signals   --date 2026-09-13 --rows /tmp/rows.json --append   검증 통과 시 append
  python3 fetch/ledger.py --ledger companies --date 2026-09-13 --rows /tmp/company_rows.json [--append]

rows 파일은 JSON 배열이다. `[]` 이면 집계만 한다. 스키마는 CLAUDE.md "시그널 스키마", "기업 관찰 스키마".
검증에 하나라도 걸리면 아무것도 쓰지 않는다. 기존 줄은 어떤 경우에도 고치지 않는다.
출력의 `skip 중복` 은 이미 장부에 있는 사건, `경고 유사 사건` 은 최근 7일 같은 테마 행과 팩트가 많이 겹치는 것.
종료 코드: 0 통과 / 1 검증 실패 / 2 인자·환경 오류
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import AXES, ROOT, all_tickers, load_companies, load_sector_map  # noqa: E402

LEDGERS = {"signals": ROOT / "ledger/signals.jsonl", "companies": ROOT / "ledger/companies.jsonl"}
KEYS = {
    "signals": ["date", "axis", "theme", "fact", "source", "structural", "sectors", "direction", "confidence", "note",
                "horizon", "impact", "channel", "thesis", "reverses"],
    "companies": ["date", "company", "axis", "fact", "source", "structural", "direction", "confidence", "note", "tickers"],
}
HORIZON, CHANNEL = ("분기", "1년", "다년"), ("실적", "멀티플", "수급")
BAD = re.compile(r"사라(?![지진질져졌짐])|팔아라|지금이 기회|매수 추천|매도 추천|사야 한다|팔아야 한다")
NOTE = re.compile(r"^(?:\[충돌: (정치권력|기술권력|자본권력|코인) vs (정치권력|기술권력|자본권력|코인)\] )?(커짐|작아짐|유보)(?![가-힣])")
URL = re.compile(r"^https?://[^\s/]+\.[^\s/]+\S*$")
THESIS_TAG = re.compile(r"T\d+[+-]")
COMPANY_DAILY_CAP = 3


def load_existing(path: Path) -> tuple[list[dict], dict[int, dict]]:
    rows, by_line = [], {}
    if not path.exists():
        return rows, by_line
    for n, l in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        if not l.strip():
            continue
        try:
            d = json.loads(l)
        except json.JSONDecodeError as e:
            sys.exit(f"{path.name} {n}번째 줄 JSON 파싱 실패: {e}. 장부는 수정 금지. Ken 에게 알린다")
        rows.append(d)
        by_line[n] = d
    return rows, by_line


def grams(t: str) -> set[str]:
    t = re.sub(r"[^가-힣a-z0-9]", "", t.lower())
    return {t[i:i + 2] for i in range(len(t) - 1)}


def is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def validate_signals(rows: list, date: str, today: datetime.date, existing: list[dict], by_line: dict[int, dict]) -> tuple[list[dict], list[str], list[str]]:
    themes = load_sector_map()
    tickers = all_tickers(themes)
    print("sector_map:", ", ".join(f"{a} {sum(1 for x, _ in themes.values() if x == a)}테마" for a in AXES), f"/ 티커 {len(tickers)}개")
    tp = ROOT / "framework/thesis.md"
    thesis_ids = set(re.findall(r"^## (T\d+)\b", tp.read_text(encoding="utf-8"), re.M)) if tp.exists() else set()
    seen = {(d["source"], d["theme"]): d["date"] for d in existing}
    recent = [d for d in existing if (today - datetime.timedelta(days=7)).isoformat() <= d["date"] <= date]
    if recent:
        print(f"최근 7일 장부 {len(recent)}건 (같은 사건이면 올리지 않는다):")
        for d in recent:
            print(f"  - {d['date']} [{d['axis']}/{d['theme']}] {d['fact'][:80]}")
    errors, todo, skipped = [], [], []
    keys = KEYS["signals"]
    for i, r in enumerate(rows):
        p = f"rows[{i}]"
        if not isinstance(r, dict) or set(r) != set(keys):
            errors.append(f"{p}: 키 구성이 스키마와 다름 {sorted(set(r) ^ set(keys)) if isinstance(r, dict) else type(r).__name__}")
            continue
        r = dict(r)
        for k in ("date", "axis", "theme", "fact", "source", "note"):
            r[k] = " ".join(str(r[k]).split())  # U+2028 등 줄바꿈류 제거. 장부는 한 줄 = 한 JSON
        if r["date"] != date:
            errors.append(f"{p}: date {r['date']!r} != --date {date!r}")
        if r["structural"] is not True:
            errors.append(f"{p}: structural=true 만 4축 장부에 올림")
        if r["axis"] not in AXES:
            errors.append(f"{p}: axis {r['axis']!r}")
        if r["theme"] not in themes:
            errors.append(f"{p}: theme {r['theme']!r} 가 sector_map 에 없음")
        elif themes[r["theme"]][0] != r["axis"]:
            errors.append(f"{p}: theme {r['theme']!r} 는 {themes[r['theme']][0]} 축")
        s = r["sectors"]
        if not isinstance(s, list) or not (1 <= len(s) <= 3) or len(set(s)) != len(s):
            errors.append(f"{p}: sectors 는 서로 다른 티커 1~3개")
        else:
            for t in s:
                if t not in tickers:
                    errors.append(f"{p}: 티커 {t} 가 sector_map 에 없음")
                elif r["theme"] in themes and t not in themes[r["theme"]][1]:
                    print(f"경고 {p}: 티커 {t} 는 테마 {r['theme']!r} 밖 (맵에는 있음). note 에 이유가 있어야 한다")
        if r["direction"] not in ("+", "-", "±"):
            errors.append(f"{p}: direction 은 + / - / ±")
        if r["confidence"] not in (0.3, 0.6, 0.8):
            errors.append(f"{p}: confidence 는 0.3 / 0.6 / 0.8")
        if not URL.match(r["source"]):
            errors.append(f"{p}: source 가 URL 이 아님")
        if not r["fact"]:
            errors.append(f"{p}: fact 비어 있음")
        m = NOTE.match(r["note"])
        if not m:
            errors.append(f"{p}: note 는 '[충돌: A vs B] '(선택) + '커짐.'|'작아짐.'|'유보.' 로 시작해야 함")
        elif m.group(1) and (m.group(1) == m.group(2) or AXES.index(m.group(1)) > AXES.index(m.group(2))):
            errors.append(f"{p}: 충돌 태그는 서로 다른 축을 {' > '.join(AXES)} 순서로")
        if BAD.search(r["fact"] + " " + r["note"]):
            errors.append(f"{p}: 매매 지시 표현 금지")
        if r["horizon"] not in HORIZON:
            errors.append(f"{p}: horizon 은 분기 / 1년 / 다년")
        if not is_int(r["impact"]) or r["impact"] not in (1, 2, 3):
            errors.append(f"{p}: impact 는 1 / 2 / 3")
        if r["channel"] not in CHANNEL:
            errors.append(f"{p}: channel 은 실적 / 멀티플 / 수급")
        th = r["thesis"]
        if not isinstance(th, list) or len(set(th)) != len(th) or any(not (isinstance(t, str) and THESIS_TAG.fullmatch(t) and t[:-1] in thesis_ids) for t in th):
            errors.append(f"{p}: thesis 는 ['T1+', 'T3-'] 형식, 번호는 framework/thesis.md 에 있는 것만 {sorted(thesis_ids)}")
        rv = r["reverses"]
        if rv is not None:
            if not is_int(rv) or rv not in by_line:
                errors.append(f"{p}: reverses 는 장부의 기존 줄 번호(1~{max(by_line, default=0)}) 또는 null")
            else:
                prev = by_line[rv]
                print(f"번복 {p}: {rv}번 줄 [{prev['axis']}/{prev['theme']}] {prev['fact'][:70]}" + ("" if prev["theme"] == r["theme"] else f"  경고: 테마가 다름 ({prev['theme']} vs {r['theme']})"))
        g = grams(r["fact"])
        for d in recent:
            if d["theme"] == r["theme"] and d["source"] != r["source"]:
                h = grams(d["fact"])
                j = len(g & h) / max(1, len(g | h))
                if j >= 0.35:
                    print(f"경고 유사 사건 {p}: {d['date']} 장부 행과 팩트 겹침 {j:.2f}. 같은 사건이면 rows 에서 뺀다: {d['fact'][:70]}")
        key = (r["source"], r["theme"])
        if key in seen:
            skipped.append(f"{p}: 이미 {seen[key]} 에 기록됨 ({r['theme']}, {r['source'][:70]})")
            continue
        seen[key] = date
        todo.append({k: r[k] for k in keys})
    return todo, errors, skipped


def tally_signals(rows: list[dict], today: datetime.date) -> None:
    cut = today - datetime.timedelta(days=30)
    c: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for d in rows:
        try:
            dd = datetime.date.fromisoformat(d["date"])
        except (ValueError, KeyError):
            continue
        if cut < dd <= today:
            c[d["axis"]][d["direction"]] += 1
    print("\n30일 누적")
    for a in AXES:
        print(f"- {a}: {sum(c[a].values())}건 (+{c[a]['+']} / -{c[a]['-']} / ±{c[a]['±']})")


def validate_companies(rows: list, date: str, today: datetime.date, existing: list[dict]) -> tuple[list[dict], list[str], list[str]]:
    comp = {}
    for c in load_companies():
        if c["error"]:
            print(f"경고 companies.yaml {c['name']}: {c['error']}")
        comp[c["name"]] = c["tickers"]
    if not comp:
        sys.exit("companies.yaml 에 기업이 없음")
    try:
        map_tickers = all_tickers(load_sector_map())
    except ValueError as e:
        print(f"경고 sector_map 파싱 실패, 티커 확인 생략: {e}")
        map_tickers = None
    seen = {(d["company"], d["source"]): d["date"] for d in existing}
    per_co = collections.Counter(d["company"] for d in existing if d.get("date") == date)
    errors, todo, skipped = [], [], []
    keys = KEYS["companies"]
    for i, r in enumerate(rows):
        p = f"rows[{i}]"
        if not isinstance(r, dict) or set(r) != set(keys):
            errors.append(f"{p}: 키 구성이 스키마와 다름 {sorted(set(r) ^ set(keys)) if isinstance(r, dict) else type(r).__name__}")
            continue
        r = dict(r)
        for k in ("date", "company", "axis", "fact", "source", "note"):
            r[k] = " ".join(str(r[k]).split())
        if r["date"] != date:
            errors.append(f"{p}: date {r['date']!r} != --date {date!r}")
        if r["company"] not in comp:
            errors.append(f"{p}: company 는 companies.yaml 의 {sorted(comp)} 중 하나")
        if r["axis"] not in AXES:
            errors.append(f"{p}: axis {r['axis']!r}")
        if not isinstance(r["structural"], bool):
            errors.append(f"{p}: structural 은 true/false")
        if r["direction"] not in ("+", "-", "±"):
            errors.append(f"{p}: direction 은 회사 기준 + / - / ±")
        if r["confidence"] not in (0.3, 0.6, 0.8):
            errors.append(f"{p}: confidence 는 0.3 / 0.6 / 0.8")
        elif r["structural"] is True and r["confidence"] < 0.6:
            errors.append(f"{p}: structural=true 는 확인 등급을 거쳐 0.6 이상")
        if not URL.match(r["source"]):
            errors.append(f"{p}: source 가 URL 이 아님")
        if not r["fact"]:
            errors.append(f"{p}: fact 비어 있음")
        m = NOTE.match(r["note"])
        if not m:
            errors.append(f"{p}: note 는 '[충돌: A vs B] '(선택) + '커짐.'|'작아짐.'|'유보.' 로 시작해야 함")
        t = r["tickers"]
        if not isinstance(t, list) or len(set(t)) != len(t) or any(x not in comp.get(r["company"], []) for x in t):
            errors.append(f"{p}: tickers 는 companies.yaml 의 그 기업 티커만 ({comp.get(r['company'])})")
        elif map_tickers is not None:
            for x in t:
                if x not in map_tickers:
                    print(f"경고 {p}: 티커 {x} 가 sector_map 에 없음 (CLAUDE.md 규칙 4). companies.yaml 과 맵을 맞춘다")
        if BAD.search(r["fact"] + " " + r["note"]):
            errors.append(f"{p}: 매매 지시 표현 금지")
        per_co[r["company"]] += 1
        if per_co[r["company"]] > COMPANY_DAILY_CAP:
            errors.append(f"{p}: {r['company']} 는 하루 최대 {COMPANY_DAILY_CAP}건 (이미 기록된 행 포함)")
        key = (r["company"], r["source"])
        if key in seen:
            skipped.append(f"{p}: 이미 {seen[key]} 에 기록됨 ({r['company']}, {r['source'][:70]})")
            continue
        seen[key] = date
        todo.append({k: r[k] for k in keys})
    return todo, errors, skipped


def tally_companies(rows: list[dict], today: datetime.date) -> None:
    cut = today - datetime.timedelta(days=30)
    names = [c["name"] for c in load_companies()]
    print("\n기업 관찰 30일 누적 (구조적/전체)")
    for c in names:
        s = [d for d in rows if d.get("company") == c and cut < datetime.date.fromisoformat(d["date"]) <= today]
        print(f"- {c}: {sum(1 for d in s if d['structural'] is True)}/{len(s)}건. " + ", ".join(f"{a} {sum(1 for d in s if d['axis'] == a)}" for a in AXES))


def append(path: Path, todo: list[dict], n_existing: int) -> None:
    path.parent.mkdir(exist_ok=True)
    need_nl = path.exists() and path.stat().st_size > 0 and not path.read_bytes().endswith(b"\n")
    with open(path, "a", encoding="utf-8") as f:
        if need_nl:
            f.write("\n")
        for r in todo:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tail = [l for l in path.read_text(encoding="utf-8").split("\n") if l.strip()][-len(todo):]
    assert [json.loads(l) for l in tail] == todo, "append 검증 실패"
    print(f"appended {len(todo)} ({path.name} 총 {n_existing + len(todo)}줄)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="장부 검증·추가")
    ap.add_argument("--ledger", choices=sorted(LEDGERS), required=True)
    ap.add_argument("--date", required=True, help="YYYY-MM-DD. 모든 행의 date 와 같아야 한다")
    ap.add_argument("--rows", required=True, help="JSON 배열 파일. [] 이면 집계만")
    ap.add_argument("--append", action="store_true", help="검증 통과 시 장부에 append")
    args = ap.parse_args(argv)
    if not (ROOT / "CLAUDE.md").exists():
        return sys.exit("레포 루트를 찾지 못함")
    try:
        today = datetime.date.fromisoformat(args.date)
    except ValueError:
        ap.error("--date 는 YYYY-MM-DD")
    try:
        rows = json.loads(Path(args.rows).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        ap.error(f"--rows 읽기 실패: {e}")
    if not isinstance(rows, list):
        ap.error("--rows 는 JSON 배열이어야 한다")
    path = LEDGERS[args.ledger]
    existing, by_line = load_existing(path)
    if args.ledger == "signals":
        todo, errors, skipped = validate_signals(rows, args.date, today, existing, by_line)
    else:
        todo, errors, skipped = validate_companies(rows, args.date, today, existing)
    for s in skipped:
        print("skip 중복:", s)
    if errors:
        print("검증 실패. append 안 함:\n  " + "\n  ".join(errors))
        return 1
    if args.append and todo:
        append(path, todo, len(existing))
    elif args.append:
        print("appended 0")
    else:
        print(f"검증 통과 {len(todo)}건 (--append 없음, 장부에는 아직 안 씀)")
    (tally_signals if args.ledger == "signals" else tally_companies)(existing + todo, today)
    return 0


if __name__ == "__main__":
    sys.exit(main())
