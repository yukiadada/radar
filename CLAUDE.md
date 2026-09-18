# radar

## 목적

"현재 세상은 이 방향으로 흐르고 있고, 그에 해당하는 섹터는 어디인가?"

세상의 방향(내러티브)은 **기술 · 사회적 트렌드 · 정책** 세 축으로 읽는다. 매일 뉴스를 세 축으로 분류해 장부에 누적하고,
장부(과거 데이터)를 근거로 섹터마다 **세 축이 얼마나 같은 쪽을 가리키는지를 %로** 내고, 그 추이를 라인 그래프로 본다.
기술이 혁신적이고, 사회가 그 기술을 원하며, 정부까지 밀어주는 분야 — 세 축이 하나로 정렬되는 순간 그 분야에 돈이 몰리는 것은 거의 필연에 가깝다.

이 레포의 산출물은 **판단 재료**이지 매매 신호가 아니다.

## 절대 규칙

1. 모든 뉴스는 `framework/axes.md`의 3축(기술 / 사회 / 정책) 중 하나로 분류한다. 어느 축에도 안 걸리면 버린다.
2. 팩트 / 해석 / 영향 섹터를 항상 분리해서 쓴다. 섞지 않는다.
3. 모든 시그널에 `structural: true|false` 태그를 단다. **장부(`ledger/signals.jsonl`)에는 structural=true 만 올린다.**
4. 섹터 이름과 티커는 `framework/sector_map.yaml`에 있는 것만 쓴다. 없는 티커가 필요하면 브리프 하단 "맵 수정 제안"에만 적는다.
5. 출처 URL이 없는 팩트는 쓰지 않는다. 기억이나 추정으로 팩트를 만들지 않는다.
6. "사라", "팔아라", "지금이 기회" 류 표현 금지. 영향은 항상 "가설"로 서술한다.
7. 브리프는 짧게. 시그널은 하루 최대 6개(축당 2개 안팎). 구조적 시그널이 없는 날은 "오늘 구조적 시그널 없음"이 정답이다. 억지로 채우지 않는다.
8. 미국 시장(미장) 영향 기준으로 판단한다. 한국 시장 영향은 부수적으로만 언급한다.
9. 장부는 append only. 쓰는 유일한 수단은 `fetch/ledger.py --append`. 기존 줄은 어떤 이유로도 고치지 않는다.

## 파일 구조

```
CLAUDE.md                  이 파일. 프레임워크와 규칙
framework/axes.md          3축 정의, 축별 질문·밀어줌/막음 신호·구조적 판정, 정렬 % 계산식 (Ken 이 큐레이션)
framework/sector_map.yaml  방향(내러티브) → 섹터 → 티커·keywords (Ken 이 큐레이션)
framework/sources.yaml     수집 소스 (RSS·Google News 검색어) 와 축 힌트 (Ken 이 큐레이션)
fetch/                     fetch.py 수집, ledger.py 장부 검증·추가(장부에 쓰는 유일한 수단), scoring.py 정렬 %·추이·관심, config.py yaml 파서, gn_decode.py,
                           market.py 종가 갱신·시장 반응 계산(--update / --report), backfill.py 과거 raw 소급 수집
raw/YYYY-MM-DD/            당일 수집 원문. 비공개 저장소 radar-raw 에만 커밋 (여기서는 ../radar-raw/raw 심볼릭 링크, git 미추적). 2026-06-19~09-16 은 backfill.py 소급분(backfill:true, 그날 수집보다 성김)
prices/prices.json         sector_map 티커 + SPY 일별 종가 (Cboe 지연 시세). radar-raw 의 prices/ 심볼릭 링크. fetch.yml 이 매일 갱신·커밋
briefs/YYYY-MM-DD.md       일간 브리프 (축별 기사 + 쉬운 말로 + 섹터 정렬 표)
ledger/signals.jsonl       구조적 시그널 누적 장부 (append only)
.claude/commands/          /brief, /trend, /review
site/                      웹페이지. build.py 가 briefs·ledger·framework·raw 를 site/out/ 로 빌드, index.html 이 렌더
.github/workflows/         fetch.yml 수집, pages.yml 사이트 빌드·배포
backlog/                   2026-09-17 이전의 4축(정치·기술·자본·코인) 체계 보관본. 실행되지 않는다. backlog/README.md 참고
logs/                      세션 로그 (/save 가 만듦, git 미추적)
```

