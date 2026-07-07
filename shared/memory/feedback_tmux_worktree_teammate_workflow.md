---
name: feedback_tmux_worktree_teammate_workflow
description: "default workflow when inside tmux — each teammate runs in its own git worktree + its own tmux window (watchable/attachable), merge and close when done"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 7c6028f1-c46a-4895-b30b-6d246404cb0c
---

tmux 안에서 작업할 때 teammate를 띄우는 기본 방식은 "각 teammate = 자기 git worktree + 자기 tmux 창"이다. 사용자가 각 teammate의 작업을 실시간으로 보고 개입할 수 있게 한다. (연결: [[feedback_always_use_worktree]] 워크트리 규칙, [[feedback_teammate_mode_when_feedback_needed]] 피드백 필요 시 teammate, [[feedback_parallelize_independent_work]] 병렬화)

**Why:** teammate를 격리된 worktree에서 돌리면 동시 작업 충돌이 없고, 각자 tmux 창(진짜 TTY)에 띄우면 사용자가 진행을 직접 보고 중간에 지시할 수 있다. (실측: 헤드리스 백그라운드에서 `claude --tmux`를 nested로 띄우면 hang됨 → 이미 tmux 안이면 `tmux new-window`로 직접 창을 만드는 게 정답.)

**How to apply:**
- 조건: (1) tmux 세션 안일 것, (2) 그 작업이 teammate로 돌릴 만한 것일 때 — 실행 중 피드백/상호작용이 필요하거나, 독립 동시 코드작업이 worktree 임계값(3개 파일↑/독립 모듈)을 넘을 때. 단순 일회성 조사/검색은 그냥 in-session 서브에이전트로.
- worktree: 사용자 규칙대로 `../프로젝트명-branch명`에 생성. (네이티브 `claude --worktree`는 `.claude/worktrees/`에 만드니, 규칙을 지키려면 직접 만든 뒤 그 경로를 넘긴다.)
- teammate 창 띄우기(실측 동작): `tmux new-window -d -n <이름> -c <worktree경로> "claude '<할 일>'; exec bash"`. 새 디렉토리면 첫 실행 시 trust 프롬프트가 뜬다.
- 엿보기/소통: `tmux capture-pane -t <세션>:<이름> -p`로 상태 확인, `tmux send-keys -t <세션>:<이름> '<입력>' Enter`로 지시. (harness 내부 Agent 서브에이전트면 SendMessage 사용.)
- 완료 시: worktree 병합 후 창 정리(`tmux kill-window` 또는 pane에서 `/exit`). 각 teammate는 독립 claude 세션이라 토큰을 쓰므로 끝나면 닫는다.
- 대안: 대화형 터미널이면 `claude '<할 일>' --worktree <이름> --tmux=classic`(iTerm2면 `--tmux`)로 네이티브 셋업 가능. 단 헤드리스 백그라운드에서는 hang되니 그땐 `tmux new-window` 방식.
