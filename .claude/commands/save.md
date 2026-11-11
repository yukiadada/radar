---
description: 이 세션에서 한 일과 점검 결과를 CLAUDE.md "현재 상태"에 반영하고 세션 로그를 비공개 radar-raw 의 logs/ 에 커밋하고, 커밋·푸시한 뒤 main 이 아닌 브랜치면 main 으로 PR 을 열어 병합한다. Ken 이 직접 호출한다. 모델이 스스로 호출하지 않는다
argument-hint: [한 줄 메모]
disable-model-invocation: true
---

# /save

레포 루트에서 실행한다. 고치는 곳은 CLAUDE.md 의 `## 현재 상태` 절과 세션 로그(radar-raw 의 `logs/`) 뿐이다. CLAUDE.md 의 다른 절(목적·절대 규칙·파일 구조·워크플로·스키마·템플릿·작성 스타일)은 여기서 고치지 않는다. 그런 변경은 이 세션에서 Ken 이 승인해 이미 고친 것만 커밋에 넣는다. 장부(`ledger/signals.jsonl`)는 읽기만 한다.

메모: `$ARGUMENTS` 가 있으면 그 한 줄을 로그와 현재 상태에 반영할 내용의 힌트로 쓴다 (예: `11/10~11/11 점검`).

## 1. 최신으로

1. `git status --short`, `git branch --show-current`, `TZ=Asia/Seoul date '+%F %H:%M'`.
2. 루틴이 매일 main 에 푸시하므로 먼저 받는다.
   - main 이면 `git pull --rebase --autostash origin main`.
   - 다른 브랜치면 원격에 그 브랜치가 있을 때 `git pull --rebase --autostash origin <브랜치>`. 그리고 `git fetch origin main` 후 `git rev-list --count HEAD..origin/main` 이 0 이 아니면 `git rebase --autostash origin/main` 으로 main 위에 올린다 (에이전트가 만든 `claude/` 브랜치일 때만. 아니면 멈추고 Ken 에게 묻는다. 원격 브랜치에 이미 있던 커밋이 바뀌었으면 5단계 푸시는 `--force-with-lease`). 현재 상태의 날짜·커밋은 main 기준으로 쓴다: `git log origin/main`.
3. 충돌이 나면 멈추고 Ken 에게 알린다.

## 2. 재료 모으기

기억으로 사실을 만들지 않는다. 숫자·날짜·커밋 해시·줄 번호는 명령 출력에서만 가져온다.

- 이 세션의 대화: 한 일, 결정, Ken 이 승인한 것, 미룬 것.
- 이 세션의 커밋: `git log --format='%h %ad %s' --date=format-local:'%m/%d %H:%M'` (TZ=Asia/Seoul) 중 이 세션에서 만든 것.
- 아직 커밋 안 된 변경: `git diff --stat`, `git status --short`.
- /check 를 이 세션에서 돌렸으면 그 요약의 "현재 상태에 넣을 한 줄"과 늘려야 할 기존 항목.
- 지금 CLAUDE.md 의 `## 현재 상태` 절 전체를 읽는다.

## 3. 세션 로그 (비공개 radar-raw 의 logs/)

로그는 비공개 저장소 radar-raw 의 `logs/` 에 커밋해 남긴다 (radar 는 공개라 여기에 두지 않는다). radar 의 `logs` 는 `../radar-raw/logs` 심볼릭 링크이고 `.gitignore` 에 있다. 커밋은 5c 단계에서 한다.

1. 링크 준비. `logs` 가 `../radar-raw/logs` 링크가 아니면:
   - `../radar-raw` 가 없으면(클라우드) `add_repo`(owner yukiadada, repo radar-raw, access push)로 붙이고 그 결과가 알려주는 clone 명령으로 `../radar-raw` 에 받는다. 붙이지 못하면 로그는 scratchpad 에 쓰고 채팅 요약에 "로그 보관 못 함"과 그 경로를 적는다.
   - `git -C ../radar-raw pull --rebase -q origin main` (radar-raw 는 fetch.yml 이 매일 커밋한다).
   - `logs` 가 실제 폴더면(예전 로컬 로그) `mkdir -p ../radar-raw/logs && mv -n logs/* ../radar-raw/logs/` 로 옮기고(같은 이름은 덮지 않는다) 비었을 때만 `rmdir logs`. 파일이 남으면 멈추고 Ken 에게 알린다.
   - `mkdir -p ../radar-raw/logs && ln -s ../radar-raw/logs logs`.
