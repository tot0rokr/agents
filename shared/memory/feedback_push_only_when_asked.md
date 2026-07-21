---
name: feedback_push_only_when_asked
description: "git push는 매번 명시적 지시가 있을 때만; 한 번 push했다고 이후 자동 push 금지; 브랜치 최초 push 시 remote가 여러 개면 어디로 push할지 물어본다"
metadata:
  node_type: memory
  type: feedback
  originSessionId: cbc73298-d504-4f6c-8ef1-717cbe33233e
---

git push는 항상 사용자가 명시적으로 지시했을 때만 한다. 커밋은 이 규칙과 별개다 — 커밋을 하라고 했거나 커밋하는 게 자연스러운 흐름이어도 push는 별도 지시가 필요하다. 그리고 한 번 "push해"라고 했다고 해서 그 이후 커밋들까지 계속 자동으로 push하면 안 된다. push는 매 건마다 새로 지시받아야 한다. 해당 브랜치를 처음 push하는 경우 remote가 여러 개면(예: origin + upstream/fork) 어느 remote로 push할지 먼저 물어보고, 답을 받은 뒤에 push한다.

**Why:** push는 되돌리기 어려운 outward 동작이고, 잘못된 remote(특히 public)로 나가면 히스토리에 남는다. 사용자는 언제·어디로 나가는지를 매번 직접 통제하고 싶어 한다. "한 번 허락 = 계속 허락"으로 확대 해석하는 것이 대표적인 실수다.

**How to apply:** 커밋 후 자동으로 push하지 않는다. 사용자가 그 시점에 명시적으로 push를 지시할 때만 실행한다. 브랜치의 최초 push라면 `git remote -v`로 remote 목록을 확인하고, 2개 이상이면 [[user_git_identity]]의 도메인 규칙도 함께 고려해 "어느 remote로 push할까요?"라고 물어본 뒤 진행한다. 이전 턴에서 push를 한 적이 있어도, 새 커밋을 push하려면 다시 지시를 받는다.
