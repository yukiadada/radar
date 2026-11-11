---
description: 매일 흐름(루틴·수집·배포·빌드·소스·장부·종가·브리프 내용)이 제대로 돌았는지 지난 점검 다음 날부터 오늘까지 점검해 채팅에 표로 낸다. 파일은 고치지 않는다. 기록은 /save 가 CLAUDE.md "현재 상태"에 남긴다
argument-hint: [YYYY-MM-DD | YYYY-MM-DD~YYYY-MM-DD]
---

# /check

레포 루트에서 실행한다. **읽기만 한다.** 장부·브리프·framework·CLAUDE.md 를 고치지 않고 커밋하지 않는다. 문제를 찾으면 원인과 고칠 곳을 채팅에 적고, 고칠지는 Ken 이 정한다. 점검 결과를 남기려면 이어서 /save 를 실행한다.

기간: `$ARGUMENTS` 가 `YYYY-MM-DD` 면 그 하루, `YYYY-MM-DD~YYYY-MM-DD` 면 그 기간. 비어 있으면 CLAUDE.md "현재 상태"의 마지막 "M/D~M/D 점검" 항목 끝 날의 다음 날부터 오늘(`TZ=Asia/Seoul date +%F`)까지 (그 항목이 없거나 끝 날이 오늘이면 오늘 하루. `fetch/check.py` 가 같은 규칙으로 정한다). 그 외 형식이면 "날짜 형식 오류"라고 답하고 멈춘다. 이하 `<기간>`, 날짜는 모두 KST.

## 0. 준비

1. `git fetch origin main`. 루틴은 main 에 푸시하므로 점검은 origin/main 기준이다.
   - 현재 브랜치가 main 이면 `git pull --rebase --autostash origin main`.
   - 다른 브랜치이고 `git merge-base --is-ancestor origin/main HEAD` 가 실패하면(main 보다 뒤처짐) 브랜치를 건드리지 말고 scratchpad(없으면 `/tmp`)에 `git worktree add --detach <scratch>/radar-main origin/main` 을 만들어 1~6단계를 그 안에서 실행하고, 끝나면 `git worktree remove --force <scratch>/radar-main` 으로 지운다.
2. raw·prices 링크(비공개 radar-raw). 점검하는 트리에 `raw`·`prices` 가 없으면:
   - `../radar-raw` 가 있으면(로컬) `git -C ../radar-raw pull --rebase` 후 `ln -s <radar-raw 절대 경로>/raw raw`, `ln -s <radar-raw 절대 경로>/prices prices`.
   - 없으면(클라우드) `add_repo`(owner yukiadada, repo radar-raw, access read)로 붙이고 그 결과가 알려주는 clone 명령으로 받은 뒤 같은 링크를 만든다.
   - 붙이지 못하면 소스·종가 절은 "확인 안 됨"으로 두고 나머지만 한다. 이때 빌드 경고 0 에는 가격 경고가 빠져 있다는 것도 적는다 (build.py 는 prices 가 없으면 가격 경고를 내지 않는다).
   - 링크는 `.gitignore` 에 있어 커밋되지 않는다.
3. 브리프가 읽은 시점의 수집 오류는 radar-raw 의 git 이력으로 본다. `git -C <radar-raw> rev-parse --is-shallow-repository` 가 `true` 면 `git -C <radar-raw> fetch --depth=200 origin main` 을 한 번 한다 (`--unshallow` 는 쓰지 않는다).

## 1. 집계 (fetch/check.py)

```bash
python3 fetch/check.py --from <기간 시작> --to <기간 끝>
```

인자 없이 실행하면 위 기간 규칙을 쓴다. 출력의 숫자만 쓴다. 직접 세지 않는다. 절마다 보는 것:

