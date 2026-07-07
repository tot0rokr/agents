---
name: feedback_always_use_worktree
description: "on any git project, always develop inside a git worktree (parent dir, projectname-branchname); merge only when work is complete"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: b0bcb094-de07-4ce3-b28a-b6a04c1166db
---

git 프로젝트 위에서 개발할 때는 항상 git worktree를 만들어서 그 안에서 작업한다. 작업이 완전히 완료되면 그때 병합한다. worktree 위치/이름 규칙: 프로젝트 상위 디렉토리에 `프로젝트명-branch명` 형식 (예: `myproj`의 `feat-x` 브랜치 → `../myproj-feat-x`).

**Why:** 한 repo에서 여러 작업을 동시에 진행하면 충돌 등 문제가 생길 수 있다. worktree로 작업을 격리하면 이를 방지할 수 있다.

**How to apply:** 코드 변경을 시작하기 전에 대상 디렉토리가 git repo인지 확인하고, 맞으면 새 worktree를 상위 디렉토리에 `프로젝트명-branch명`으로 생성한 뒤 그 안에서 작업한다. main/기본 브랜치에서 바로 작업하지 않는다. 작업 완료 후 병합한다. BSP/Jira 티켓 작업이면 기존 [[project_grep_find_rg_fd_wrappers]]와 무관하게 claude-bsp `worktree` 스킬을 우선 사용한다.
