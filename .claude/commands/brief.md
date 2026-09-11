---
description: raw/<날짜>를 읽어 4축 일간 브리프(briefs/<날짜>.md)를 쓰고 structural=true 시그널만 ledger에 append. Ken 이 직접 호출하거나 Ken 이 만든 클라우드 루틴이 실행한다. 모델이 스스로 호출하지 않는다
argument-hint: [YYYY-MM-DD]
disable-model-invocation: true
---

# /brief

CLAUDE.md "워크플로 > /brief"를 실행한다. 아래 순서를 건너뛰지 않는다. 모든 명령은 레포 루트에서 실행한다.

날짜: `$ARGUMENTS`가 `YYYY-MM-DD` 형식이면 그 날짜, 비어 있으면 `TZ=Asia/Seoul date +%F` 결과(한국 날짜. 클라우드는 UTC 라 TZ 를 반드시 붙인다). 그 외 형식이면 "날짜 형식 오류"라고 답하고 멈춘다. 이하 `<날짜>`.

## 0. 규칙 로드

1. `CLAUDE.md`, `framework/axes.md`, `framework/sector_map.yaml` 세 파일을 전부 읽는다. 매번 읽는다. 기억으로 대체하지 않는다.
2. sector_map.yaml에서 축 → 테마 키 → 티커 목록을 뽑아 둔다. 이 목록 밖의 테마 키와 티커는 브리프 표와 장부 어디에도 쓰지 않는다. 예외는 "맵 수정 제안" 섹션뿐이다.
3. `tail -n 40 ledger/signals.jsonl`로 최근 장부를 본다. 이미 기록된 사건은 출처 URL이 달라도 다시 올리지 않는다. 같은 사건의 후속 문서(예: 발표 → Federal Register 게재)는 새 시그널이다.

## 1. 원문 확인

1. `raw/<날짜>/*.json`을 확인한다. 폴더가 없거나 json 파일이 0개면 아래 한 줄만 답하고 멈춘다. 실행 여부는 Ken이 정한다.
   > raw/<날짜>/ 없음. 먼저 `python3 fetch/fetch.py --date <날짜>` 실행이 필요합니다.

   비대화형(클라우드 루틴)에서는 Actions 수집이 늦을 수 있으니 2분 간격으로 `git pull` 하며 최대 20분 기다린 뒤 그래도 없으면 멈춘다.
2. 파일이 있으면 전부 읽는다. 구조는 `{source, feed_url, fetched_at, window_hours, count, items: [{title, link, published, summary}]}`. 파일이 6개 미만이거나, count가 0이거나, `error` 필드가 있는(수집 실패) 소스가 있으면 기억해 두고 마지막 채팅 요약에 적는다(그 축은 입력이 없었다는 뜻).
3. `briefs/<날짜>.md`가 이미 있으면 내용을 보여주고 덮어쓸지 Ken에게 묻는다. 답을 받기 전에는 덮어쓰지 않는다. Ken이 거부하면 거기서 멈춘다. 장부도 건드리지 않는다. 비대화형(클라우드 루틴)에서는 묻지 않고 "이미 있음"을 출력하고 멈춘다.

## 2. 분류와 후보 추출

- 모든 항목을 axes.md의 4축 중 하나로 분류한다: 정치권력 / 기술권력 / 자본권력 / 코인. 어느 축에도 안 걸리면 버린다. 해외 중앙은행(ECB 등) 결정은 axes.md 자본권력 절에 적힌 대로 4축 밖이다. "버린 뉴스"에 "4축 범위 밖"으로 한 줄만 적고 FOMC 판단의 배경으로만 언급한다.
- 용어: **1차 출처**란 발행 기관 사이트다. whitehouse.gov, federalregister.gov(API `https://www.federalregister.gov/api/v1/documents/<문서번호>.json` 과 그 안의 raw_text_url 은 봇 차단 없이 열린다), federalreserve.gov, sec.gov, bls.gov, ecb.europa.eu 등. 이하 "1차 출처"는 이 뜻이다.
- Google News 항목은 `summary`가 제목과 같은 경우가 대부분이다. 헤드라인만으로 판단할 수 있는 것은 structural=false 판정과 "버린다" 판정뿐이다.
- **structural=true 후보는 확인 등급을 거친다.** 순서대로 시도하고, 도달한 등급의 제한을 지킨다.
  1. 본문 확인: 기사나 1차 출처를 WebFetch 로 연다. Google News 링크(news.google.com/rss/articles/...)는 WebFetch 로 직접 열리지 않으므로 `python3 fetch/gn_decode.py --raw <날짜> <source> <위치...>`(위치는 raw `items` 배열의 순서, 0부터) 또는 `python3 fetch/gn_decode.py <링크>` 로 실제 URL 을 얻은 뒤 연다. Google News 링크가 아니면 그대로 돌려준다. `ERROR` 가 나오거나 유료라 못 열면 같은 사건의 다른 기사나 1차 출처를 연다. 이 등급이면 confidence 0.6 또는 0.8.
  2. 검색 교차 확인: WebFetch 가 막힌 환경(EGRESS_BLOCKED)이면 WebSearch 로 같은 사건을 다룬 서로 다른 매체 2개 이상의 결과를 교차 확인한다. 이 등급이면 structural=true 는 허용하되 confidence 는 0.6 을 넘기지 않고, note 끝에 ` 확인: 검색 교차` 를 붙이고, 브리프 해석 아래에 "확인 방법 메모" 한 줄을 남긴다.
  3. 둘 다 안 되면 structural=false, confidence 0.3 으로 내리거나 버린다. 헤드라인만 보고 structural=true 를 쓰지 않는다.
