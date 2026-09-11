# market-brief

## 목적

시장을 큰 그림으로 본다.
코인 / 기술권력(빅테크) / 정치권력(트럼프 행정부·의회) / 자본권력(월스트리트) 네 축 중
**어느 쪽이 점점 커지고 있는가**를 매일 관찰하고 장부에 누적해서,
3~4년 이상의 큰 흐름 안에서 어떤 시장이 상방이 크고 손익비가 좋은지 판단할 재료를 만든다.

이 레포의 산출물은 **판단 재료**이지 매매 신호가 아니다.

## 절대 규칙

1. 모든 뉴스는 `framework/axes.md`의 4축 중 하나로 분류한다. 어느 축에도 안 걸리면 버린다.
2. 팩트 / 해석 / 영향 섹터를 항상 분리해서 쓴다. 섞지 않는다.
3. 모든 시그널에 `structural: true|false` 태그를 단다. **장부(`ledger/`)에는 structural=true만 올린다.**
4. 영향 티커는 `framework/sector_map.yaml`에 있는 것만 인용한다. 목록에 없는 티커가 필요하면 브리프 하단 "맵 수정 제안"에만 적고 장부에는 넣지 않는다.
5. 출처 URL이 없는 팩트는 쓰지 않는다. 기억이나 추정으로 팩트를 만들지 않는다.
6. "사라", "팔아라", "지금이 기회" 류 표현 금지. 영향은 항상 "가설"로 서술한다.
7. 브리프는 짧게. 시그널 3~5개. 구조적 시그널이 없는 날은 "오늘 구조적 시그널 없음"이 정답이다. 억지로 채우지 않는다.
8. 미국 시장(미장) 영향 기준으로 판단한다. 한국 시장 영향은 부수적으로만 언급한다.

## 파일 구조

```
CLAUDE.md                  이 파일. 프레임워크와 규칙
framework/axes.md          4축 정의, "커진다/작아진다" 판단 기준
framework/sector_map.yaml  축 → 테마 → ETF/티커 매핑 (Ken이 큐레이션)
fetch/                     수집 스크립트 (python). 매일 06:00 KST GitHub Actions 가 실행해 raw/ 를 커밋
raw/YYYY-MM-DD/            당일 수집 원문. 비공개 저장소 radar-raw 에만 커밋 (여기서는 git 미추적)
briefs/YYYY-MM-DD.md       일간 브리프
ledger/signals.jsonl       구조적 시그널 누적 장부 (append only, 수정 금지)
.claude/commands/          /brief, /trend
logs/                      세션 로그 (/save 가 만듦, git 미추적)
site/                      웹페이지. build.py 가 briefs·ledger·framework 를 site/out/ 로 빌드, index.html 이 렌더
.github/workflows/         fetch.yml 06:00 KST 수집 → radar-raw 커밋, pages.yml push 마다 site/ 빌드·배포 (https://yukiadada.github.io/radar/)
```

매일 흐름: 06:00 KST Actions 수집 → 비공개 radar-raw 커밋 → 06:20 KST 클라우드 루틴(claude.ai/code/routines)이 radar 와 radar-raw 를 함께 받아 /brief 실행·push → Pages 갱신. 로컬에서 작업하기 전에 `git pull` 부터 한다. 로컬에서 /brief 를 돌리려면 `python3 fetch/fetch.py` 로 raw/ 를 만들면 된다(미추적).

## 워크플로

### /brief (매일)
1. `raw/오늘/` 전체를 읽는다. 없으면 `fetch/` 스크립트 실행을 먼저 제안한다.
2. 4축으로 분류 → 축별 후보 시그널 추출.
3. 각 후보에 structural 판정. 기준은 `framework/axes.md` 참고.
4. `briefs/오늘.md` 작성 (아래 템플릿).
5. structural=true 시그널만 `ledger/signals.jsonl`에 append.
6. "3~4년 논지 변화?" 섹션에 한 줄. 대부분 "없음"이어야 정상. (템플릿 순서상 "맵 수정 제안"이 그 뒤에 온다)

### /trend (주 1회 또는 요청 시)
1. `ledger/signals.jsonl`에서 최근 30일 / 90일을 읽는다.
2. 축별 시그널 수, 방향(+/-) 비율, 자주 등장하는 섹터를 집계한다.
3. "어느 축이 커지고 있는가"를 집계 숫자 근거로 한 문단 서술한다.
4. 축 간 충돌(예: 정치권력 vs 자본권력)이 반복되면 별도로 표시한다.