2. `logs/<YYYY-MM-DD>-<HHMM>.md` (KST)를 쓴다.

```markdown
# 세션 로그 YYYY-MM-DD HH:MM (KST)

- 브랜치: <브랜치> (main 보다 n 커밋 뒤면 적는다)
- 이 세션 커밋: <해시> <제목> (한 줄씩)

## 한 일
- 무엇을 왜. 바꾼 파일.

## 확인한 것
- 명령과 결과 숫자 (빌드 경고 n, 장부 n줄, 점검 결과 등)

## 남은 일
- Ken 판단·승인이 필요한 것, 다음에 볼 날짜
```

## 4. CLAUDE.md "현재 상태" 갱신

절 머리는 이 형식을 지킨다.

```markdown
## 현재 상태

> /save 자동 업데이트 — YYYY-MM-DD HH:MM (KST)

**브랜치:** <현재 브랜치> (main 이 아닌 브랜치면 `main (<브랜치> 에서 PR 병합)`)
**마지막 커밋:** <이 save 커밋의 한 줄 요약> (이 커밋)

**미완료 항목:**
- ...
```

항목 규칙:
- 있는 항목은 그 자리에서 고친다. 기간 끝 날짜·건수·상태를 늘린다 (예: "9/30~11/09 Actions 수집·배포 모두 성공" → "9/30~11/11"). 같은 주제로 새 항목을 따로 만들지 않는다.
- 새 주제만 새 항목. 점검 결과는 `- M/D~M/D 점검: ...` 한 항목이고, 마지막 점검 항목 바로 뒤에 둔다 (`fetch/check.py` 가 이 형식에서 다음 점검 기간을 읽는다).
- 끝난 일은 지운다 (기록은 git log 에 남는다). 다시 볼 기준(예: "20% 넘으면 제안", "11월 /review 에서 다시 본다")이 남은 항목은 남긴다.
- 항목마다 날짜(KST)·숫자·커밋 해시·장부 줄 번호로 쓴다. 형용사를 줄인다. CLAUDE.md "작성 스타일"을 따른다. 모르는 것은 "확인 안 됨".
- Ken 이 정할 일은 "Ken 판단", "Ken 승인 후"로 표시한다. 에이전트가 정한 것처럼 쓰지 않는다.
- 비밀값(토큰·키)과 개인 정보는 쓰지 않는다.

## 5. 커밋·푸시

1. `git add CLAUDE.md` 와 이 세션에서 고친 다른 파일. 이 세션이 고치지 않은 변경이 보이면 넣지 않고 채팅에 알린다. `logs/`·`raw`·`prices`·`site/out/` 은 `.gitignore` 라 커밋되지 않는다.
2. 커밋 메시지: 첫 줄 `현재 상태: <요약>` (이 세션에서 코드·규칙도 바꿨으면 그 내용을 첫 줄 앞에 두고 `+ 현재 상태 기록`). 본문은 바뀐 항목을 2~3문장으로.
3. `git push -u origin <현재 브랜치>`. 네트워크 오류면 2·4·8·16초 간격으로 최대 4번 다시 시도한다. non-fast-forward 로 거부되면 `git pull --rebase --autostash` 후 한 번 더.
4. 커밋 뒤 4단계 머리의 "마지막 커밋"이 이 커밋의 요약과 맞는지 본다 (해시는 쓰지 않는다. "(이 커밋)"이 가리킨다).

## 5b. PR 과 병합 (main 이 아닌 브랜치)

현재 브랜치가 main 이면 건너뛴다 (5단계에서 main 에 바로 푸시했다). 아니면 main 으로 PR 을 열고 **병합까지 한다** (Ken 이 2026-11-11 에 /save 의 PR·병합을 맡겼다).