- 숫자·날짜·주체는 확인한 출처에 있는 것만 쓴다. 검색 결과에서 얻은 숫자는 그 검색 결과 페이지의 URL 을 팩트 셀에 함께 적는다. URL 이 없으면 그 숫자를 쓰지 않는다(CLAUDE.md 규칙 5). 헤드라인끼리 숫자가 다르면 "확인 안 됨".
- 후보마다 아래 셋을 따로 적는다. 섞지 않는다.
  - 팩트: 출처에 있는 내용만 한 문장. 기억이나 추정으로 보강하지 않는다.
  - 해석: 왜 이 축이 커지거나 작아지는 신호인지. axes.md의 "커진다/작아진다" 기준을 인용한다. 팩트 셀에는 해석을, 해석에는 출처 없는 새 숫자를 넣지 않는다.
  - 영향 섹터: sector_map.yaml의 테마 키 하나 + 티커 최대 3개. 영향은 항상 "~라는 가설"로 쓴다.
- 같은 사건을 다루는 기사가 여럿이면 하나로 합친다.
- 출처(`source`) URL 규칙: 사실을 실제로 확인한 URL 을 쓴다. 1차 출처에서 확인했으면 그 URL, 그렇지 않으면 raw 의 `link` 를 그대로(Google News 리다이렉트 URL 포함). `source` 는 장부 중복 검사 키의 일부이므로 같은 사건이 날마다 같은 URL 이 되도록 1차 출처를 우선한다. 쓰지 않은 쪽(원문 URL 또는 raw 기사 제목)은 note 에 적는다.
- Federal Register 원문은 하루 수십~수백 건이다. 제목과 summary로 4축 관련만 고른다. 나머지는 "버린 뉴스"에 나열하지 않는다.
- 시각 표기: `published`는 UTC다. ET로 바꾸고 KST를 괄호로 덧붙인다. 3월 둘째 일요일~11월 첫째 일요일은 EDT(UTC-4), 그 외는 EST(UTC-5). Federal Register 항목은 `published`가 게재일 04:00 UTC 고정이므로 시각 대신 "M/D 게재"라고 쓴다. `published`가 null이면 시각을 쓰지 않는다.

## 3. structural 판정

- axes.md 각 축의 "구조적 판정" 기준을 그대로 적용한다. 요약:
  - true: 문서로 남고 3개월 이상 유효한 것. 법·행정명령·관세율, 실적 가이던스 숫자·체결된 계약·확정 판결, FOMC 결정·국채 발행 계획(QRA)·월 단위 자금흐름 방향 전환, 법안 통과·규제 확정·기업의 재무제표상 보유 결정.
  - false: 발언·트윗·인터뷰·"검토 중", 루머·애널리스트 추정·데모, 일간·주간 자금흐름·연준 위원 개별 발언, 가격 등락 자체·유명인 발언.
  - 제안 단계(NPRM, proposed rule, 의견 요청, 법안 발의)는 false다. 확정(final rule, 서명, 통과, 판결)만 true다.
  - 확정 문서라도 sector_map 테마의 티커에 직접 영향이 없으면 표와 장부에 올리지 않는다. "버린 뉴스"에 "구조적이나 맵 영향 없음"으로 적는다.
