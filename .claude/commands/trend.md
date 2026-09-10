---
description: ledger/signals.jsonl을 최근 30일/90일로 집계해 어느 축이 커지고 있는지 숫자 근거로 서술
argument-hint: [YYYY-MM-DD]
---

# /trend

CLAUDE.md "워크플로 > /trend"를 실행한다. 레포 루트에서 실행한다. 파일은 만들지 않고 채팅에만 출력한다. 장부는 읽기만 한다. 어떤 경우에도 `ledger/signals.jsonl`을 수정하지 않는다.

기준일: `$ARGUMENTS`가 `YYYY-MM-DD` 형식이면 그 날짜, 비어 있으면 `date +%F` 결과(로컬 날짜). 그 외 형식이면 "날짜 형식 오류"라고 답하고 멈춘다. 이하 `<기준일>`.

## 1. 집계

숫자는 아래 스크립트 출력만 쓴다. 직접 세지 않는다. 출력이 `장부 비어 있음`이면 그 한 줄만 답하고 끝낸다. 파싱 실패 메시지가 나오면 그대로 Ken에게 전하고 끝낸다(장부는 수정 금지).

```bash
python3 - <<'EOF'
import json, re, sys, glob, datetime, collections
from pathlib import Path

DATE = "<기준일>"
if not Path("CLAUDE.md").exists(): sys.exit("레포 루트에서 실행해야 한다")
try: today = datetime.date.fromisoformat(DATE)
except ValueError: sys.exit(f"DATE 가 YYYY-MM-DD 가 아님: {DATE!r}")
AXES = ("정치권력", "기술권력", "자본권력", "코인")

p = Path("ledger/signals.jsonl")
rows = []
if p.exists():
    for n, l in enumerate(p.read_text(encoding="utf-8").split("\n"), 1):
        if not l.strip(): continue
        try: d = json.loads(l); d["_d"] = datetime.date.fromisoformat(d["date"])
        except (json.JSONDecodeError, KeyError, ValueError) as e: sys.exit(f"ledger {n}번째 줄 파싱 실패: {e}. 장부는 수정 금지. Ken 에게 알린다")
        d["_line"] = n; rows.append(d)
if not rows: print("장부 비어 있음"); raise SystemExit
future = sum(1 for r in rows if r["_d"] > today)
print(f"장부 전체 {len(rows)}건, {min(r['_d'] for r in rows)} ~ {max(r['_d'] for r in rows)}" + (f" (기준일 이후 {future}건은 집계 제외)" if future else ""))

GROW = re.compile(r"^(?:\[충돌:[^\]]*\]\s*)?(커짐|작아짐|유보)")
CONF = re.compile(r"\[충돌:\s*(\S+)\s+vs\s+(\S+)\s*\]", re.I)
def grow(r):
    m = GROW.match(r.get("note", "")); return m.group(1) if m else "미표기"
def pair(m):
    return " vs ".join(sorted((m.group(1), m.group(2)), key=lambda x: AXES.index(x) if x in AXES else 99))
def fmt(counter, k): return ", ".join(f"{a}({b})" for a, b in counter.most_common(k)) or "-"
def pct(n, d): return f"{100 * n / d:.0f}%" if d else "-"

windows = {}
for days in (30, 90):
    cut = today - datetime.timedelta(days=days)
    w = [r for r in rows if cut < r["_d"] <= today]; windows[days] = w
    print(f"\n## 최근 {days}일 ({cut + datetime.timedelta(days=1)} ~ {today}) 총 {len(w)}건")
    print("| 축 | 건수 | 비중 | 커짐 | 작아짐 | 유보 | 섹터 방향 +/-/± | 평균 확신 | 상위 테마 | 상위 섹터 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for a in AXES:
        s = [r for r in w if r["axis"] == a]
        g = collections.Counter(grow(r) for r in s)
        dc = collections.Counter(r["direction"] for r in s)
        th = collections.Counter(r["theme"] for r in s)
        sc = collections.Counter(t for r in s for t in r["sectors"])
        conf = f"{sum(r['confidence'] for r in s) / len(s):.2f}" if s else "-"
        miss = f" (미표기 {g['미표기']})" if g["미표기"] else ""
        print(f"| {a} | {len(s)} | {pct(len(s), len(w))} | {g['커짐']} | {g['작아짐']} | {g['유보']}{miss} | {dc['+']}/{dc['-']}/{dc['±']} | {conf} | {fmt(th, 3)} | {fmt(sc, 5)} |")

lines30 = {r["_line"] for r in windows[30]}
hits = [(r, pair(m)) for r in windows[90] if (m := CONF.search(r.get("note", "")))]
print(f"\n## 축 간 충돌 (90일 {len(hits)}건, 30일 {sum(1 for r, _ in hits if r['_line'] in lines30)}건)")
for pr, cnt in collections.Counter(pr for _, pr in hits).most_common():
    n30 = sum(1 for r, x in hits if x == pr and r["_line"] in lines30)
    print(f"- {pr}: 90일 {cnt}건 / 30일 {n30}건" + ("  ← 반복" if cnt >= 2 else ""))
for r, pr in sorted(hits, key=lambda x: x[0]["_d"]):
    print(f"  - {r['date']} [{r['axis']}/{r['theme']}] {r['fact'][:90]} → {r['note'][:140]}")
if not hits: print("- 없음")

print("\n## 30일 단위 추이 (최근 → 과거): 건수 (커짐/작아짐)")
print("| 축 | 0~29일 전 | 30~59일 전 | 60~89일 전 |")
print("|---|---|---|---|")
for a in AXES:
    cells = []
    for k in range(3):
        hi = today - datetime.timedelta(days=30 * k); lo = today - datetime.timedelta(days=30 * (k + 1))
        s = [r for r in rows if r["axis"] == a and lo < r["_d"] <= hi]
        g = collections.Counter(grow(r) for r in s)
        cells.append(f"{len(s)} ({g['커짐']}/{g['작아짐']})")
    print(f"| {a} | " + " | ".join(cells) + " |")

# 맵 수정 제안 반복 횟수 (sector_map.yaml 사용 규칙: 3회 이상 반복 등장할 때만 추가 검토)
all_tickers = set()
for line in Path("framework/sector_map.yaml").read_text(encoding="utf-8").split("\n"):
    m = re.match(r"^\s+tickers:\s*\[(.*?)\]", line)
    if m: all_tickers.update(t.strip().strip("'\"") for t in m.group(1).split(","))
STOP = {"ETF", "AI", "US", "USA", "SEC", "CFTC", "FOMC", "FED", "ET", "KST", "QRA", "IPO", "GDP", "CPI", "OCC", "FDIC", "EU", "UK", "NPRM", "URL", "QT", "QE", "EDT", "EST", "UTC", "ETFS", "BTC", "ETH"}
props = collections.Counter()
for f in sorted(glob.glob("briefs/*.md")):
    m = re.search(r"^## 맵 수정 제안.*?$(.*?)(?=^## |\Z)", Path(f).read_text(encoding="utf-8"), re.M | re.S)
    if not m: continue
    for t in {t for t in re.findall(r"\b[A-Z][A-Z0-9.\-]{1,5}\b", m.group(1)) if t not in all_tickers and t not in STOP}: props[t] += 1
print("\n## 맵 수정 제안 등장 횟수 (briefs/*.md 기준, 대문자 토큰이라 사람이 걸러야 함)")
for t, n in props.most_common(): print(f"- {t}: {n}회" + ("  ← 3회 이상, 추가 검토 대상" if n >= 3 else ""))
if not props: print("- 없음")
EOF
```