1. `git fetch origin main` 후 `git log origin/main..HEAD --format='%h %s'` 가 비어 있으면(브랜치가 main 과 같음) PR 도 병합도 하지 않는다.
2. 그 브랜치의 열린 PR 을 찾는다: GitHub MCP `list_pull_requests`(owner yukiadada, repo radar, head `yukiadada:<브랜치>`, state open), 도구가 없으면 `gh pr view <브랜치> --json url,state`. 열린 PR 이 있으면 새로 열지 않는다 (방금 푸시한 커밋이 그 PR 에 붙는다). 이미 병합된 PR 은 다시 쓰지 않고 새 PR 을 연다.
3. 없으면 연다: GitHub MCP `create_pull_request`(owner yukiadada, repo radar, head <브랜치>, base main). 도구가 없으면 `gh pr create --base main --head <브랜치> --title ... --body-file <임시 파일>`. 둘 다 안 되면 `https://github.com/yukiadada/radar/compare/main...<브랜치>?expand=1` 을 채팅에 적고 병합은 4의 푸시로만 한다.
   - 제목: 1의 커밋이 하나면 그 첫 줄, 여럿이면 바뀐 것을 한 줄로.
   - 본문(한국어, 짧게). 레포에 PR 템플릿(`.github/pull_request_template.md` 등)이 생기면 그 절 제목을 따른다.

     ```markdown
     ## 바뀐 것
     - <1의 커밋 한 줄씩>

     ## 확인
     - site/build.py 경고 n (이 세션에서 돌린 것). /check 를 돌렸으면 그 결과 한 줄

     ## 현재 상태
     - 고침 / 새로 / 지움 항목
     ```
4. 병합. 아래가 모두 맞을 때만 한다. 하나라도 아니면 병합하지 않고 PR 을 열어 둔 채 이유를 채팅에 적는다.
   - 이 저장에서 `python3 site/build.py` 가 실패하지 않았다 (경고는 막지 않는다. 채팅에 적는다).
   - PR 에 변경 요청(changes requested) 리뷰가 없고, 체크 실행이 있으면 실패한 것이 없다 (GitHub MCP `pull_request_read` 의 get_reviews·get_check_runs, 또는 `gh pr view --json reviewDecision,statusCheckRollup`).
   - 1의 커밋이 모두 이 세션(또는 이 브랜치의 앞선 저장)이 만든 것이다.

   방법은 fast-forward 다 (main 기록은 병합 커밋 없이 한 줄이고, 커밋 해시가 그대로 남는다).
   1) `git fetch origin main`. `git merge-base --is-ancestor origin/main HEAD` 가 실패하면(그새 루틴 등이 main 에 푸시했다) `git rebase origin/main` 으로 main 위에 올리고 `python3 site/build.py` 를 다시 돌린 뒤 `git push --force-with-lease origin <브랜치>`. 에이전트가 만든 `claude/` 브랜치가 아니면 rebase 하지 않고 멈춘다. 충돌이 나면 `git rebase --abort` 하고 멈춘다.
   2) `git push origin HEAD:main`. non-fast-forward 로 거부되면(그 사이 main 이 또 움직였다) 1) 부터 한 번 더. 그 밖의 거부(보호 규칙·권한)면 멈춘다.
   3) PR 이 병합됨으로 바뀌었는지 본다 (MCP `pull_request_read` get 의 merged, 또는 `gh pr view --json state`). fast-forward 푸시면 GitHub 가 PR 을 병합됨으로 표시한다.
   4) main 푸시는 pages.yml 배포를 띄운다. 기다리지 않는다. 결과는 다음 /check 가 본다.

## 5c. 세션 로그 커밋 (radar-raw)

1. 로그의 "이 세션 커밋" 줄에 이 save 커밋 해시와 PR 링크·병합 결과를 채운다.
2. `git -C ../radar-raw add logs/` 로 이번 로그와 3단계에서 옮긴 옛 로그만 올린다. `raw/`·`prices/` 는 건드리지 않는다.
3. 커밋 메시지 `logs: <YYYY-MM-DD HH:MM> 세션 로그 (<한 줄 요약>)`. `git -C ../radar-raw pull --rebase -q origin main` 후 `git -C ../radar-raw push origin HEAD:main`. 네트워크 오류는 5단계처럼 다시 시도하고, 권한으로 거부되면 로컬 커밋으로 두고 채팅 요약에 적는다.

## 6. 채팅 요약

- 커밋 해시와 푸시한 브랜치
- PR 링크와 병합 결과 (새로 열었는지 / 이미 열려 있던 것인지 / main 이라 건너뛰었는지, 병합됨 / 병합 안 함과 그 이유)
- 현재 상태에서 바뀐 항목 (고침 / 새로 / 지움)
- 로그 파일 경로와 radar-raw 커밋 해시 (보관 못 했으면 그 이유)
- main 위로 rebase 했으면 그 사실
