---
description: ledger/signals.jsonl을 최근 30일/90일로 집계해 어느 축이 커지고 있는지 숫자 근거로 서술
argument-hint: [YYYY-MM-DD]
---

# /trend

CLAUDE.md "워크플로 > /trend"를 실행한다. 레포 루트에서 실행한다. 파일은 만들지 않고 채팅에만 출력한다. 장부는 읽기만 한다. 어떤 경우에도 `ledger/signals.jsonl`을 수정하지 않는다.

기준일: `$ARGUMENTS`가 `YYYY-MM-DD` 형식이면 그 날짜, 비어 있으면 `TZ=Asia/Seoul date +%F` 결과(한국 날짜). 그 외 형식이면 "날짜 형식 오류"라고 답하고 멈춘다. 이하 `<기준일>`.

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

tp = Path("framework/thesis.md")
TITLES = dict(re.findall(r"^## (T\d+)\s+(.+?)\s*$", tp.read_text(encoding="utf-8"), re.M)) if tp.exists() else {}
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
    # 티커 집계: 같은 섹터(테마)끼리 묶는다. 한 시그널에 같은 티커가 두 번 있어도 1회. 방향은 그 시그널의 direction
    sec, tot, themes_of = {}, {}, collections.defaultdict(collections.Counter)
    for r in w:
        s = sec.setdefault((r["axis"], r["theme"]), [0, {}]); s[0] += 1
        for t in dict.fromkeys(r.get("sectors", [])):
            for slot in (s[1].setdefault(t, collections.Counter()), tot.setdefault(t, collections.Counter())):
                slot["n"] += 1; slot[r.get("direction", "?")] += 1
            themes_of[t][r["theme"]] += 1
    print(f"\n### 티커 집계 (최근 {days}일, 같은 섹터끼리 묶음. 한 시그널에 같은 티커는 1회)")
    print("| 축 | 섹터(테마) | 시그널 | 티커: 횟수 (+/-/±) |")
    print("|---|---|---|---|")
    for (a, th), (n, tk) in sorted(sec.items(), key=lambda x: (-x[1][0], -sum(c["n"] for c in x[1][1].values()), AXES.index(x[0][0]) if x[0][0] in AXES else 99, x[0][1])):
        cell = ", ".join(f"{t} {c['n']} ({c['+']}/{c['-']}/{c['±']})" for t, c in sorted(tk.items(), key=lambda x: (-x[1]["n"], x[0])))
        print(f"| {a} | {th} | {n} | {cell or '-'} |")
    if not sec: print("| - | - | 0 | - |")
    print("- 티커별 합계 (섹터 무관): " + (", ".join(f"{t}({c['n']})" for t, c in sorted(tot.items(), key=lambda x: (-x[1]["n"], x[0]))) or "없음"))
    multi = [(t, list(c)) for t, c in themes_of.items() if len(c) > 1]
    if multi: print("- 두 섹터 이상에서 나온 티커: " + ", ".join(f"{t} ({', '.join(ths)})" for t, ths in sorted(multi)))
    # 가중 집계: impact × horizon(분기 1, 1년 2, 다년 3). 필드가 없는 옛 줄은 가중 1
    HW = {"분기": 1, "1년": 2, "다년": 3}
    wt = lambda r: (r.get("impact") if isinstance(r.get("impact"), int) else 1) * HW.get(r.get("horizon"), 1)
    print(f"\n### 가중 집계 (최근 {days}일, impact × horizon. 필드 없는 옛 줄은 가중 1)")
    print("| 축 | 커짐 가중 | 작아짐 가중 | 유보 가중 | 필드 없는 줄 |")
    print("|---|---|---|---|---|")
    for a in AXES:
        s = [r for r in w if r["axis"] == a]
        g = {k: sum(wt(r) for r in s if grow(r) == k) for k in ("커짐", "작아짐", "유보")}
        print(f"| {a} | {g['커짐']} | {g['작아짐']} | {g['유보']} | {sum(1 for r in s if 'horizon' not in r)} |")
    # 논지별 증거: thesis 필드 T1+ / T1-
    ev = collections.defaultdict(lambda: [0, 0])
    for r in w:
        for x in r.get("thesis") or []:
            m = re.fullmatch(r"(T\d+)([+-])", x)
            if m: ev[m.group(1)][0 if m.group(2) == "+" else 1] += 1
    print(f"\n### 논지별 증거 (최근 {days}일, thesis 필드)")
    for tid, (c, f) in sorted(ev.items(), key=lambda x: int(x[0][1:])): print(f"- {tid} {TITLES.get(tid, '')}: 확인 {c}건 / 반증 {f}건")
    if not ev: print("- 없음 (thesis 필드가 있는 줄 없음)")

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