매일 흐름 (시각은 여기에만 적는다): 04:30 KST GitHub Actions(fetch.yml) 예약 수집 + 종가 갱신(market.py --update)(05:15 KST 에 한 번 더. 워크플로는 멱등) → 비공개 radar-raw 커밋 → 06:20 KST 클라우드 루틴(claude.ai/code/routines)이 radar 와 radar-raw 를 함께 받아 /brief 실행·push → Pages 갱신(07:00 KST 에 한 번 더 빌드). GitHub 예약은 1~2시간 늦을 수 있어 루틴은 raw 가 없으면 fetch.yml 을 직접 실행하고 기다린다. 사이트 https://yukiadada.github.io/radar/. 로컬에서 작업하기 전에 `git pull` 부터 한다. 로컬에서 /brief 를 돌리려면 `python3 fetch/fetch.py` 로 raw/ 를 만들면 된다(미추적, feedparser 필요).

## 워크플로

### /brief (매일)
1. `raw/오늘/` 전체를 읽는다. 없으면 `fetch/` 스크립트 실행을 먼저 제안한다.
2. 3축으로 분류 → 축별 후보 시그널 추출. 축은 사건의 주체로 정한다: 정부가 한 일이면 정책, 통계·수용·채택이면 사회, 기술·공급·capex·계약이면 기술.
3. 각 후보에 structural 판정과 섹터·티커·방향(섹터 기준 +/−/±)을 정한다. 기준은 `framework/axes.md`. 함께 horizon(분기/1년/다년)·impact(1~3)·channel(실적/멀티플/수급)을 정한다.
4. structural=true 시그널을 `fetch/ledger.py` 로 검증하고(append 없이) 30일 누적(새로 들어온 건수)과 섹터 정렬 표(살아 있는 시그널의 누적. axes.md "3축 정렬")를 받는다. `fetch/market.py --report` 로 최근 30일 시그널의 시장 반응 표를 받는다.
5. `briefs/오늘.md` 작성 (아래 템플릿). 섹터 정렬 표는 4의 출력을 그대로 붙인다.
6. 같은 rows 로 `fetch/ledger.py --append`.
7. `python3 site/build.py` 로 빌드가 되는지 확인한다 (경고가 있으면 채팅 요약에 적는다). 빌드 실패는 사이트가 조용히 멈추는 원인이라 push 전에 잡는다.

### /trend (주 1회 또는 요청 시)
1. 장부 누적(살아 있는 시그널, 유효기간 기준) / 최근 30일(새 근거) / 열린 긴 창: 축별 건수와 방향(+/−/±), 섹터별 정렬 %(기술·사회·정책 축 점수, 상태, 7일·30일 변화), 방향별 %. 수준은 누적으로, 변화는 30일 창으로 읽는다.
2. "지금 세상은 어느 방향으로 흐르는가"를 집계 숫자 근거로 한 문단 서술한다. 3축 정렬 섹터 / 엇갈림 섹터 / 역풍 섹터를 나눈다.
3. 관심(수집 헤드라인 keywords 언급량)과 붙여 "관심은 높은데 근거는 없는 곳 / 관심은 낮은데 근거가 쌓이는 곳"을 짚는다.
4. 번복 행(`reverses`), 확인 대기(30일 넘은 + 시그널), 맵 수정 제안 반복 횟수를 표시한다.

### /review (월 1회)
1. 확인 대기 시그널의 예상 결과가 실제로 나타났는지 확인한다. 뒤집혔으면 반대 방향 행을 /brief 로 올리자고 제안한다 (`reverses`에 이전 줄 번호).
2. 방향·섹터 맵(sector_map.yaml)과 소스(sources.yaml)의 수정을 제안한다. Ken 이 승인해야 고친다.

## 시그널 스키마 (ledger/signals.jsonl 한 줄)

