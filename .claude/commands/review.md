---
description: 월 1회 점검. backdrop.md 에 배경 지표를 출처와 함께 적고, 30일 넘은 커짐 시그널의 예상 결과를 확인하고, thesis.md 상태 변경을 제안한다. Ken 이 직접 호출한다
argument-hint: [YYYY-MM]
disable-model-invocation: true
---

# /review (월 1회)

CLAUDE.md "워크플로 > /review"를 실행한다. 레포 루트에서 실행한다. 장부(`ledger/signals.jsonl`)는 읽기만 한다. 어떤 경우에도 장부를 수정하지 않는다. 번복이 확인되면 반대 방향 행을 /brief 로 올리자고 제안만 한다.

대상 월: `$ARGUMENTS`가 `YYYY-MM` 형식이면 그 달, 비어 있으면 `TZ=Asia/Seoul date +%Y-%m`. 이하 `<월>`.

## 0. 규칙 로드

`CLAUDE.md`, `framework/axes.md`(특히 "공통 규칙"), `framework/thesis.md`, `framework/backdrop.md`를 전부 읽는다.

## 1. 증거 집계

아래 스크립트를 실행한다. 숫자는 이 출력만 쓴다.

```bash
python3 - <<'EOF'
import json, re, datetime, collections, sys
from pathlib import Path
if not Path("CLAUDE.md").exists(): sys.exit("레포 루트에서 실행해야 한다")
today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date()
rows = []
for n, l in enumerate(Path("ledger/signals.jsonl").read_text(encoding="utf-8").split("\n"), 1):
    if l.strip(): d = json.loads(l); d["_line"] = n; d["_d"] = datetime.date.fromisoformat(d["date"]); rows.append(d)
GROW = re.compile(r"^(?:\[충돌:[^\]]*\]\s*)?(커짐|작아짐|유보)")
grow = lambda r: (GROW.match(r.get("note", "")) or [None, "미표기"])[1]
th_md = Path("framework/thesis.md").read_text(encoding="utf-8")
titles = dict(re.findall(r"^## (T\d+)\s+(.+?)\s*$", th_md, re.M))
status = {m.group(1): m.group(2) for m in re.finditer(r"^## (T\d+)[^\n]*\n(?:(?!^## ).*\n)*?- 상태:\s*(.+?)\s*$", th_md, re.M)}
w90 = [r for r in rows if today - datetime.timedelta(days=90) < r["_d"] <= today]
print(f"장부 {len(rows)}줄, 최근 90일 {len(w90)}건, 기준일 {today}")
print("\n## 논지별 증거 (최근 90일)")
ev = collections.defaultdict(lambda: [[], []])
for r in w90:
    for t in r.get("thesis") or []:
        m = re.fullmatch(r"(T\d+)([+-])", t)
        if m: ev[m.group(1)][0 if m.group(2) == "+" else 1].append(r)
for tid in sorted(titles, key=lambda x: int(x[1:])):
    c, f = ev.get(tid, [[], []])
    print(f"- {tid} {titles[tid]} [상태: {status.get(tid, '?')}] 확인 {len(c)} / 반증 {len(f)}")
    for r in c: print(f"    + {r['date']} {r['fact'][:70]}")
    for r in f: print(f"    - {r['date']} {r['fact'][:70]}")
rev = {r["reverses"] for r in rows if r.get("reverses")}
cut = today - datetime.timedelta(days=30)
print("\n## 확인 대기 (30일 넘은 커짐, horizon 1년 이상, 번복 없음). 예상 결과가 실제로 나타났는지 검색으로 확인한다")
wait = [r for r in w90 if r["_d"] <= cut and grow(r) == "커짐" and r.get("horizon", "1년") != "분기" and r["_line"] not in rev]
for r in wait: print(f"- 줄 {r['_line']} {r['date']} [{r['axis']}/{r['theme']}] {r['fact'][:90]}\n    출처 {r['source']}")
if not wait: print("- 없음")
bd = Path("framework/backdrop.md").read_text(encoding="utf-8")
months = re.findall(r"^\| (\d{4}-\d{2}) \|", bd, re.M)
print(f"\n## backdrop.md 기록 월: {', '.join(months) or '없음'}")
EOF
```

## 2. 배경 지표 기록

1. `<월>` 행이 backdrop.md 에 이미 있으면 이 단계를 건너뛴다.
2. 지표 4개를 WebFetch 또는 WebSearch 로 확인한다. 값마다 확인한 페이지의 URL 을 적는다. 못 찾은 값은 "확인 안 됨". 기억으로 채우지 않는다.
3. 아래처럼 표 끝에 한 행을 **추가만** 한다(Edit 로 마지막 줄 뒤에 붙인다). 기존 행은 고치지 않는다.
   `| <월> | 값 | 값 | 상향/하향/보합 | 값 | URL, URL | 한 줄 |`

## 3. 확인 대기 점검

"확인 대기" 각 줄에 대해 WebSearch 로 그 뒤 무슨 일이 있었는지 확인한다.
- 예상 결과가 나타났으면(집행·투자 집행·자금 유입 지속) "유지"라고 적는다.
- 뒤집혔으면(철회·취소·파기·폐지) 출처 URL 과 함께 "번복"이라고 적고, 반대 방향 행을 `/brief` 로 올리자고 제안한다. `reverses` 에 그 줄 번호를 쓴다. 여기서 장부를 쓰지 않는다.
- 확인이 안 되면 "확인 안 됨".

## 4. 논지 상태 제안

논지별 증거와 확인 대기 결과를 근거로, 상태를 바꿀 논지가 있으면 제안한다. 기준: 같은 방향 증거가 3건 이상 쌓이고 반대 증거가 없으면 "확인 쌓임"/"반증 쌓임", 반증이 확인을 넘고 90일 이어지면 "폐기" 검토. Ken 이 승인하면 thesis.md 의 해당 논지 "상태"와 "마지막 검토" 줄만 고친다. 주장·신호 문장은 Ken 이 직접 고친다.

## 5. 출력 (채팅)

```markdown
# 월간 점검 (<월>)

## 배경 지표
(이달 행 그대로, 또는 "이미 기록됨")

## 논지별 증거
(스크립트 출력 그대로)

## 확인 대기 결과
- 줄 n: 유지 / 번복 (출처) / 확인 안 됨

## 상태 변경 제안
없음 / T번호: 현재 → 제안, 근거 한 줄

## 다음 달까지 볼 것
한두 줄
```

매매 표현 금지. 영향은 "~라는 가설"로 쓴다.
