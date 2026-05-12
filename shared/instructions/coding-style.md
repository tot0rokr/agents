# Coding Style

General principles that apply across languages and projects. Project-level
`AGENTS.md` files may override these.

## Comments

- Default to writing no comments. Add one only when *why* is non-obvious.
- Do not explain *what* the code does — well-named identifiers do that.
- Do not reference the current task, PR, or issue in code comments. Those
  belong in commit messages and rot in code.

## Scope

- Don't add features, refactors, or abstractions beyond what the task requires.
- Don't add error handling, fallbacks, or validation for scenarios that can't
  happen. Trust internal code; validate only at system boundaries.
- Three similar lines is fine. Don't preemptively abstract.

## Security

- Never introduce command injection, XSS, SQL injection, or other OWASP-style
  vulnerabilities. If you notice you wrote insecure code, fix it immediately.
- Never commit secrets. If you see `.env`, credentials, tokens, etc. in a
  staging area, stop and warn the user.
