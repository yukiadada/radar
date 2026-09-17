---
description: 월 1회 점검. 30일 넘은 + 시그널의 예상 결과를 확인하고, 방향·섹터 맵(sector_map.yaml)과 소스(sources.yaml)의 수정을 제안한다. Ken 이 직접 호출한다
argument-hint: [YYYY-MM]
disable-model-invocation: true
---

# /review (월 1회)

CLAUDE.md "워크플로 > /review"를 실행한다. 레포 루트에서 실행한다. 장부(`ledger/signals.jsonl`)는 읽기만 한다. 어떤 경우에도 장부를 수정하지 않는다. 번복이 확인되면 반대 방향 행을 /brief 로 올리자고 제안만 한다. framework/*.yaml 도 여기서 고치지 않는다. 제안만 하고 Ken 이 승인하면 고친다.

대상 월: `$ARGUMENTS`가 `YYYY-MM` 형식이면 그 달, 비어 있으면 `TZ=Asia/Seoul date +%Y-%m`. 이하 `<월>`.

## 0. 규칙 로드

`CLAUDE.md`, `framework/axes.md`(특히 "공통 규칙"과 "3축 정렬"), `framework/sector_map.yaml`, `framework/sources.yaml` 을 전부 읽는다.

## 1. 증거 집계

아래 스크립트를 실행한다. 숫자는 이 출력만 쓴다.

```bash
python3 - <<'EOF'
import json, re, datetime, collections, sys, glob
from pathlib import Path
if not Path("CLAUDE.md").exists(): sys.exit("레포 루트에서 실행해야 한다")
today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date()
sys.path.insert(0, "fetch")
from config import AXES, load_sector_map, directions
from scoring import alignment, series, attach_deltas, board_table, in_window, LABELS
rows = []
for n, l in enumerate(Path("ledger/signals.jsonl").read_text(encoding="utf-8").split("\n"), 1):
    if l.strip(): r = json.loads(l); r["line"] = n; r["_d"] = datetime.date.fromisoformat(r["date"]); rows.append(r)
smap = load_sector_map()
w90, _ = in_window(rows, today, 90)
print(f"장부 {len(rows)}줄, 최근 90일 {len(w90)}건, 기준일 {today}")
board = attach_deltas(alignment(rows, today, 90, smap), series(rows, today, 90, 90, smap))
print("\n## 섹터 정렬 (최근 90일)")
print("\n".join(board_table(board)))
print("- 신호 없는 섹터: " + (", ".join(x["sector"] for x in board["sectors"] if not x["n"]) or "없음"))
print("\n## 축별 90일 건수·방향")
for a in AXES:
    s = [r for r in w90 if r["axis"] == a]; dc = collections.Counter(r["direction"] for r in s)
    print(f"- {a}: {len(s)}건 (+{dc['+']} / -{dc['-']} / ±{dc['±']})")
rev = {r["reverses"] for r in rows if r.get("reverses")}
cut = today - datetime.timedelta(days=30)
print("\n## 확인 대기 (30일 넘은 + 시그널, horizon 1년 이상, 번복 없음). 예상 결과가 실제로 나타났는지 검색으로 확인한다")
wait = [r for r in w90 if r["_d"] <= cut and r["direction"] == "+" and r.get("horizon", "1년") != "분기" and r["line"] not in rev]
for r in wait: print(f"- 줄 {r['line']} {r['date']} [{r['axis']}/{r['sector']}] {r['fact'][:90]}\n    출처 {r['source']}")
if not wait: print("- 없음")
props = collections.Counter()
for f in sorted(glob.glob("briefs/*.md")):
    m = re.search(r"^## 맵 수정 제안.*?$(.*?)(?=^## |\Z)", Path(f).read_text(encoding="utf-8"), re.M | re.S)
    if m:
        for line in m.group(1).split("\n"):
            if line.strip().startswith("- "): props[line.strip()[2:80]] += 1
print("\n## 맵 수정 제안 (briefs/*.md)")
for t, n in props.most_common(): print(f"- {t} ({n}회)")
if not props: print("- 없음")
EOF
```

## 2. 확인 대기 점검

"확인 대기" 각 줄에 대해 WebSearch 로 그 뒤 무슨 일이 있었는지 확인한다.
- 예상 결과가 나타났으면(집행·투자 집행·자금 유입 지속·이용 증가) "유지"라고 적는다.
- 뒤집혔으면(철회·취소·파기·폐지) 출처 URL 과 함께 "번복"이라고 적고, 반대 방향 행을 `/brief` 로 올리자고 제안한다. `reverses` 에 그 줄 번호를 쓴다. 여기서 장부를 쓰지 않는다.
- 확인이 안 되면 "확인 안 됨".

## 3. 맵·소스 제안

- 방향·섹터: 90일 동안 신호 없는 섹터가 있으면 "소스가 못 보는 곳인지, 시장이 안 건드리는 곳인지"를 한 줄로 판단한다. 맵 수정 제안이 3회 이상 반복된 티커는 어느 섹터에 넣을지 제안한다. 새 방향(내러티브)이 필요해 보이면 이름과 소속 섹터를 제안한다.
- 소스: 축별 90일 건수가 한 축에 치우쳐 있으면(특히 사회 축이 적으면) sources.yaml 에 어떤 검색어·RSS 를 더하거나 뺄지 제안한다. raw 파일의 count 가 계속 0인 소스는 제거를 제안한다.
- 제안은 표로. Ken 이 승인한 것만 파일에 반영한다.

## 4. 출력 (채팅)

```markdown
# 월간 점검 (<월>)

## 섹터 정렬 (90일)
(스크립트 출력 그대로)

## 확인 대기 결과
- 줄 n: 유지 / 번복 (출처) / 확인 안 됨

## 맵·소스 제안
| 대상 | 현재 | 제안 | 근거 |

## 다음 달까지 볼 것
한두 줄
```

매매 표현 금지. 영향은 "~라는 가설"로 쓴다.
