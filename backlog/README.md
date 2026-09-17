# backlog — 4축(정치권력·기술권력·자본권력·코인) 체계의 보관본

2026-09-17 에 radar 를 3축(기술·사회·정책) 체계로 완전 리뉴얼하면서, 그 전까지 쓰던 코드와 문서를 여기로 옮겼다.
실행되지 않는다. 참고와 복구용이다. 새 체계는 레포 루트의 `CLAUDE.md` 부터 읽는다.

| 경로 | 원래 위치 | 내용 |
|---|---|---|
| `CLAUDE.md` | `/CLAUDE.md` | 4축 프레임워크와 규칙, 워크플로, 스키마, 브리프 템플릿 |
| `framework/` | `/framework/` | axes.md(4축 정의), sector_map.yaml(축→테마→티커), thesis.md(T1~T5 논지), backdrop.md(월간 배경 지표, 비어 있음), companies.yaml(기업 관찰 SpaceX·BITO·Microsoft) |
| `fetch/` | `/fetch/` | fetch.py(수집), config.py(yaml 파서), ledger.py(장부 검증), scoring.py(섹터 보드·관심 테마), gn_decode.py |
| `site/` | `/site/` | build.py, index.html (오늘·섹터·트렌드·기업·장부·브리프·기준 탭) |
| `briefs/` | `/briefs/` | 2026-09-10 ~ 09-17 일간 브리프 8건 (4축 템플릿) |
| `ledger/` | `/ledger/` | signals.jsonl 11줄(4축 구조적 시그널), companies.jsonl 35줄(기업 관찰). append only 였으므로 그대로 둔다 |
| `commands/` | `/.claude/commands/` | /brief, /trend, /review |
| `workflows/` | `/.github/workflows/` | fetch.yml, pages.yml |

새 체계로 가져간 것: 수집 파이프라인(fetch.py 구조, raw 형식, radar-raw 비공개 저장소, GitHub Actions 예약), 장부 검증 방식(ledger.py 가 유일한 쓰기 수단, append only), 지속성 사다리(horizon)·크기(impact)·경로(channel) 가중, 사이트의 디자인 토큰·차트 프레임·마크다운 렌더, 티커 화이트리스트와 keywords.
새 장부(`/ledger/signals.jsonl`)의 첫 11줄은 여기 `ledger/signals.jsonl` 의 11건을 3축으로 다시 분류해 옮긴 것이다(각 줄 note 끝에 "이관: 구 장부 n번 줄").
