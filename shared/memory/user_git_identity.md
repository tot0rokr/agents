---
name: user-git-identity
description: User has a personal git author identity (TOT0Ro <tot0roprog@gmail.com>) distinct from their work email
metadata:
  type: user
---

User uses two git identities:

- Personal: `TOT0Ro <tot0roprog@gmail.com>` — for personal / open-source
  repos (e.g. `github.com/tot0rokr/*`).
- Work: `junho.lee@mangoboost.io` — for MangoBoost projects.

When initializing git config in a new repo where the identity is unset, ask
which identity to use rather than defaulting. Set with repo-local `git config`
(not `--global`) per the user's preference.