- 확신(confidence)은 0.3 / 0.6 / 0.8 중 하나. 0.9 이상은 쓰지 않는다.
- 방향(direction)은 **해당 섹터·티커** 기준 `+` / `-` / `±`. 축이 커지는지와는 다른 값이다.
- 축이 커지는지는 note의 첫 단어로 적는다: `커짐.` / `작아짐.` / `유보.` 그 뒤에 왜 구조적인지 한 줄. /trend가 이 단어를 집계한다.
- note 끝에는 확인 등급 접미어(` 확인: 검색 교차`)만 붙을 수 있다. 실행 환경 얘기(차단, 도구 이름 등)는 note 에 쓰지 않는다. 그런 메모는 브리프 해석 아래 "확인 방법 메모"에만.
- 두 축이 정면으로 부딪히는 사건이면 note 맨 앞에 `[충돌: A vs B] `를 붙이고 그 뒤에 커짐/작아짐/유보를 잇는다. A, B는 서로 다른 축이고 순서는 정치권력 > 기술권력 > 자본권력 > 코인 순으로 앞의 것을 A에 쓴다. 누가 이겼는지를 note에 적는다. 예: `[충돌: 정치권력 vs 자본권력] 유보. 인하 압박 vs 동결, 9/16 FOMC가 판정.`

## 4. 시그널 선정

- 브리프 표는 최대 5개. 0개도 가능하다. 후보가 적으면 있는 만큼만 쓴다. structural=false는 축 판단에 의미가 있을 때만 올리고, 채우기 위해 올리지 않는다.
- structural=true가 0개면 표 아래에 `오늘 구조적 시그널 없음` 한 줄을 쓴다.
- theme는 sector_map.yaml의 테마 키와 글자 단위로 같아야 한다. 티커는 시그널당 서로 다른 것 최대 3개, sector_map에 있는 것만. 원칙적으로 그 테마의 tickers에서 고르고, 다른 테마의 티커를 쓸 때는 note에 이유를 적는다.
- 맵에 없는 티커가 필요하면 "맵 수정 제안"에만 적고 표와 장부에는 넣지 않는다.
- 은행·운용사가 코인 상품 회사를 인수하거나 코인 상품을 내는 사건은 코인 축 "커짐"(axes "은행이 코인 사업 진입")이고, 테마는 상품 종류에 맞춘다(ETF 관련이면 현물 ETF).
- "사라", "팔아라", "지금이 기회" 류 매매 지시 표현 금지.

## 5. 검증 + 30일 집계 (APPEND = False)

아래 스크립트에 structural=true 시그널만 `ROWS`에 넣고 **`APPEND = False`인 채로** 실행한다. 검증과 30일 누적 계산만 하고 장부는 건드리지 않는다. 0개면 `ROWS = []`로 실행해서 집계만 받는다. 검증에 걸리면 시그널을 고쳐서 다시 실행한다.

`skip 중복`이 찍힌 행은 이미 장부에 있는 사건이다. 표에는 남겨도 되지만 장부에는 안 올라간다. 마지막 채팅 요약에 적는다. `경고 유사 사건`이 찍히면 최근 7일 장부의 같은 테마 행과 팩트가 많이 겹치는 것이다. 같은 사건이면(출처 URL 이 달라도) 그 행을 ROWS 에서 빼고 다시 실행한다. 다른 사건이면 그대로 진행한다.

