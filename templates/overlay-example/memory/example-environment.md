---
name: example-environment
description: Placeholder memory showing what an overlay-provided memory file looks like
metadata:
  type: project
---

Replace this file with the environment facts that must not live in the public base repo — internal hostnames, ticket prefixes, which remote maps to which account, where a build lands.

Overlay memory files are symlinked into `shared/memory/`, so agents read them exactly like base memory. Add the matching pointer line to `shared/memory/MEMORY.md` from the overlay too, or keep the pointer in the base repo generic enough to be public.
