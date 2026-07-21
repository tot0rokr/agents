---
name: feedback_rehydrate_context_after_compact
description: "after any compaction, immediately re-read the prior conversation to rebuild working context to ~30% before doing anything else; enforced by a global SessionStart(compact) hook"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 7c6028f1-c46a-4895-b30b-6d246404cb0c
---

compact(대화 압축)가 일어난 직후에는, 다른 행동을 하기 전에 반드시 이전 대화를 꼼꼼히 다시 읽어 작업 컨텍스트를 재구성한다 — 컨텍스트 창의 약 30%를 가장 관련성 높은 이전 내용(사용자 선호·피드백, 내린 결정, 생성·수정한 파일과 그 위치, 미완결 스레드)으로 채운 뒤 진행한다. 최근 턴을 우선하고 오버플로 전에 멈춘다.

**Why:** compact 후에는 요약만 남고 세부 맥락이 사라진다. 요약만 믿고 진행하면 사용자 선호나 진행 중이던 작업 세부를 놓친다. 사용자가 "반드시, 전역으로 발동"을 명시적으로 요구했다.

**How to apply:**
- 이 동작은 전역 SessionStart(compact) hook으로 강제된다: `~/.claude/hooks/post-compact-rehydrate.sh`가 매 compact 직후 이 지시를 컨텍스트에 주입한다 (`~/.claude/settings.json`의 `hooks.SessionStart` 중 `matcher: "compact"` 항목). 메모리만으로는 "반드시 발동"이 보장되지 않으므로 hook이 실제 강제 장치이고, 이 메모리는 그 문서화 + 소프트 보강이다. (PostCompact 이벤트는 hook이 돌긴 해도 `additionalContext` 주입을 무시하므로 못 쓴다 — SessionStart/compact만 주입 가능.)
- 주입된 지시를 받으면: hook이 알려주는 세션 transcript(.jsonl) 경로의 관련 tail을 읽어 맥락을 복원한다. 전체를 무리하게 읽어 오버플로하지 않는다.
- 현재 `autoCompactEnabled: true`라 자동 compact도 켜져 있어 자동/수동(`/compact`) 모두에서 발동한다.
- 이 hook 파일이나 settings.json의 SessionStart(compact) 항목을 지우면 동작이 사라진다 — 건드릴 때 주의.
