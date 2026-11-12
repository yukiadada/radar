#!/usr/bin/env python3
"""/check 의 집계. 기간의 루틴 커밋·raw 소스·장부 행·종가·브리프 내용을 한 번에 출력한다. 아무것도 쓰지 않는다.

  python3 fetch/check.py                                   지난 점검 다음 날 ~ 오늘(KST)
  python3 fetch/check.py --from 2026-11-10 --to 2026-11-11

"지난 점검"은 CLAUDE.md "## 현재 상태" 의 마지막 "- M/D~M/D 점검" 항목의 끝 날이다 (없거나 오늘이면 오늘 하루).
루틴 커밋은 origin/main 기록에서 찾는다 (루틴은 main 에 푸시한다). 먼저 `git fetch origin main`.
raw/·prices/ 링크(radar-raw)가 없으면 그 두 절은 "확인 안 됨"으로 찍는다. 브리프가 읽은 시점의 수집 오류는
radar-raw 의 git 이력으로 본다 (얕은 clone 이면 `git -C ../radar-raw fetch --depth=200 origin main`).
브리프 시점은 루틴 커밋 직전의 수집으로 잡는다. 루틴은 커밋보다 몇 분 앞서 raw 를 읽으므로 커밋 전 30분 안의 앞선 수집에 있던 오류도 같이 찍는다.
GitHub Actions 수집·배포 실행과 site/build.py 경고는 여기서 보지 않는다 (/check 가 따로 본다).
종료 코드: 0 (문제가 있어도 0. 판단은 /check 가 한다) / 2 인자 오류
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import ROOT, all_tickers, load_sector_map, load_sources  # noqa: E402
from ledger import LEDGER, load_existing  # noqa: E402
from market import BENCH, asof, lagging, load_prices  # noqa: E402

KST = datetime.timezone(datetime.timedelta(hours=9))
CHECK_ITEM = re.compile(r"^- (\d{1,2})/(\d{1,2})(?:~(\d{1,2})/(\d{1,2}))? 점검", re.M)
BRIEF_COMMIT = re.compile(r"^brief (\d{4}-\d{2}-\d{2}): 구조적 시그널 (\d+)건")
# 버린 뉴스 이유 (brief.md 6단계의 이유 예 + 실제로 자주 나온 것). 같은 이유의 반복을 세려고 쓴다
REASONS = ["맵 영향 없음", "맵 밖", "제안 단계", "임시 조치", "일시 중단", "같은 달 지표 반복", "먼 연결", "발언", "가격 등락",
           "자금흐름", "중복", "헤드라인만", "전망", "계획 단계", "3축 어디에도"]
BLOCKED = re.compile(r"403|열리지|허용 도메인 밖|허용 목록 밖|막혀|막힌|봇 확인|차단")
READ_WINDOW = 30   # 분. 루틴이 raw 를 읽고 커밋하기까지 걸릴 수 있는 시간
HOST = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:gov|com|org|net|io)\b")


def sh(*args: str, cwd: Path = ROOT) -> str:
    r = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def kst(iso: str) -> str:
    return datetime.datetime.fromisoformat(iso).astimezone(KST).strftime("%m/%d %H:%M")


def last_check_end(today: datetime.date) -> datetime.date | None:
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    text = text.split("## 현재 상태", 1)[-1] if "## 현재 상태" in text else ""
    ends = []
    for m in CHECK_ITEM.finditer(text):
        mo, d = (int(m.group(3)), int(m.group(4))) if m.group(3) else (int(m.group(1)), int(m.group(2)))
        try:
            e = datetime.date(today.year, mo, d)
        except ValueError:
            continue
        if e > today:   # 해를 넘긴 항목 (1월에 보는 12월 점검)
            try:
                e = e.replace(year=today.year - 1)
            except ValueError:   # 2/29
                continue
        ends.append(e)
    return max(ends, default=None)


def brief_commits(lo: datetime.date) -> dict[str, list[dict]]:
    ref = "origin/main" if sh("git", "rev-parse", "--verify", "-q", "origin/main") else "HEAD"
    out = collections.defaultdict(list)
    since = (lo - datetime.timedelta(days=3)).isoformat()
    for line in sh("git", "log", ref, f"--since={since}", "--format=%h|%an|%cI|%s").splitlines():
        h, an, ci, s = line.split("|", 3)
        m = BRIEF_COMMIT.match(s)
        if m:
            files = sh("git", "show", "--name-only", "--format=", h).split()
            out[m.group(1)].append({"hash": h, "author": an, "time": ci, "n": int(m.group(2)), "files": files})
    return out


def errors_at(rr: Path, commit: str, ds: str) -> list[str]:
    """radar-raw 의 그 커밋 시점에 raw/<날짜>/ 에서 error 필드가 있던 소스."""
    out = []
    for f in sh("git", "ls-tree", "--name-only", commit, f"raw/{ds}/", cwd=rr).split():
        try:
            j = json.loads(sh("git", "show", f"{commit}:{f}", cwd=rr) or "{}")
            if isinstance(j, dict) and j.get("error"):
                out.append(Path(f).stem)
        except ValueError:
            out.append(Path(f).stem + "(깨짐)")
    return out


def section_routine(dates: list[str], commits: dict, per_day: collections.Counter) -> None:
    print("## 루틴 (origin/main 의 brief 커밋)")
    for ds in dates:
        cs = commits.get(ds, [])
        brief = (ROOT / "briefs" / f"{ds}.md").exists()
        if not cs:
            print(f"- {ds}: 루틴 커밋 없음" + ("" if brief else ", 브리프 파일도 없음"))
            continue
        for c in cs:
            probs = []
            if c["author"] != "radar routine":
                probs.append(f"작성자 {c['author']}")
            for f in (f"briefs/{ds}.md", "briefs/direction.md"):
                if f not in c["files"]:
                    probs.append(f"{f} 빠짐")
            if c["n"] and "ledger/signals.jsonl" not in c["files"]:
                probs.append("장부 빠짐")
            if c["n"] != per_day[ds]:
                probs.append(f"커밋 {c['n']}건 ≠ 장부 {per_day[ds]}건")
            if not brief:
                probs.append("작업 트리에 브리프 없음 (브랜치가 main 보다 뒤?)")
            print(f"- {ds}: {c['hash']} {kst(c['time'])} KST, 시그널 {c['n']}건"
                  + (f". 문제: {', '.join(probs)}" if probs else ". 이상 없음"))
        if len(cs) > 1:
            print(f"  - {ds} 루틴 커밋 {len(cs)}개")
    d = ROOT / "briefs/direction.md"
    print(f"- direction.md 첫 줄: {d.read_text(encoding='utf-8').splitlines()[0] if d.exists() else '없음'}")


def section_sources(dates: list[str], commits: dict) -> None:
    print("\n## 소스 (raw/)")
    raw = ROOT / "raw"
    if not raw.is_dir():
        print("- raw/ 없음 (radar-raw 링크 필요): 확인 안 됨")
        return
    names = [s["name"] for s in load_sources() if not s["error"]]
    rr = raw.resolve().parent
    shallow = sh("git", "rev-parse", "--is-shallow-repository", cwd=rr).strip()
    zero_days = collections.Counter()
    for ds in dates:
        p = raw / ds
        files = {}
        for f in sorted(p.glob("*.json")) if p.is_dir() else []:
            try:
                files[f.stem] = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                files[f.stem] = {"error": "JSON 깨짐", "count": 0}
        missing = [n for n in names if n not in files]
        errs = [n for n, v in files.items() if v.get("error")]
        zero = [n for n, v in files.items() if not v.get("error") and not v.get("count")]
        zero_days.update(zero)
        items = sum(v.get("count") or 0 for v in files.values())
        print(f"- {ds}: 파일 {len(files)}/{len(names)}, 항목 {items}, 빠짐 {', '.join(missing) or '없음'}, "
              f"오류 {', '.join(errs) or '없음'}, 0건 {', '.join(zero) or '없음'}")
        # 브리프가 읽은 시점: 루틴 커밋 직전의 radar-raw 커밋. 루틴은 커밋보다 몇 분 앞서 raw 를 읽으므로,
        # 커밋 전 READ_WINDOW 분 안에 수집이 여러 번 들어왔으면 앞선 수집의 오류도 같이 보인다 (어느 쪽을 읽었는지는 이력만으로 모른다)
        when = commits.get(ds, [{}])[0].get("time")
        if not when:
            continue
        since = (datetime.datetime.fromisoformat(when) - datetime.timedelta(minutes=READ_WINDOW)).isoformat()
        near = [x.split("|") for x in sh("git", "log", f"--before={when}", f"--since={since}", "--format=%h|%cI", "--", f"raw/{ds}", cwd=rr).split()]
        if not near:   # 창 안에 수집이 없으면 그 전의 마지막 수집을 읽은 것이다
            near = [x.split("|") for x in sh("git", "log", "-1", f"--before={when}", "--format=%h|%cI", "--", f"raw/{ds}", cwd=rr).split()]
        if not near:
            print(f"  - 브리프 시점: radar-raw 이력 없음" + (" (얕은 clone)" if shallow == "true" else ""))
            continue
        (ch, ct), earlier = near[0], near[1:]
        at = errors_at(rr, ch, ds)
        print(f"  - 브리프 시점({ch} {kst(ct)} KST) 오류: {', '.join(at) or '없음'}")
        for eh, et in earlier:
            more = [n for n in errors_at(rr, eh, ds) if n not in at]
            if more:
                print(f"    - 그 직전 수집({eh} {kst(et)} KST)에는 오류: {', '.join(more)}. 루틴 커밋 {READ_WINDOW}분 안이라 브리프가 이쪽을 읽었을 수 있다")
    always = [n for n, k in zero_days.items() if k == len(dates)]
    if len(dates) > 1 and always:
        print(f"- 기간 내내 0건: {', '.join(sorted(always))}")


def section_ledger(rows: list[dict], lo: str, hi: str) -> collections.Counter:
    print("\n## 장부")
    sel = [r for r in rows if lo <= r["date"] <= hi]
    per_day = collections.Counter(r["date"] for r in sel)
    print(f"- 장부 {len(rows)}줄, 기간 {len(sel)}건" + (f" (줄 {sel[0]['line']}~{sel[-1]['line']})" if sel else ""))
    if not sel:
        return per_day
    pm = sum(r["direction"] == "±" for r in sel)
    print(f"- 날짜별: {', '.join(f'{d[5:]} {n}' for d, n in sorted(per_day.items()))}")
    print(f"- 축: {dict(collections.Counter(r['axis'] for r in sel))}, 방향: {dict(collections.Counter(r['direction'] for r in sel))}"
          f", ± {pm}/{len(sel)} ({round(pm * 100 / len(sel))}%)")
    rev = ", ".join("%s→%s" % (r["line"], r["reverses"]) for r in sel if r.get("reverses")) or "없음"
    print(f"- 확신: {dict(sorted(collections.Counter(r['confidence'] for r in sel).items()))}, 번복: {rev}")
    for r in sel:
        first = r["fact"].split(". ")[0]
        print(f"  - {r['line']} {r['date'][5:]} {r['axis']}/{r['sector']} {r['direction']} {r['confidence']} {first[:45]}")
    return per_day


def section_prices(today: datetime.date) -> None:
    print("\n## 종가 (prices/)")
    p = load_prices()
    if not p:
        print("- prices/prices.json 없음 (radar-raw 링크 필요): 확인 안 됨")
        return
    a = asof(p)
    lag = (today - datetime.date.fromisoformat(a)).days if a else None
    print(f"- {len(p['tickers'])}종목, 마지막 종가 {a} (오늘보다 {lag}일 전), 갱신 {kst(p['updated_at']) + ' KST' if p.get('updated_at') else '확인 안 됨'}")
    try:
        want = sorted(all_tickers(load_sector_map()) | {BENCH})
        missing = [t for t in want if t not in p["tickers"]]
    except ValueError as e:
        missing = []
        print(f"- sector_map 읽기 실패: {e}")
    stale = lagging(p)
    errs = p.get("errors") or {}
    print(f"- 빠진 종목: {', '.join(missing) or '없음'}. 멈춘 종목(최근 종가보다 5일 넘게 뒤): {', '.join(f'{t} {dt}' for t, dt in stale) or '없음'}. "
          f"마지막 갱신 실패: {', '.join(errs) or '없음'}")


def section_briefs(dates: list[str]) -> None:
    print("\n## 브리프 내용")
    reasons, hosts = collections.Counter(), collections.Counter()
    for ds in dates:
        p = ROOT / "briefs" / f"{ds}.md"
        if not p.exists():
            continue
        t = p.read_text(encoding="utf-8")
        secs = {m.group(1): m.group(2) for m in re.finditer(r"^## (.+?)\n(.*?)(?=^## |\Z)", t, flags=re.S | re.M)}
        dropped = [l[2:] for k, v in secs.items() if k.startswith("버린 뉴스") for l in v.splitlines() if l.startswith("- ")]
        flags = ["오늘 구조적 시그널 없음"] if "오늘 구조적 시그널 없음" in t else []
        maps = [l[2:] for k, v in secs.items() if k.startswith("맵 수정 제안") for l in v.splitlines() if l.startswith("- ")]
        print(f"- {ds}: 버린 뉴스 {len(dropped)}줄" + (f", {', '.join(flags)}" if flags else "")
              + (f", 맵 수정 제안 {len(maps)}건" if maps else ""))
        for m in maps:
            print(f"  - 맵 수정 제안: {m[:160]}")
        for l in dropped:
            why = l.rsplit(": ", 1)[-1]
            for k in REASONS:
                if k in why:
                    reasons[k] += 1
            print(f"  - 버림: {l[:160]}")
        for memo in re.findall(r"^- 확인 방법 메모: (.*)$", t, flags=re.M):
            for s in re.split(r"(?<=다)\. ", memo):
                if BLOCKED.search(s):
                    hosts.update(set(HOST.findall(s)))
                    print(f"  - 열리지 않음: {s[:160]}")
    if reasons:
        print(f"- 버린 이유 합계: {', '.join(f'{k} {n}' for k, n in reasons.most_common())}")
    if hosts:
        print(f"- 열리지 않은 호스트: {', '.join(f'{h} {n}일' for h, n in hosts.most_common())}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="/check 집계 (읽기만)")
    ap.add_argument("--from", dest="lo", help="YYYY-MM-DD. 기본: 지난 점검 끝 날 다음 날")
    ap.add_argument("--to", dest="hi", help="YYYY-MM-DD. 기본: 오늘(KST)")
    args = ap.parse_args(argv)
    try:
        hi = datetime.date.fromisoformat(args.hi) if args.hi else datetime.datetime.now(KST).date()
        if args.lo:
            lo = datetime.date.fromisoformat(args.lo)
        else:
            last = last_check_end(hi)
            lo = last + datetime.timedelta(days=1) if last and last < hi else hi
    except ValueError:
        ap.error("날짜는 YYYY-MM-DD")
    if lo > hi:
        ap.error("--from 이 --to 보다 늦다")
    dates = [(lo + datetime.timedelta(days=i)).isoformat() for i in range((hi - lo).days + 1)]
    print(f"# 점검 {lo} ~ {hi} ({len(dates)}일, KST)\n")
    warn: list[str] = []
    rows, _ = load_existing(LEDGER, warnings=warn)
    commits = brief_commits(lo)
    per_day = collections.Counter(r["date"] for r in rows if lo.isoformat() <= r["date"] <= hi.isoformat())
    section_routine(dates, commits, per_day)
    section_sources(dates, commits)
    section_ledger(rows, lo.isoformat(), hi.isoformat())
    for w in warn:
        print(f"- 장부 경고: {w}")
    section_prices(datetime.datetime.now(KST).date())
    section_briefs(dates)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:   # `| head` 처럼 읽는 쪽이 먼저 닫은 경우
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