# 섹터 보드 (fetch/scoring.py. 사이트 "섹터" 탭과 같은 계산)
sys.path.insert(0, "fetch")
from scoring import sector_board, attention
crows = []
cp = Path("ledger/companies.jsonl")
if cp.exists():
    for n, l in enumerate(cp.read_text(encoding="utf-8").split("\n"), 1):
        if l.strip(): d = json.loads(l); d["line"] = n; crows.append(d)
for r in rows: r["line"] = r["_line"]
NAME = {"up": "유리 누적", "down": "불리 누적", "mixed": "엇갈림"}
for days in (30, 90):
    S = sector_board(rows, crows, today, days)
    print(f"\n## 섹터 보드 (최근 {days}일. 점수 = 방향 × 크기 × 기간, 기업 관찰은 구조적 1·미확정 0.5) 유리 {S['counts']['up']} / 불리 {S['counts']['down']} / 엇갈림 {S['counts']['mixed']} / 신호 없음 {S['counts']['none']}")
    print("| 축 | 섹터 | 티커 | 점수 | 유리/불리/양쪽 | 건수(구조적) | 분류 | 최근 신호 |")
    print("|---|---|---|---|---|---|---|---|")
    for b in S["themes"]:
        print(f"| {b['axis']} | {b['theme']} | {', '.join(b['tickers'])} | {b['score']:+g} | {b['up']}/{b['down']}/{b['both']} | {b['n']}({b['structural']}) | {NAME[b['group']]} | {b['recent'][0]['date']} {b['recent'][0]['fact'][:60]} |")
    print("- 신호 없는 섹터: " + (", ".join(b["theme"] for b in S["none"]) or "없음"))
    print("- 티커별: " + (", ".join(f"{x['ticker']} {x['score']:+g}({x['up']}/{x['down']}/{x['both']})" for x in S["tickers"]) or "없음"))
A = attention(today)
print(f"\n## 관심 테마 (최근 7일 수집 헤드라인 {A['headlines7']}건, 수집 {A['days_present7']}일. 기업 검색어 소스 제외. 지난주 비교 {'가능' if A['comparable'] else '불가(자료 부족)'})")
for x in A["themes"][:12]:
    print(f"- {x['theme']}: {x['n7']}건 ({x['share7']}%)" + (f", 지난주 대비 {x['delta_pp']:+g}p" if A["comparable"] else ""))
if not A["days_present7"]: print("- raw/ 가 없어 계산 못 함 (로컬이면 python3 fetch/fetch.py 또는 radar-raw 연결)")

print("\n## 번복 행 (reverses)")
rev = [r for r in rows if r.get("reverses")]
for r in rev: print(f"- {r['date']} [{r['axis']}/{r['theme']}] 줄 {r['_line']} 이 줄 {r['reverses']} 을 뒤집음: {r['fact'][:80]}")
if not rev: print("- 없음")
reversed_lines = {r["reverses"] for r in rev}
cut30 = today - datetime.timedelta(days=30)
print("\n## 확인 대기 (30일 넘은 커짐, horizon 1년 이상, 번복 없음. /review 에서 예상 결과를 확인한다)")
wait = [r for r in windows[90] if r["_d"] <= cut30 and grow(r) == "커짐" and r.get("horizon", "1년") != "분기" and r["_line"] not in reversed_lines]
for r in wait: print(f"- 줄 {r['_line']} {r['date']} [{r['axis']}/{r['theme']}] {r['fact'][:80]}")
if not wait: print("- 없음")