```bash
python3 - <<'EOF'
import json, re, sys, datetime, collections
from pathlib import Path

DATE = "<날짜>"
APPEND = False   # 6단계에서 브리프를 쓴 뒤, 7단계에서 True 로 바꿔 같은 ROWS 로 다시 실행
ROWS = [
    # {"date": DATE, "axis": "정치권력", "theme": "관세/리쇼어링",
    #  "fact": "한 문장. 출처에 있는 내용만.", "source": "https://...",
    #  "structural": True, "sectors": ["XLI", "PWR"], "direction": "+", "confidence": 0.6,
    #  "note": "커짐. 왜 구조적인지 한 줄."},
]

if not Path("CLAUDE.md").exists(): sys.exit("레포 루트에서 실행해야 한다")
try: today = datetime.date.fromisoformat(DATE)
except ValueError: sys.exit(f"DATE 가 YYYY-MM-DD 가 아님: {DATE!r} (치환 누락?)")
AXES = ("정치권력", "기술권력", "자본권력", "코인")
KEYS = ["date", "axis", "theme", "fact", "source", "structural", "sectors", "direction", "confidence", "note"]

# sector_map.yaml → {테마: (축, [티커])}. 주석은 먼저 지운다.
themes, axis, theme, n_theme_lines = {}, None, None, 0
for raw in Path("framework/sector_map.yaml").read_text(encoding="utf-8").split("\n"):
    line = re.sub(r"\s#.*$|^#.*$", "", raw).rstrip()
    if not line.strip(): continue
    if re.match(r"^\S[^:]*:\s*$", line): axis, theme = line.strip()[:-1], None; continue
    m = re.match(r"^  (\S[^:]*):\s*$", line)
    if m: theme, n_theme_lines = m.group(1).strip(), n_theme_lines + 1; continue
    m = re.match(r"^\s+tickers:\s*\[(.*)\]\s*$", line)
    if m and theme and axis: themes[theme] = (axis, [t.strip().strip("'\"") for t in m.group(1).split(",") if t.strip()])
assert {a for a, _ in themes.values()} == set(AXES), f"sector_map 축 파싱 실패: {sorted(a for a, _ in themes.values())}"
assert len(themes) == n_theme_lines, f"테마 {n_theme_lines}개 중 {len(themes)}개만 파싱됨. sector_map.yaml 형식 확인"
all_tickers = {t for _, ts in themes.values() for t in ts}
assert all(re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,6}", t) for t in all_tickers), f"티커 형식 이상: {sorted(all_tickers)}"
print("sector_map:", ", ".join(f"{a} {sum(1 for x, _ in themes.values() if x == a)}테마" for a in AXES), f"/ 티커 {len(all_tickers)}개")

ledger = Path("ledger/signals.jsonl")
existing = []
if ledger.exists():
    for n, l in enumerate(ledger.read_text(encoding="utf-8").split("\n"), 1):
        if not l.strip(): continue
        try: existing.append(json.loads(l))
        except json.JSONDecodeError as e: sys.exit(f"ledger {n}번째 줄 JSON 파싱 실패: {e}. 장부는 수정 금지. Ken 에게 알린다")
seen = {(d["source"], d["theme"]): d["date"] for d in existing}
recent = [d for d in existing if (today - datetime.timedelta(days=7)).isoformat() <= d["date"] <= DATE]
if recent:
    print(f"최근 7일 장부 {len(recent)}건 (같은 사건이면 올리지 않는다):")
    for d in recent: print(f"  - {d['date']} [{d['axis']}/{d['theme']}] {d['fact'][:80]}")

BAD = re.compile(r"사라(?![지진질져졌짐])|팔아라|지금이 기회|매수 추천|매도 추천|사야 한다|팔아야 한다")
NOTE = re.compile(r"^(?:\[충돌: (정치권력|기술권력|자본권력|코인) vs (정치권력|기술권력|자본권력|코인)\] )?(커짐|작아짐|유보)(?![가-힣])")
URL = re.compile(r"^https?://[^\s/]+\.[^\s/]+\S*$")
errors, todo, skipped = [], [], []
for i, r in enumerate(ROWS):
    p = f"ROWS[{i}]"
    if not isinstance(r, dict) or set(r) != set(KEYS):
        errors.append(f"{p}: 키 구성이 스키마와 다름 {sorted(set(r) ^ set(KEYS)) if isinstance(r, dict) else type(r).__name__}"); continue
    r = dict(r)
    for k in ("date", "axis", "theme", "fact", "source", "note"):
        r[k] = " ".join(str(r[k]).split())   # U+2028 등 줄바꿈류 문자 제거. 장부는 한 줄 = 한 JSON
    if r["date"] != DATE: errors.append(f"{p}: date {r['date']!r} != DATE {DATE!r}")
    if r["structural"] is not True: errors.append(f"{p}: structural=true 만 장부에 올림")
    if r["axis"] not in AXES: errors.append(f"{p}: axis {r['axis']!r}")
    if r["theme"] not in themes: errors.append(f"{p}: theme {r['theme']!r} 가 sector_map 에 없음")
    elif themes[r["theme"]][0] != r["axis"]: errors.append(f"{p}: theme {r['theme']!r} 는 {themes[r['theme']][0]} 축")
    s = r["sectors"]
    if not isinstance(s, list) or not (1 <= len(s) <= 3) or len(set(s)) != len(s): errors.append(f"{p}: sectors 는 서로 다른 티커 1~3개")
    else:
        for t in s:
            if t not in all_tickers: errors.append(f"{p}: 티커 {t} 가 sector_map 에 없음")
            elif r["theme"] in themes and t not in themes[r["theme"]][1]: print(f"경고 {p}: 티커 {t} 는 테마 {r['theme']!r} 밖 (맵에는 있음). note 에 이유가 있어야 한다")
    if r["direction"] not in ("+", "-", "±"): errors.append(f"{p}: direction 은 + / - / ±")
    if r["confidence"] not in (0.3, 0.6, 0.8): errors.append(f"{p}: confidence 는 0.3 / 0.6 / 0.8")
    if not URL.match(r["source"]): errors.append(f"{p}: source 가 URL 이 아님")
    if not r["fact"]: errors.append(f"{p}: fact 비어 있음")
    m = NOTE.match(r["note"])
    if not m: errors.append(f"{p}: note 는 '[충돌: A vs B] '(선택) + '커짐.'|'작아짐.'|'유보.' 로 시작해야 함")
    elif m.group(1) and (m.group(1) == m.group(2) or AXES.index(m.group(1)) > AXES.index(m.group(2))): errors.append(f"{p}: 충돌 태그는 서로 다른 축을 {' > '.join(AXES)} 순서로")
    if BAD.search(r["fact"] + " " + r["note"]): errors.append(f"{p}: 매매 지시 표현 금지")
    grams = lambda t: {t[i:i + 2] for t in [re.sub(r"[^가-힣a-z0-9]", "", t.lower())] for i in range(len(t) - 1)}
    g = grams(r["fact"])
    for d in recent:
        if d["theme"] == r["theme"] and d["source"] != r["source"]:
            h = grams(d["fact"]); j = len(g & h) / max(1, len(g | h))
            if j >= 0.35: print(f"경고 유사 사건 {p}: {d['date']} 장부 행과 팩트 겹침 {j:.2f}. 같은 사건이면 ROWS 에서 뺀다: {d['fact'][:70]}")
    key = (r["source"], r["theme"])
    if key in seen: skipped.append(f"{p}: 이미 {seen[key]} 에 기록됨 ({r['theme']}, {r['source'][:70]})"); continue
    seen[key] = DATE
    todo.append({k: r[k] for k in KEYS})
for s in skipped: print("skip 중복:", s)
if errors: print("검증 실패. append 안 함:\n  " + "\n  ".join(errors)); sys.exit(1)

if APPEND and todo:
    ledger.parent.mkdir(exist_ok=True)
    need_nl = ledger.exists() and ledger.stat().st_size > 0 and not ledger.read_bytes().endswith(b"\n")
    with open(ledger, "a", encoding="utf-8") as f:
        if need_nl: f.write("\n")
        for r in todo: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tail = [l for l in ledger.read_text(encoding="utf-8").split("\n") if l.strip()][-len(todo):]
    assert [json.loads(l) for l in tail] == todo, "append 검증 실패"
    print(f"appended {len(todo)} (ledger 총 {len(existing) + len(todo)}줄)")
elif APPEND: print("appended 0")
else: print(f"검증 통과 {len(todo)}건 (APPEND=False, 장부에는 아직 안 씀)")

cut = today - datetime.timedelta(days=30)
c = collections.defaultdict(collections.Counter)
for d in existing + todo:
    try: dd = datetime.date.fromisoformat(d["date"])
    except ValueError: continue
    if cut < dd <= today: c[d["axis"]][d["direction"]] += 1
print("\n30일 누적")
for a in AXES:
    print(f"- {a}: {sum(c[a].values())}건 (+{c[a]['+']} / -{c[a]['-']} / ±{c[a]['±']})")
EOF
```

