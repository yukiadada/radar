---
description: ledger/signals.jsonl 을 최근 30일/90일로 집계해 세 축이 어느 섹터·방향에 정렬되는지 숫자 근거로 서술
argument-hint: [YYYY-MM-DD]
---

# /trend

CLAUDE.md "워크플로 > /trend"를 실행한다. 레포 루트에서 실행한다. 파일은 만들지 않고 채팅에만 출력한다. 장부는 읽기만 한다. 어떤 경우에도 `ledger/signals.jsonl`을 수정하지 않는다.

기준일: `$ARGUMENTS`가 `YYYY-MM-DD` 형식이면 그 날짜, 비어 있으면 `TZ=Asia/Seoul date +%F` 결과(한국 날짜). 그 외 형식이면 "날짜 형식 오류"라고 답하고 멈춘다. 이하 `<기준일>`.

## 1. 집계

숫자는 아래 스크립트 출력만 쓴다. 직접 세지 않는다. 출력이 `장부 비어 있음`이면 그 한 줄만 답하고 끝낸다. 파싱 실패 메시지가 나오면 그대로 Ken에게 전하고 끝낸다(장부는 수정 금지). 사이트 "섹터"·"추이" 탭과 같은 계산(fetch/scoring.py)이다.

```bash
python3 - <<'EOF'
import json, re, sys, glob, datetime, collections
from pathlib import Path

DATE = "<기준일>"
if not Path("CLAUDE.md").exists(): sys.exit("레포 루트에서 실행해야 한다")
try: today = datetime.date.fromisoformat(DATE)
except ValueError: sys.exit(f"DATE 가 YYYY-MM-DD 가 아님: {DATE!r}")
sys.path.insert(0, "fetch")
from config import AXES, load_sector_map, all_tickers, directions
from scoring import alignment, series, attach_deltas, board_table, attention, raw_scan, pending_review, in_window, weight, fmt_net, fmt_delta, LABELS, delta

from ledger import load_existing
try: rows, _ = load_existing()
except ValueError as e: sys.exit(str(e))
for r in rows: r["_d"] = datetime.date.fromisoformat(r["date"])
if not rows: print("장부 비어 있음"); raise SystemExit
future = sum(1 for r in rows if r["_d"] > today)
print(f"장부 전체 {len(rows)}건, {min(r['_d'] for r in rows)} ~ {max(r['_d'] for r in rows)}" + (f" (기준일 이후 {future}건은 집계 제외)" if future else ""))
smap = load_sector_map()
def fmt(counter, k): return ", ".join(f"{a}({b})" for a, b in counter.most_common(k)) or "-"
def pct(n, d): return f"{100 * n / d:.0f}%" if d else "-"
ser = {days: series(rows, today, days, 90, smap) for days in (30, 90)}
for days in (30, 90):
    w, span = in_window(rows, today, days)
    print(f"\n## 최근 {days}일 ({span['from']} ~ {span['to']}) 총 {len(w)}건")
    print("| 축 | 건수 | 비중 | + | − | ± | 가중 + | 가중 − | 평균 확신 | 상위 섹터 | 상위 티커 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for a in AXES:
        s = [r for r in w if r["axis"] == a]
        dc = collections.Counter(r["direction"] for r in s)
        sc = collections.Counter(r["sector"] for r in s)
        tk = collections.Counter(t for r in s for t in dict.fromkeys(r.get("tickers", [])))
        conf = f"{sum(r['confidence'] for r in s) / len(s):.2f}" if s else "-"
        wp = sum(weight(r) for r in s if r["direction"] == "+"); wm = sum(weight(r) for r in s if r["direction"] == "-")
        print(f"| {a} | {len(s)} | {pct(len(s), len(w))} | {dc['+']} | {dc['-']} | {dc['±']} | {wp} | {wm} | {conf} | {fmt(sc, 3)} | {fmt(tk, 5)} |")
    board = attach_deltas(alignment(rows, today, days, smap), ser[days])
    c = board["counts"]
    print(f"\n### 섹터 정렬 (최근 {days}일. 축 값 −1~+1, 정렬 % = 50 + 50 × 세 축 평균) 3축 {c['aligned3']} · 2축 {c['aligned2']} · 1축 {c['aligned1']} · 엇갈림 {c['mixed']} · 양쪽 {c['neutral']} · 역풍 {c['headwind']} · 신호 없음 {c['none']}")
    print("\n".join(board_table(board)))
    print("- 신호 없는 섹터: " + (", ".join(x["sector"] for x in board["sectors"] if not x["n"]) or "없음"))
    print(f"\n### 방향 (최근 {days}일. 신호 있는 소속 섹터의 축 점수 평균)")
    print("| 방향 | " + " | ".join(AXES) + " | 정렬 | 상태 | 건수 | 섹터(신호/전체) | 7일 변화 |")
    print("|---|" + "---|" * (len(AXES) + 5))
    for x in sorted(board["directions"], key=lambda x: (x["score"] is None, -(x["score"] or 0), x["direction"])):
        sc = f"{x['score']}%" if x["score"] is not None else "–"
        print(f"| {x['direction']} | " + " | ".join(fmt_net(x["axes"][a]) for a in AXES) + f" | {sc} | {LABELS[x['label']]} | {x['n']} | {x['active']}/{len(x['sectors'])} | {fmt_delta(x.get('delta'))} |")
    if board["orphan_total"]: print(f"- 경고: sector_map 에 없는 섹터의 행 {board['orphan_total']}건이 정렬에서 빠짐: " + ", ".join(f"{k} {v}건" for k, v in board["orphans"].items()))
print("\n## 30일 변화 (30일 창 정렬 %, 30일 전 대비. 둘 다 값이 있는 섹터만)")
ch = [(s, delta(v, 30), v[-1]) for s, v in ser[30]["sectors"].items() if delta(v, 30) is not None]
for s, dl, now in sorted(ch, key=lambda x: -abs(x[1])): print(f"- {s}: {now}% ({dl:+d}p)")
if not ch: print("- 없음 (장부가 30일 미만)")
A = attention(raw_scan(today), smap)
print(f"\n## 관심 (최근 7일 수집 헤드라인 {A['headlines7']}건, 수집 {A['days_present7']}일. 지난주 비교 {'가능' if A['comparable'] else '불가(자료 부족)'})")
if not A["days_present7"]: print("- raw/ 가 없어 계산 못 함 (로컬이면 python3 fetch/fetch.py 또는 radar-raw 연결)")
for x in (A["sectors"][:12] if A["days_present7"] else []):
    print(f"- {x['sector']}: {x['n7']}건 ({x['share7']}%)" + (f", 지난주 대비 {x['delta_pp']:+g}p" if A["comparable"] else ""))
print("\n## 번복 행 (reverses)")
rev = [r for r in rows if r.get("reverses")]
for r in rev: print(f"- {r['date']} [{r['axis']}/{r['sector']}] 줄 {r['line']} 이 줄 {r['reverses']} 을 뒤집음: {r['fact'][:80]}")
if not rev: print("- 없음")
print("\n## 확인 대기 (30일 넘은 + 시그널, horizon 1년 이상, 번복 없음. /review 에서 예상 결과를 확인한다)")
wait = pending_review(rows, today)
for r in wait: print(f"- 줄 {r['line']} {r['date']} [{r['axis']}/{r['sector']}] {r['fact'][:80]}")
if not wait: print("- 없음")
tickers = all_tickers(smap)
STOP = {"ETF", "AI", "US", "USA", "SEC", "CFTC", "FOMC", "FED", "ET", "KST", "QRA", "IPO", "GDP", "CPI", "OCC", "FDIC", "EU", "UK", "NPRM", "URL", "QT", "QE", "EDT", "EST", "UTC", "ETFS", "BTC", "ETH", "DPA", "PPA", "EO", "FR", "DMCA"}
props = collections.Counter()
for f in sorted(glob.glob("briefs/*.md")):
    m = re.search(r"^## 맵 수정 제안.*?$(.*?)(?=^## |\Z)", Path(f).read_text(encoding="utf-8"), re.M | re.S)
    if not m: continue
    for t in {t for t in re.findall(r"\b[A-Z][A-Z0-9.\-]{1,5}\b", m.group(1)) if t not in tickers and t not in STOP}: props[t] += 1
print("\n## 맵 수정 제안 등장 횟수 (briefs/*.md 기준, 대문자 토큰이라 사람이 걸러야 함)")
for t, n in props.most_common(): print(f"- {t}: {n}회" + ("  ← 3회 이상, 추가 검토 대상" if n >= 3 else ""))
if not props: print("- 없음")
EOF
```