# 맵 수정 제안 반복 횟수 (sector_map.yaml 사용 규칙: 3회 이상 반복 등장할 때만 추가 검토)
sys.path.insert(0, "fetch")
from config import load_sector_map, all_tickers as _all   # framework/*.yaml 공용 파서 (fetch/config.py)
all_tickers = _all(load_sector_map())
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
- 티커 집계 표는 스크립트 출력을 그대로 옮긴다. "두 섹터 이상에서 나온 티커"가 있으면 그 티커가 어느 섹터들에서 나왔는지 한 줄로 밝힌다. 횟수는 언급 횟수이지 강도가 아니다.
- 가중 집계가 건수와 다른 그림을 보이면(건수는 많은데 가중은 작거나 그 반대) 그 점을 한 줄로 밝힌다. 축 판단은 건수와 가중을 같이 보고, 둘이 어긋나면 "유보"로 쓴다.
- 논지별 증거는 thesis.md 번호와 제목으로 쓴다. 확인·반증 건수만 옮기고 상태 변경은 제안하지 않는다(그건 /review).
- 섹터 보드는 "어느 섹터에 유리·불리 근거가 쌓였는가"를 답하는 표다. 점수의 부호와 유리/불리 건수를 같이 옮기고, 최근 신호 한 줄로 이유를 붙인다. 티커별 줄은 그대로 옮긴다. 수익률 예측처럼 쓰지 않는다.
- 관심 테마는 헤드라인 언급량이라 방향이 없다. 순위와 주간 변화만 말하고, 섹터 보드의 방향과 붙여 "관심은 높은데 근거는 없는 곳 / 관심은 낮은데 근거가 쌓이는 곳"을 짚는다.
- 소스 편향을 밝힌다: 정치권력은 federal_register·gnews_tariff, 자본권력은 fed_press·gnews_fed_rate, 기술권력은 gnews_big_tech_antitrust, 코인은 gnews_bitcoin_etf 가 입력이다. 기술·자본 축의 분기 자료(실적 가이던스, SEP, QRA, 13F)는 파이프라인에 없어 건수가 적게 나온다. 축 간 건수 차이를 그대로 힘의 차이로 읽지 않는다.
- 맵 수정 제안 등장 횟수는 대문자 토큰 집계라서 티커가 아닌 것이 섞인다. 티커로 보이는 것만 남기고 3회 이상이면 Ken에게 추가 검토를 제안한다.
- 매매 표현 금지. 영향은 "~라는 가설"로 쓴다. 미국 시장 기준.

## 4. 출력 형식 (채팅)

```markdown
# 트렌드 (기준일 <기준일>)

## 최근 30일
(스크립트 표 그대로. 축 표 다음에 "티커 집계" 표와 티커별 합계 줄)

## 최근 90일
(스크립트 표 그대로. 위와 같은 구성)

## 30일 단위 추이
(스크립트 표 그대로)

## 어느 축이 커지고 있는가
한 문단

## 축 간 충돌
없음 / 조합별 90일·30일 건수와 각 건의 결과

## 섹터 보드
(스크립트 표 그대로: 30일, 90일. 신호 없는 섹터와 티커별 줄 포함)

## 관심 테마
(스크립트 출력 그대로 + 섹터 보드와 붙인 한 줄)

## 논지별 증거
T번호 제목: 확인 n / 반증 m (30일, 90일)

## 번복과 확인 대기
(스크립트 출력 그대로)

## 맵 수정 제안 반복
없음 / 티커별 횟수
```
