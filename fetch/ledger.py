#!/usr/bin/env python3
"""장부(ledger/signals.jsonl) 검증·추가. 장부에 쓰는 유일한 수단이다.

  python3 fetch/ledger.py --date 2026-09-18 --rows /tmp/rows.json            검증 + 30일 집계 + 섹터 정렬 표(누적)
  python3 fetch/ledger.py --date 2026-09-18 --rows /tmp/rows.json --append   검증 통과 시 append

rows 파일은 JSON 배열이다. `[]` 이면 집계만 한다. 스키마는 CLAUDE.md "시그널 스키마".
검증에 하나라도 걸리면 아무것도 쓰지 않는다. 기존 줄은 어떤 경우에도 고치지 않는다.
출력의 `skip 중복` 은 이미 장부에 있는 사건(같은 source, 같은 sector), `경고 유사 사건` 은 최근 7일 같은 섹터 행과 팩트가 많이 겹치는 것.
종료 코드: 0 통과 / 1 검증 실패 / 2 인자·환경 오류 또는 장부·sector_map 이 깨져 읽을 수 없음
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
from config import AXES, ROOT, all_tickers, load_sector_map  # noqa: E402
from scoring import PARAMS, alignment, attach_deltas, board_table, first_sentence, in_window, is_int, series, span_text  # noqa: E402

LEDGER = ROOT / "ledger/signals.jsonl"
KEYS = ["date", "axis", "sector", "fact", "source", "structural", "tickers", "direction", "confidence", "note",
        "horizon", "impact", "channel", "reverses"]
HORIZON, CHANNEL = ("분기", "1년", "다년"), ("실적", "멀티플", "수급")
BAD = re.compile(r"사라(?![지진질져졌짐])|팔아라|지금이 기회|매수 추천|매도 추천|사야 한다|팔아야 한다")
URL = re.compile(r"^https?://[^\s/]+\.[^\s/]+\S*$")
VERIFY_SUFFIX = " 확인: 검색 교차"
FIRST_WARN, FIRST_MAX = 55, 90   # 팩트 첫 문장 길이. CLAUDE.md "40자 안팎" 규칙


def load_existing(path: Path = LEDGER, warnings: list[str] | None = None) -> tuple[list[dict], dict[int, dict]]:
    """[행], {줄 번호: 행}. 행에 line(줄 번호)을 붙인다 (파일에는 없는 파생 필드).
    JSON 이 깨졌거나 date 가 ISO 가 아닌 줄은 warnings 가 주어지면 거기 적고 건너뛰고(사이트 빌드), 아니면 ValueError (장부 추가는 멈춘다)."""
    rows, by_line = [], {}
    if not path.exists():
        return rows, by_line
    for n, l in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        if not l.strip():
            continue
        try:
            r = json.loads(l)
            if not isinstance(r, dict):
                raise ValueError("JSON 객체가 아님")
            datetime.date.fromisoformat(str(r.get("date")))
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            msg = f"{path.name} {n}번째 줄 읽기 실패: {e}. 장부는 수정 금지. Ken 에게 알린다"
            if warnings is None:
                raise ValueError(msg) from None
            warnings.append(msg)
            continue
        r["line"] = n
        rows.append(r)
        by_line[n] = r
    return rows, by_line


def grams(t: str) -> set[str]:
    t = re.sub(r"[^가-힣a-z0-9]", "", t.lower())
    return {t[i:i + 2] for i in range(len(t) - 1)}


def validate(rows: list, date: str, today: datetime.date, existing: list[dict], by_line: dict[int, dict], smap: dict) -> tuple[list[dict], list[str], list[str]]:
    tickers = all_tickers(smap)
    print(f"sector_map: 섹터 {len(smap)}개, 티커 {len(tickers)}개")
    seen = {(r["source"], r["sector"]): r["date"] for r in existing}
    recent, _ = in_window(existing, today, 7)
    if recent:
        print(f"최근 7일 장부 {len(recent)}건 (같은 사건이면 올리지 않는다):")
        for r in recent:
            print(f"  - {r['date']} [{r['axis']}/{r['sector']}] {r['fact'][:80]}")
    errors, todo, skipped = [], [], []
    for i, r in enumerate(rows):
        p = f"rows[{i}]"
        if not isinstance(r, dict) or set(r) != set(KEYS):
            errors.append(f"{p}: 키 구성이 스키마와 다름 {sorted(set(r) ^ set(KEYS)) if isinstance(r, dict) else type(r).__name__}")
            continue
        r = dict(r)
        for k in ("date", "axis", "sector", "fact", "source", "note"):
            r[k] = " ".join(str(r[k]).split())  # U+2028 등 줄바꿈류 제거. 장부는 한 줄 = 한 JSON
        if r["date"] != date:
            errors.append(f"{p}: date {r['date']!r} != --date {date!r}")
        if r["structural"] is not True:
            errors.append(f"{p}: structural=true 만 장부에 올림")
        if r["axis"] not in AXES:
            errors.append(f"{p}: axis 는 {' / '.join(AXES)} 중 하나 ({r['axis']!r})")
        if r["sector"] not in smap:
            errors.append(f"{p}: sector {r['sector']!r} 가 sector_map 에 없음")
        t = r["tickers"]
        if not isinstance(t, list) or not (1 <= len(t) <= 3) or len(set(t)) != len(t):
            errors.append(f"{p}: tickers 는 서로 다른 티커 1~3개")
        else:
            for x in t:
                if x not in tickers:
                    errors.append(f"{p}: 티커 {x} 가 sector_map 에 없음")
                elif r["sector"] in smap and x not in smap[r["sector"]]["tickers"]:
                    print(f"경고 {p}: 티커 {x} 는 섹터 {r['sector']!r} 밖 (맵에는 있음). note 에 이유가 있어야 한다")
        if r["direction"] not in ("+", "-", "±"):
            errors.append(f"{p}: direction 은 + / - / ± (섹터 기준)")
        if r["confidence"] not in (0.3, 0.6, 0.8):
            errors.append(f"{p}: confidence 는 0.3 / 0.6 / 0.8")
        elif r["confidence"] < 0.6:
            errors.append(f"{p}: structural=true 는 확인 등급을 거쳐 0.6 이상")
        if not URL.match(r["source"]):
            errors.append(f"{p}: source 가 URL 이 아님")
        if not r["fact"]:
            errors.append(f"{p}: fact 비어 있음")
        else:
            fs = first_sentence(r["fact"])
            if len(fs) > FIRST_MAX:
                errors.append(f"{p}: fact 첫 문장이 {len(fs)}자. {FIRST_MAX}자 이하로 '누가 무엇을 했다'만 쓰고 번호·시각·세부 숫자는 두 번째 문장부터 (사이트 카드 제목)")
            elif len(fs) > FIRST_WARN:
                print(f"경고 {p}: fact 첫 문장이 {len(fs)}자 (40자 안팎 권장): {fs[:60]}…")
        if not r["note"]:
            errors.append(f"{p}: note 비어 있음 (왜 이 축이 이 섹터를 밀거나 막는지 한 줄)")
        elif VERIFY_SUFFIX.strip() in r["note"] and not r["note"].endswith(VERIFY_SUFFIX.strip()):
            errors.append(f"{p}: note 의 '{VERIFY_SUFFIX.strip()}' 뒤에는 아무것도 붙이지 않는다 (확인 등급 접미어는 맨 끝)")
        if BAD.search(r["fact"] + " " + r["note"]):
            errors.append(f"{p}: 매매 지시 표현 금지")
        if r["horizon"] not in HORIZON:
            errors.append(f"{p}: horizon 은 분기 / 1년 / 다년")
        if not is_int(r["impact"]) or r["impact"] not in (1, 2, 3):
            errors.append(f"{p}: impact 는 1 / 2 / 3")
        if r["channel"] not in CHANNEL:
            errors.append(f"{p}: channel 은 실적 / 멀티플 / 수급")
        rv = r["reverses"]
        if rv is not None:
            if not is_int(rv) or rv not in by_line:
                errors.append(f"{p}: reverses 는 장부의 기존 줄 번호(1~{max(by_line, default=0)}) 또는 null")
            else:
                prev = by_line[rv]
                print(f"번복 {p}: {rv}번 줄 [{prev.get('axis')}/{prev.get('sector')}] {str(prev.get('fact', ''))[:70]}" +
                      ("" if prev.get("sector") == r["sector"] else f"  경고: 섹터가 다름 ({prev.get('sector')} vs {r['sector']})"))
                if prev.get("direction") == r["direction"]:
                    errors.append(f"{p}: reverses 는 이전 줄과 반대 방향이어야 함 ({rv}번 줄도 {r['direction']}). 번복이 아니면 null")
        g = grams(r["fact"])
        for x in recent:
            if x["sector"] == r["sector"] and x["source"] != r["source"]:
                h = grams(x["fact"])
                j = len(g & h) / max(1, len(g | h))
                if j >= 0.35:
                    print(f"경고 유사 사건 {p}: {x['date']} 장부 행과 팩트 겹침 {j:.2f}. 같은 사건이면 rows 에서 뺀다: {x['fact'][:70]}")
        key = (r["source"], r["sector"])
        if key in seen:
            skipped.append(f"{p}: 이미 {seen[key]} 에 기록됨 ({r['sector']}, {r['source'][:70]})")
            continue
        seen[key] = date
        todo.append({k: r[k] for k in KEYS})
    return todo, errors, skipped


def tally(rows: list[dict], today: datetime.date, smap: dict) -> str:
    """브리프 "30일 누적"·"섹터 정렬" 절에 그대로 붙이는 텍스트. 30일 누적은 새로 들어온 건수, 섹터 정렬은 살아 있는 시그널의 누적(유효기간 기준).
    append 전에 계산해 둔다 (계산이 실패해도 장부에 쓰기 전에 멈추도록)."""
    w, span = in_window(rows, today, 30)
    c: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for r in w:
        c[r.get("axis")][r.get("direction")] += 1
    out = ["", "30일 누적"]
    for a in AXES:
        out.append(f"- {a}: {sum(c[a].values())}건 (+{c[a]['+']} / -{c[a]['-']} / ±{c[a]['±']})")
    board = attach_deltas(alignment(rows, today, None, smap), series(rows, today, None, PARAMS["delta_days"] + 1, smap))
    out.append("")
    out.append(f"섹터 정렬 (누적. {span_text(board)}. 신호 있는 섹터만, 정렬 % 높은 순. 축 값은 −1~+1, 7일 변화는 %p)")
    out.extend(board_table(board))
    dirs = [x for x in board["directions"] if x["n"]]
    if dirs:
        out.append("- 방향: " + ", ".join(f"{x['direction']} {x['score']}%" for x in sorted(dirs, key=lambda x: -x["score"])))
    if board["orphan_total"]:
        out.append(f"- 경고: sector_map 에 없는 섹터의 행 {board['orphan_total']}건이 정렬에서 빠짐: " + ", ".join(f"{k} {v}건" for k, v in board["orphans"].items()) + ". 맵의 섹터 이름을 바꿨으면 되돌리거나 Ken 에게 알린다")
    return "\n".join(out)


def append(path: Path, todo: list[dict], n_existing: int) -> int:
    """append 한 뒤 마지막 줄들을 다시 읽어 rows 와 같은지 확인한다. 0 통과 / 2 검증 실패(이미 쓴 뒤라 되돌리지 않는다. 장부는 수정 금지)."""
    path.parent.mkdir(exist_ok=True)
    need_nl = path.exists() and path.stat().st_size > 0 and not path.read_bytes().endswith(b"\n")
    with open(path, "a", encoding="utf-8") as f:
        if need_nl:
            f.write("\n")
        for r in todo:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tail = [l for l in path.read_text(encoding="utf-8").split("\n") if l.strip()][-len(todo):]
    try:
        ok = [json.loads(l) for l in tail] == todo
    except json.JSONDecodeError:
        ok = False
    if not ok:
        print(f"append 검증 실패: {path.name} 마지막 {len(todo)}줄이 rows 와 다름. 장부는 수정하지 않는다. Ken 에게 알린다")
        return 2
    print(f"appended {len(todo)} ({path.name} 총 {n_existing + len(todo)}줄)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="장부 검증·추가")
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
    try:
        existing, by_line = load_existing()
        smap = load_sector_map()
    except ValueError as e:
        print(f"멈춤: {e}")
        return 2
    todo, errors, skipped = validate(rows, args.date, today, existing, by_line, smap)
    for s in skipped:
        print("skip 중복:", s)
    if errors:
        print("검증 실패. append 안 함:\n  " + "\n  ".join(errors))
        return 1
    summary = tally(existing + todo, today, smap)   # append 전에 계산. 여기서 실패하면 장부에 아무것도 쓰지 않는다
    if args.append and todo:
        rc = append(LEDGER, todo, len(existing))
        if rc:
            return rc
    elif args.append:
        print("appended 0")
    else:
        print(f"검증 통과 {len(todo)}건 (--append 없음, 장부에는 아직 안 씀)")
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
