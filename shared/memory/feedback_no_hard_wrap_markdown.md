---
name: no-hard-wrap-markdown
description: Markdown 문서에서 한 줄(한 단락·한 불릿)을 여러 줄로 강제 줄바꿈하지 말 것. 논리적 한 줄 = 물리적 한 줄.
metadata:
  type: feedback
---

Markdown 문서를 쓸 때 단락이나 불릿 항목 안에서 임의로 줄바꿈을 넣지 말 것. 80자/100자 wrap 같은 코드 컨벤션을 산문 문서에 적용하지 않는다. 한 단락은 한 줄, 한 불릿 항목은 한 줄로 작성한다.

**Why:** 사용자가 직접 지적 — 강제 wrap된 markdown은 편집기에서 가독성이 떨어지고, diff·grep·검색에서도 불리하다. 화면에서는 어차피 자동 wrap된다.

**How to apply:** Write/Edit 도구로 markdown 파일을 작성할 때, 한 불릿/단락의 내용이 길어도 줄바꿈 없이 한 줄로 유지. 줄바꿈이 의미가 있을 때만 사용 (목록 항목 구분, 코드 블록 안, 인용문 분리 등). 관련: [[doc-writing-style]] 류 doc 규칙 따르는 모든 작성 작업.