```json
{
  "date": "2026-09-18",
  "axis": "정책",
  "sector": "AI 반도체",
  "fact": "한 문장. 출처에 있는 내용만.",
  "source": "https://...",
  "structural": true,
  "tickers": ["SMH", "NVDA"],
  "direction": "+",
  "confidence": 0.6,
  "note": "해석. 왜 이 축이 이 섹터를 밀거나 막는지, 왜 구조적인지 한 줄.",
  "horizon": "1년",
  "impact": 2,
  "channel": "실적",
  "reverses": null
}
```

- `axis`: 기술 | 사회 | 정책
- `sector`: sector_map.yaml 의 섹터 키와 일치. 같은 사건이 두 섹터에 반대로 작용하면 섹터마다 한 줄.
- `tickers`: 그 섹터의 티커 1~3개. 다른 섹터의 티커를 쓰면 note 에 이유.
- `direction`: 그 섹터에 + / - / ± (양방향·불확실). 섹터 기준이지 축 기준이 아니다.
- `confidence`: 0.3 낮음 / 0.6 보통 / 0.8 높음. 0.9 이상은 쓰지 않는다. "사실이 맞는가"의 확신이지 중요도가 아니다. structural=true 는 0.6 이상.
- `horizon`: 분기 | 1년 | 다년. axes.md "지속성 사다리"로 정한다.
- `impact`: 1 단일 기업·좁은 규칙 / 2 산업·섹터 / 3 시장 전체 또는 방향 자체.
- `channel`: 실적 | 멀티플 | 수급.
- `reverses`: 이전 시그널을 뒤집는 행이면 그 줄 번호, 아니면 null. 뒤집는 행은 이전 줄과 반대 방향이어야 한다 (ledger.py 가 검사).
- 정렬 % 계산: 가중치 w = impact × horizon(분기 1, 1년 2, 다년 3). 축 점수 = clamp(Σ 방향×w ÷ 6, −1, +1). 정렬 % = 50 + 50 × 세 축 평균 (axes.md "3축 정렬"). 상태는 3축 정렬 / 2축 정렬 / 1축 / 엇갈림 / 양쪽 / 역풍 / 신호 없음. `fetch/scoring.py` 가 유일한 구현이다.
- 시장 반응: 시그널마다 사건 전날(장부 날짜 이틀 전) 종가 대비 시그널 티커 평균의 1·5·20·60거래일 수익률과 같은 기간 SPY 를 `fetch/market.py` 가 계산한다 (Cboe 지연 시세, prices/prices.json). 판정(방향대로/반대로/보합/아직)은 완료된 가장 긴 구간의 SPY 대비 초과수익 부호를 방향과 비교한 것이고 ± 시그널은 판정하지 않는다. 사이트 카드·장부·섹터 상세와 브리프 "시장 반응" 절에 보인다. 과거 반응은 판단 재료이지 매매 신호가 아니다 (규칙 6).
- 사이트 빌드(site/build.py)는 자료 문제(깨진 장부 줄, sector_map 오류, 맵에 없는 섹터, 브리프 형식)로 멈추지 않고 data.json 의 warnings 에 적어 사이트 상단 배너로 보여준다. 배너가 보이면 그 자료를 고친다.
- 장부 1~11번 줄은 backlog 의 4축 장부 11건을 2026-09-17 에 3축으로 다시 분류해 `fetch/ledger.py --append` 로 날짜별로 옮긴 것이다 (note 끝 "(이관: 구 장부 n번 줄)"). 이관 시 부여한 기간·크기·경로는 이관 판단이다. 이 11줄은 팩트 첫 문장 40자 규칙과 note 접미어 규칙(확인 등급 접미어가 맨 끝) 이전에 쓰인 것이라 그 규칙에 어긋나지만 append only 라 그대로 둔다. 12번 줄부터는 ledger.py 가 두 규칙을 검사한다.

## 일간 브리프 템플릿