## 6. 브리프 작성

`briefs/<날짜>.md`를 CLAUDE.md 템플릿 그대로 쓴다. 섹션 제목과 순서를 바꾸지 않는다. 5단계 출력의 "30일 누적" 줄을 그대로 붙인다. `briefs/`가 없으면 만든다.

```markdown
# <날짜> 브리프

## 오늘의 축 시그널
| 축 | 팩트 (출처) | 구조적 | 영향 섹터·티커 | 방향 | 확신 |
|---|---|---|---|---|---|
| 정치권력 | 한 문장. 9/8 10:00 ET (23:00 KST). ([출처](https://...)) | true | 관세/리쇼어링 · XLI, PWR | + | 0.6 |

오늘 구조적 시그널 없음

- 해석 (정치권력/관세/리쇼어링): 한 줄. 커짐/작아짐과 그 이유. 영향은 가설로.

## 쉬운 말로
- **캐나다 관세**
  - 무슨 일: 무슨 일이 있었는지 한두 문장. 중학생이 읽어도 되게.
  - 왜 중요: 어느 축이 왜 커지거나 작아지는지.
  - 누가 이득·손해: 섹터·티커를 쉬운 이름과 함께 (예: 미국 산업재 ETF XLI).

## 누가 유리하고 불리한가
| 티커 | 무엇 | 방향 | 확신 | 왜 |
|---|---|---|---|---|
| XLI, CAT | 미국 산업재 ETF, 건설기계 회사 | ± | 0.6 | 한 줄 |

## 버린 뉴스 (한 줄씩, 왜 버렸는지)
- 제목 — 이유

## 30일 누적
- 정치권력: n건 (+x / -y / ±z)
- 기술권력: n건 (+x / -y / ±z)
- 자본권력: n건 (+x / -y / ±z)
- 코인: n건 (+x / -y / ±z)

## 3~4년 논지 변화?
없음

## 맵 수정 제안 (있을 때만)
- 티커 — 왜 필요한지 한 줄
```