- **루틴**: 날마다 `brief <날짜>: 구조적 시그널 N건 (routine)` 커밋이 하나, 작성자 radar routine, 브리프·direction.md(·N>0 이면 장부) 포함, N = 장부의 그날 행 수. 커밋 시각(보통 06:2x KST)이 늦은 날은 따로 적는다. 오늘 점검이면 direction.md 첫 줄 날짜가 오늘인지.
- **소스**: 파일 수가 소스 수와 같은지, 지금 오류가 있는 소스, 그리고 "브리프 시점" 오류(브리프가 실제로 읽은 파일). 브리프 시점 오류가 있으면 그 소스의 그날 항목이 다음 날 수집(48시간 창)으로 브리프에 들어갔는지 다음 날 브리프와 raw 로 확인한다. 0건은 피드에 새 글이 없는 날이라 하루치는 정상이다. "기간 내내 0건" 소스는 현재 상태의 수집 소스 항목(bea_releases·doj_antitrust 등)과 비교한다.
- **장부**: 하루 건수(6 은 상한), `오늘 구조적 시그널 없음` 날, ± 비율(현재 상태 "방향 ± 비율" 항목의 기준: 20% 넘게 오르면 axes.md 문구 제안 후보), 확신 분포(0.8 이 나온 행), 번복 행. 끝의 `장부 경고` 줄은 깨진 장부 줄이다. 장부는 고치지 않고 Ken 에게 알린다.
- **종가**: 마지막 종가가 오늘보다 며칠 전인지. 1~3거래일 늦은 것은 Cboe 지연이라 정상이고, 5일을 넘으면 build.py 가 경고한다.
- **브리프 내용**: 맵 수정 제안(같은 티커 제안 반복 횟수), 버린 이유 합계와 같은 사건·같은 기관이 여러 날 버려진 것(특히 "구조적이나 맵 영향 없음" 반복은 /review 맵 검토 후보, 같은 사건을 날마다 다르게 판정했으면 적는다), 열리지 않은 호스트(현재 상태 네트워크 항목의 허용 목록·후보와 비교해 새 후보만 따로 적는다).

## 2. 수집·배포 (GitHub Actions)

GitHub MCP `actions_list`(method list_workflow_runs, owner yukiadada, repo radar, resource_id `fetch.yml` 와 `pages.yml` 각각, perPage 30)로 `<기간>` 의 실행을 본다. 시각은 UTC 라 KST 로 바꾼다.

- fetch.yml: 날마다 실행 수, event(schedule = 예약 04:30·05:15 KST 분, workflow_dispatch = 루틴이 직접 실행), 실제 시작 시각, conclusion.
- pages.yml: 날마다 push(루틴 커밋)·schedule 실행의 conclusion.
- 실패가 있으면 `get_job_logs`(failed_only)로 실패한 단계와 오류 한 줄을 적는다.
- 도구가 없거나 막히면 이 절은 "확인 안 됨".

## 3. 빌드

```bash
python3 site/build.py
python3 -c "import json; [print('-', w) for w in json.load(open('site/out/data.json')).get('warnings', [])]"
```

마지막 줄의 `warnings n` 과 경고 문장을 그대로 적는다. 경고가 있으면 CLAUDE.md "사이트 빌드" 항목대로 어느 자료를 고쳐야 하는지 적는다 (고치지는 않는다).

## 4. 요약 (채팅)

1. 표 하나: `| 항목 | 결과 |` — 루틴 / 수집 / 배포 / 빌드 / 소스 / 장부 / 종가 / 브리프 내용. 결과 칸은 숫자와 날짜로 짧게. 확인 못 한 칸은 "확인 안 됨"과 이유.
2. 이상과 이어서 볼 것: 문제마다 한 줄(무엇이 / 어디서 / 고칠 곳). 없으면 "이상 없음".
3. 현재 상태에 넣을 한 줄: CLAUDE.md "현재 상태"의 점검 항목 형식 그대로 한 줄을 코드 블록으로 낸다. 예:
   `- 11/10~11/11 점검: 루틴·수집·배포 모두 성공, 빌드 경고 0. 하루 시그널 2·2건(301~304), ± 없음. 확신 0.8 이 처음 나왔다(위 확신 항목)`
   그리고 현재 상태의 기존 항목 중 기간 끝 날짜나 건수를 늘려야 할 것(예: "9/30~11/11 Actions 수집·배포 모두 성공")을 짧게 나열한다. 고치지는 않는다. "기록하려면 /save" 라고 한 줄 덧붙인다.

규칙: 채팅에 새 사실을 만들지 않는다. 숫자는 check.py·build.py·Actions 출력에서만. 장부를 쓰거나 고치지 않는다. "사라/팔아라" 류 표현 금지(CLAUDE.md 규칙 6).
