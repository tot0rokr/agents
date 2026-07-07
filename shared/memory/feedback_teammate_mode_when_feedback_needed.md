---
name: feedback_teammate_mode_when_feedback_needed
description: "when a task needs feedback/back-and-forth during execution, prefer teammate mode (conversational subagent via SendMessage) over a fire-and-forget background subagent"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 6a95d291-83f4-47b5-87da-7fdc56b9c01b
---

작업 진행 중 피드백·상호작용이 필요한 경우에는, 결과만 한 번 받고 끝나는 백그라운드(일회성) 서브에이전트보다 teammate mode를 사용한다. (teammate = 이름·모델·색을 가진 지속적 대화형 서브에이전트, SendMessage로 소통. [[feedback_parallelize_independent_work]]의 병렬화 방침과 연결)

**Why:** 일회성 백그라운드 서브에이전트는 최종 결과를 한 번만 반환하고 실행 중에 방향을 잡아줄 수 없다. teammate mode는 SendMessage로 실행 중에도 대화하며 피드백을 주고받고, idle 상태로 대기하며 다음 지시를 받을 수 있어 피드백 루프에 적합하다.

**How to apply:**
- 판단 기준: "한 번 시키고 결과만 받으면 끝인가?" → 백그라운드/일회성 서브에이전트. "가면서 방향을 잡아주거나 중간 확인이 필요한가?" → teammate mode.
- 잘 정의됐고 결과만 받으면 되는 독립 작업(검색, 조사, 기계적 변환 등)은 기존대로 백그라운드/일회성으로 처리한다.
- 중간 피드백·명확화·수정 지시·리뷰 후 수정 루프가 필요한 작업은 teammate로 스폰하고 SendMessage로 소통한다.