템플릿 사용 규칙:
- `오늘 구조적 시그널 없음` 줄은 structural=true가 0개일 때만 쓴다. 있으면 그 줄을 지운다.
- 표 아래 "해석" 불릿은 표의 행마다 하나씩. 팩트 셀에 해석을 섞지 않기 위한 자리다(CLAUDE.md 규칙 2).
- "쉬운 말로"는 표의 행마다 하나씩, 무슨 일 / 왜 중요 / 누가 이득·손해 세 줄. 중학생이 읽는다고 생각하고 쓴다. 관세, ETF, 연준, 반독점 같은 용어는 처음 나올 때 괄호로 한 줄 풀이. 숫자는 출처 그대로 쓰고 환율 환산 같은 추정은 만들지 않는다.
- "누가 유리하고 불리한가"는 시그널 표에 나온 티커만, 방향과 확신은 시그널 표와 같은 값. "무엇"은 티커의 쉬운 이름, "왜"는 한 줄. 매매 지시 표현 금지는 여기도 같다.
- "버린 뉴스"는 축에 걸릴 듯했지만 버린 것만 최대 10줄. 이유 예: 발언만 있고 문서 없음 / 제안 단계 / 4축 어디에도 안 걸림 / 가격 등락 자체 / 같은 사건 중복 / 구조적이나 맵 영향 없음.
- "3~4년 논지 변화?"는 대부분 "없음"이다. "있음"이면 한 문단으로 무엇이 바뀌었는지 쓴다.
- "맵 수정 제안" 섹션은 제안이 있을 때만 쓴다. 없으면 섹션 자체를 생략한다.
- 한국어. 티커·기관명은 영문 그대로. 형용사를 줄이고 숫자와 출처로 말한다. 팩트 셀에는 출처 URL 링크를 반드시 넣는다. 미국 시장 영향 기준. 한국 시장은 부수적으로만.

## 7. 장부 append (APPEND = True)

브리프 파일을 쓴 다음, 5단계와 **같은 ROWS를 바꾸지 않고** `APPEND = True`로만 바꿔 같은 스크립트를 다시 실행한다. 출력에 `appended n`과 5단계와 같은 30일 누적 숫자가 나와야 한다. 다르면 멈추고 Ken에게 알린다.

장부 규칙:
- `ledger/signals.jsonl`에 쓰는 유일한 수단은 이 스크립트다. Edit/Write 도구, Bash 리다이렉션(`>`, `>>`), `sed`, `tee`, 별도 python 등 다른 어떤 방법으로도 쓰지 않는다.
- 기존 줄은 어떤 이유로도 수정·삭제하지 않는다. 잘못 올라간 줄이 있으면 Ken에게 알리고 그대로 둔다.
- 검증에 하나라도 걸리면 아무것도 append되지 않는다.

## 8. 마무리 (채팅 출력)

- 표를 축·팩트 한 줄·구조적·티커로 요약해 보여준다.
- "장부 추가 n건", "중복으로 건너뜀 n건", "3~4년 논지 변화: 없음/있음".
- 수집 현황: 소스 6개 중 파일이 없거나 count 0인 소스가 있으면 이름을 적는다.
- 만든 파일 경로: `briefs/<날짜>.md`, 그리고 append가 있었으면 `ledger/signals.jsonl`.
