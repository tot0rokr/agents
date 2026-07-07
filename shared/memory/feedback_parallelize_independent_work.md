---
name: feedback_parallelize_independent_work
description: "parallelize any work that has no sequential dependency — batch independent tool calls, use background execution, and isolate concurrent code edits in temp worktrees then merge"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: b0bcb094-de07-4ce3-b28a-b6a04c1166db
---

순차적으로 수행할 필요가 없는 작업은 반드시 병렬/백그라운드로 처리한다. 검색·파일읽기·코드작성·문서작성처럼 카테고리가 다른 작업은 당연히 병렬로, 그리고 코드작성이라도 동시에 진행 가능한 것은 각각 임시 worktree에서 백그라운드로 작업한 뒤, 백그라운드가 모두 종료되면 병합한다. (worktree 규칙은 [[feedback_always_use_worktree]] 참고)

**Why:** 독립적인 작업을 직렬로 돌리면 대기 시간만 낭비된다. 병렬화하면 전체 wall-clock이 가장 느린 단일 작업 수준으로 줄어든다.

**How to apply:**
- 의존성 없는 tool 호출(여러 파일 Read, grep, 독립 검색 등)은 한 응답에 여러 tool_use로 묶어 동시에 실행한다.
- 오래 걸리는 명령(빌드/테스트/dev 서버/워처)은 `run_in_background`로 돌린다. harness가 완료 시 자동으로 다시 호출하므로 폴링(짧은 주기로 상태 확인)하지 않는다 — 폴링은 토큰·캐시 낭비.
- 독립 workstream(리서치/구현/리뷰)은 subagent를 병렬로 fan-out한다. 단 실행 중 피드백·상호작용이 필요한 작업은 일회성 백그라운드가 아니라 teammate mode로 돌린다 — [[feedback_teammate_mode_when_feedback_needed]].
- 동시 코드작성은 **파일/모듈이 겹치지 않을 때만** 별도 worktree에서 병렬로 하고, 겹치면 직렬로 처리한다. 병합 순서를 정해두고 충돌은 병합 시점에 해결한다.
- worktree 병렬의 손익분기점: **3개 파일 이상이거나 독립 모듈** 규모일 때만 worktree로 격리한다. 한두 파일 소량 수정은 셋업·병합 오버헤드가 더 커서 그냥 순차로 처리.
- 부분 실패 정책: 서로 독립적인 백그라운드 작업 중 일부가 실패하면 **완료분만 병합하고, 실패분은 사용자에게 보고 후 재시도**한다 (전체를 중단하지 않는다). 단 작업들이 서로 의존적이면 실패 시 관련 작업 전체를 재검토한다.
- 결과 요약: 병렬/서브에이전트 작업 결과는 사용자에게 직접 안 보이므로, 병합·완료 후 "무엇을 어디에 했는지"를 항상 요약해 전달한다.
- 반대로 의존성이 있는 작업(예: Read→Edit, build→test)은 순서를 반드시 유지한다. 무조건 병렬화가 아니라 "독립일 때만" 병렬화.
- 대량 출력은 로그 파일로 리다이렉트하고 tail만 읽는다(프로젝트 CLAUDE.md 규칙과 동일).
- 수십 개 에이전트를 fan-out하는 Workflow 멀티에이전트 오케스트레이션은 사용자가 세션에서 명시적으로 opt-in할 때만 사용한다 (기본 아님).