```markdown
# 2026-09-18 브리프

## 기술
| 팩트 (출처) | 구조적 | 섹터 · 티커 | 방향 | 확신 |
|---|---|---|---|---|

- 해석: 행마다 한 줄. 왜 이 축이 이 섹터를 밀거나 막는지. (기간 · 크기 · 경로)

## 사회
해당 없음

## 정책
(같은 표)

## 쉬운 말로
- **시그널 짧은 이름**
  - 무슨 일: 중학생이 읽어도 되게. 전문용어는 괄호로 풀이
  - 왜 중요: 어느 축이 어느 섹터를 왜 밀거나 막는지
  - 이득 (티커, 티커): 누가 왜 이득인지 한 줄. 티커의 쉬운 이름을 넣는다
  - 손해 (티커): 누가 왜 손해인지 한 줄. 해당 없으면 이 줄을 뺀다

## 섹터 정렬 (누적)
| 섹터 | 기술 | 사회 | 정책 | 정렬 | 상태 | 7일 변화 |
|---|---|---|---|---|---|---|
(ledger.py 출력 그대로. 살아 있는 시그널 기준)

## 버린 뉴스 (한 줄씩, 왜 버렸는지)

## 30일 누적
- 기술: n건 (+x / -y / ±z)
- 사회: n건 (+x / -y / ±z)
- 정책: n건 (+x / -y / ±z)

## 시장 반응 (최근 30일 시그널)
(market.py --report 출력 그대로)

## 맵 수정 제안 (있을 때만)
```

- 축 절에 시그널이 없으면 표 대신 `해당 없음` 한 줄. 세 축 모두 구조적 시그널이 없으면 "정책" 절 아래에 `오늘 구조적 시그널 없음` 한 줄을 더 쓴다.
- "쉬운 말로" 항목은 세 축 표의 행을 기술 → 사회 → 정책 순서로 이어 붙인 순서와 같다 (사이트가 그 순서로 카드를 만든다).

## 작성 스타일

- 한국어. 티커·기관명은 영문 그대로.
- 시간은 미국 동부 기준(ET)으로 표기하고 KST를 괄호로 덧붙인다.
- 형용사 줄이고 숫자와 출처로 말한다.
- 시그널 표의 팩트 셀은 첫 문장을 40자 안팎으로 "누가 무엇을 했다"로 쓴다. 문서 번호·조항·시각·세부 숫자는 두 번째 문장부터. 사이트가 첫 문장을 카드 제목으로 쓴다.
- 모르면 "확인 안 됨"이라고 쓴다.
- "쉬운 말로"는 중학생 기준으로 쓴다. 관세, ETF, 연준, 반독점 같은 용어는 처음 나올 때 괄호로 한 줄 풀이. 환율 환산 같은 추정 숫자는 만들지 않는다.

## 현재 상태

> /save 자동 업데이트 — 2026-09-18 12:25

**브랜치:** main
**마지막 커밋:** 5a6cf15 오늘 탭 최상단의 날짜 줄과 정보 칩(장부 건수·시작일·수집 소스) 삭제