## 2. 규칙 로드

장부가 비어 있지 않으면 `framework/axes.md`를 읽는다. 각 축의 "밀어줌/막음" 기준과 "3축 정렬" 절이 서술의 기준이다.

## 3. 서술

- "지금 세상은 어느 방향으로 흐르는가": 한 문단. 근거는 위 숫자만 쓴다. 방향별 정렬 %와 상태, 3축·2축 정렬 섹터, 엇갈림·역풍 섹터, 30일 변화의 가속·감속. 숫자 없는 주장은 쓰지 않는다.
- 어느 섹터든 표본이 3건 미만이면 "표본 부족"이라고 쓰고 방향을 단정하지 않는다. 한 축에서만 신호가 있는 섹터(1축)는 "나머지 두 축은 아직 모른다"라고 쓴다. 상태 "양쪽"은 신호는 있는데 축 점수가 모두 0 인 섹터(± 뿐이거나 상쇄)다. 엇갈림과 다르며, 방향을 말하지 않고 "판단 보류"라고 쓴다.
- 스크립트가 "sector_map 에 없는 섹터" 경고를 내면 그 행이 정렬에서 빠져 있다는 뜻이다. 서술 첫머리에 밝히고 맵의 섹터 이름을 되돌리거나 Ken 에게 알린다.
- 정렬이 깨진 섹터(엇갈림)는 axes.md 의 세 가지 패턴(기술 +/사회 −, 사회 +/정책 −, 정책 +/사회 −) 중 어디에 해당하는지 짚는다.
- 축별 상세 표는 스크립트 출력을 그대로 옮긴다. 가중 합이 건수와 다른 그림을 보이면 한 줄로 밝힌다.
- 관심은 헤드라인 언급량이라 방향이 없다. 순위와 주간 변화만 말하고, 섹터 정렬과 붙여 "관심은 높은데 근거는 없는 곳 / 관심은 낮은데 근거가 쌓이는 곳"을 짚는다.
- 소스 편향을 밝힌다: 정책 축 소스(federal_register, fed_press, tariff, Fed rate, antitrust, policy)가 가장 많고 문서형이라 구조적 시그널이 많이 나온다. 사회 축은 공식 통계·정기 조사만 구조적이라 건수가 적다. 축 간 건수 차이를 그대로 힘의 차이로 읽지 않는다.
- 맵 수정 제안 등장 횟수는 대문자 토큰 집계라서 티커가 아닌 것이 섞인다. 티커로 보이는 것만 남기고 3회 이상이면 Ken에게 추가 검토를 제안한다.
- 매매 표현 금지. 영향은 "~라는 가설"로 쓴다. 미국 시장 기준.

## 4. 출력 형식 (채팅)

```markdown
# 추이 (기준일 <기준일>)

## 최근 30일
(축 표, 섹터 정렬 표, 방향 표 그대로)

## 최근 90일
(같은 구성)

## 지금 세상은 어느 방향으로 흐르는가
한 문단

## 정렬과 균열
- 3축·2축 정렬: 섹터와 근거 한 줄씩
- 엇갈림·역풍: 섹터와 어느 축이 막는지

## 30일 변화
(스크립트 출력 그대로)

## 관심
(스크립트 출력 그대로 + 섹터 정렬과 붙인 한 줄)

## 번복과 확인 대기
(스크립트 출력 그대로)

## 맵 수정 제안 반복
없음 / 티커별 횟수
```