## 시그널 스키마 (ledger/signals.jsonl 한 줄)

```json
{
  "date": "2026-09-08",
  "axis": "정치권력",
  "theme": "관세/리쇼어링",
  "fact": "한 문장. 출처에 있는 내용만.",
  "source": "https://...",
  "structural": true,
  "sectors": ["XLI", "PWR"],
  "direction": "+",
  "confidence": 0.6,
  "note": "해석. 왜 구조적인지 한 줄."
}
```

- `axis`: 코인 | 기술권력 | 정치권력 | 자본권력
- `theme`: sector_map.yaml의 테마 키와 일치
- `direction`: 해당 섹터에 + / - / ± (양방향·불확실). 섹터 기준이지 축 기준이 아니다.
- `note`: `커짐.` / `작아짐.` / `유보.` 중 하나로 시작한다 (그 축이 커지는지). 그 뒤에 왜 구조적인지 한 줄. /trend가 이 첫 단어를 집계한다.
- 축 간 충돌이면 note 맨 앞에 `[충돌: A vs B] `를 붙이고 그 뒤에 커짐/작아짐/유보를 잇는다. A, B는 서로 다른 축, 순서는 정치권력 > 기술권력 > 자본권력 > 코인. 예: `[충돌: 정치권력 vs 자본권력] 유보. 인하 압박 vs 동결, 9/16 FOMC가 판정.`
- `confidence`: 0.3 낮음 / 0.6 보통 / 0.8 높음. 0.9 이상은 쓰지 않는다.

## 일간 브리프 템플릿

```markdown
# 2026-09-08 브리프

## 오늘의 축 시그널
| 축 | 팩트 (출처) | 구조적 | 영향 섹터·티커 | 방향 | 확신 |
|---|---|---|---|---|---|

- 해석 (축/테마): 행마다 한 줄. 커짐/작아짐과 이유. 팩트 셀에는 해석을 넣지 않는다.

## 쉬운 말로
- **시그널 짧은 이름**
  - 무슨 일: 중학생이 읽어도 되게. 전문용어는 괄호로 풀이
  - 왜 중요: 어느 축이 왜 커지거나 작아지는지
  - 누가 이득·손해: 섹터·티커를 쉬운 이름과 함께

## 누가 유리하고 불리한가
| 티커 | 무엇 | 방향 | 확신 | 왜 |
|---|---|---|---|---|

## 버린 뉴스 (한 줄씩, 왜 버렸는지)

## 30일 누적
- 정치권력: n건 (+x / -y)
- 기술권력: n건
- 자본권력: n건
- 코인: n건

## 3~4년 논지 변화?
없음 / 있음 — 있으면 한 문단

## 맵 수정 제안 (있을 때만)
```

## 작성 스타일

- 한국어. 티커·기관명은 영문 그대로.
- 시간은 미국 동부 기준(ET)으로 표기하고 KST를 괄호로 덧붙인다.
- 형용사 줄이고 숫자와 출처로 말한다.
- 모르면 "확인 안 됨"이라고 쓴다.
- "쉬운 말로"와 "누가 유리하고 불리한가"는 중학생 기준으로 쓴다. 관세, ETF, 연준, 반독점 같은 용어는 처음 나올 때 괄호로 한 줄 풀이. 환율 환산 같은 추정 숫자는 만들지 않는다.

## 현재 상태

> /save 자동 업데이트 — 2026-09-11 10:12

**브랜치:** main
**마지막 커밋:** fc6f87a raw/·logs/ 를 공개 저장소에서 제외. 수집 원문은 비공개 radar-raw 로, brief.md 에 분류 선례 3건

**미완료 항목:**
- 9/12 06:00 Actions 수집 → 06:20 루틴 첫 완전 자동 실행 확인. 사이트에 브리프 없으면 루틴 로그(claude.ai/code/routines/trig_01564MDnvQH3DtPRvCiqfaDY) 확인
- Ken: claude.ai/code Default 환경 네트워크 접근 확대(루틴의 1차 출처 WebFetch 가 EGRESS_BLOCKED)
- 로컬 작업 전 `git pull` 필수. 로컬 /brief 는 `python3 fetch/fetch.py` 로 raw/ 를 먼저 만든다(미추적)
- 루틴 사용량(실행당 opus-5 약 8분)이 매일 누적됨. 부담되면 모델을 sonnet-5 로 변경 가능
- 운영 저장소: https://github.com/yukiadada/radar (public, raw/·logs/ 제외), https://github.com/yukiadada/radar-raw (private, raw). 사이트 https://yukiadada.github.io/radar/