**미완료 항목:**
- 사이트(site/index.html): 이름 Radar. 글꼴 IBM Plex Sans KR 단일(Google Fonts, 막히면 시스템 고딕), 화면마다 h1 구조, 설명은 "기호 읽는 법" 펼침, 모서리 3단계(상자 12·조작 8·배지 6), 섹터·섹터 상세·추이의 기간 탭은 머리글 아래 8px 고정(배경 없음). 새 화면은 pageHead·secHead·legendBox 부품과 토큰을 쓴다. 긴 대시(—)·알약 모양·색 띠·반투명 흐림은 쓰지 않는다
- 오늘 탭: 제목·설명 → 오늘의 브리프(축별 카드만, 카드가 200px 넘으면 그라데이션 + 글자 버튼 "더 보기") → 방향별 정렬 → 쉬운 말로 읽는 지금의 방향 → 섹터 한눈에 → 지난 브리프. 요약 4칸·날짜 줄·정보 칩은 뺐다. 섹터 정렬·버린 뉴스·30일 누적·시장 반응·맵 수정 제안은 브리프 탭에만
- 오늘 탭 카드 안의 "원본 시그널 표 · 해석 · 확인 방법 메모" 펼침은 남아 있음. 브리프 탭으로 옮길지 Ken 판단
- 이용약관·개인정보처리방침(site/legal/*.md, #/terms #/privacy)의 [입력 필요]·[확인 필요] 16곳을 Ken 이 채운다. 책임 제한 문구는 법률 검토, Cboe 지연 시세 게시 조건 확인. 외부 요청 목록(GitHub Pages·Google Fonts·cdnjs)이나 브라우저 저장 값이 바뀌면 privacy.md 도 고친다
- 로고·아이콘·공유 이미지는 site/static (원본 logo.png, og.png 1200×630). og.png 는 2026-09-18 에 "Radar" 로 다시 만들고 눈으로 확인. 로고 원본이 Ken 이 준 것과 다르면 다시 생성
- briefs/direction.md(홈 "방향 브리프")는 2026-09-17 w30 숫자로 쓴 손글씨 문서. 자동 갱신 없음. 장부가 쌓이면 카드 숫자와 어긋나므로 /trend 때 같이 다시 쓸지 Ken 판단
- GitHub 예약 수집은 여전히 1~3시간 늦음(9/18 은 07:23·07:51 KST). 루틴이 06:21 KST 에 직접 실행해 브리프는 제때 나옴. 9/18 raw 23소스 정상(bea_releases 0건은 발표 없음, ftc_press 4건), 종가 갱신 정상
- 루틴 프롬프트가 옛 4축 파일(companies 등)을 언급하는지 확인하고 새 3축 /brief 에 맞춘다. 루틴 로그 claude.ai/code/routines/trig_01564MDnvQH3DtPRvCiqfaDY
- pages.yml 이 radar-raw 의 prices 를 받아 시장 반응이 매일 갱신되는지 확인 (data.json market_meta.asof)
- 장부 12~91번 줄(80건, 2026-06-25~09-16)은 2026-09-17 에 에이전트가 소급 작성한 행(1차 출처 본문 확인, ledger.py 검증). Ken 이 훑어보고 어긋난 행은 반대 방향 행(reverses)으로 처리, 기존 줄은 고치지 않는다
- 시장 반응 판정 "반대로" 30건은 첫 /review(10월 초)에서 근거가 틀렸는지·이미 반영됐는지·다른 힘이 컸는지 본다. 표본이 쌓이면 축·섹터별 비율
- gnews 7개·새 피드 10개 품질 첫 주 점검 후 sources.yaml 조정. court_opinions 키워드·법원 목록, pew_research 소음(하루 10~30건)이 조정 후보
- raw/2026-06-19~09-16 은 backfill.py 소급분(backfill:true, gnews 2일 청크 100건 캡이라 성김). 관심의 지난주 비교는 실제 수집분이 쌓이는 9/23 께부터. 키워드는 sector_map.yaml 의 keywords 에서 Ken 이 조정
- 못 쓰는 소스는 sources.yaml 머리말에 기록(BLS·NY Fed·Commerce·FCC 403, NRC 503, Gallup sitemap 뿐, Treasury·BIS 피드 없음, Census 보도자료 link 없음). 가격은 Stooq(JS 차단)·Yahoo(429) 대신 Cboe. FRED 는 이 환경에서 연결 실패
- 사이트 상단에 빌드 경고 배너가 보이면 그 자료(장부 줄·sector_map·브리프 형식·가격 자료 5일 이상 오래됨)를 고친다. 빌드는 멈추지 않는다
- 장부 1~11번 줄은 옛 장부의 3축 재분류(이관 판단). 첫 문장 40자·note 접미어 규칙의 예외. 12번 줄부터 ledger.py 가 검사
- 기업 관찰(SpaceX·BITO·Microsoft)은 새 스펙에 없어 뺐다. 필요하면 backlog 에서 복원
- Ken: claude.ai/code Default 환경 네트워크 접근 확대 (WebFetch EGRESS_BLOCKED 해제 시 1차 출처 본문 확인 가능 → confidence 0.8)
- 로컬 작업 전 `git pull` (../radar-raw 도). 로컬 raw·prices 는 ../radar-raw/raw, ../radar-raw/prices 심볼릭 링크. 장부는 `fetch/ledger.py --append` 로만
- 저장소: https://github.com/yukiadada/radar (public), https://github.com/yukiadada/radar-raw (private, raw·prices). 사이트 https://yukiadada.github.io/radar/