## 2. 규칙 로드

장부가 비어 있지 않으면 `framework/axes.md`를 읽는다. "커진다/작아진다" 기준과 "축 간 충돌" 절이 서술의 기준이다.

## 3. 서술

- "어느 축이 커지고 있는가": 한 문단. 근거는 위 숫자만 쓴다. 축별 건수와 비중, 커짐 대 작아짐, 30일 단위 추이의 가속·감속. 숫자 없는 주장은 쓰지 않는다.
- 커짐/작아짐은 note 첫 단어를 집계한 것이고, "섹터 방향 +/-/±"는 티커 기준이다. 축 판단에는 앞의 것을 쓴다. "미표기"가 있으면 그 건수는 축 판단에서 뺀다고 밝힌다.
- 어느 축이든 표본이 3건 미만이면 그 축은 "표본 부족"이라고 쓰고 방향을 단정하지 않는다.
- 축 간 충돌: 스크립트가 `← 반복`으로 표시한 조합(90일 2건 이상)은 별도 항목으로 쓴다. 누가 이겼는지는 각 note에 적힌 내용만 인용한다. 추정하지 않는다.
- 자주 등장하는 섹터는 축별 상위 섹터 열을 그대로 옮긴다.
- 맵 수정 제안 등장 횟수는 대문자 토큰 집계라서 티커가 아닌 것이 섞인다. 티커로 보이는 것만 남기고 3회 이상이면 Ken에게 추가 검토를 제안한다.
- 매매 표현 금지. 영향은 "~라는 가설"로 쓴다. 미국 시장 기준.

## 4. 출력 형식 (채팅)

```markdown
# 트렌드 (기준일 <기준일>)

## 최근 30일
(스크립트 표 그대로)

## 최근 90일
(스크립트 표 그대로)

## 30일 단위 추이
(스크립트 표 그대로)

## 어느 축이 커지고 있는가
한 문단

## 축 간 충돌
없음 / 조합별 90일·30일 건수와 각 건의 결과

## 맵 수정 제안 반복
없음 / 티커별 횟수
```
