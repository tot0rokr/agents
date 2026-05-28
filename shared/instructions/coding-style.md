# Coding Style

General principles that apply across languages and projects. Project-level `AGENTS.md` files may override these.

## Language

- Write code, identifiers, and code comments in English. See [language.md](./language.md) for the full language matrix.

## Readability and simplicity

- Favor concise, readable code. Clarity beats cleverness.
- Do not overengineer. Build for what the task requires, not for hypothetical futures.
- When extensibility looks important, surface it as a proposal instead of silently building it.
  - Implement what was asked, cleanly.
  - In the response, note the extensibility angle: "If you want this to extend to Y, here are the trade-offs / two ways to do it." Let the user decide whether to invest.
  - Applies to plugin hooks, config options, generic interfaces, "while we're here" refactors.

## Comments

- Default to writing no comments. Add one only when *why* is non-obvious.
- Do not explain *what* the code does — well-named identifiers do that.
- Do not reference the current task, PR, or issue in code comments. Those belong in commit messages and rot in code.

## Scope

- Do not add features, refactors, or abstractions beyond what the task requires.
- Do not add error handling, fallbacks, or validation for scenarios that cannot happen. Trust internal code; validate only at system boundaries.
- Three similar lines is fine. Do not preemptively abstract.

## Naming and identifiers

- Follow the host language and framework conventions first.
  - Python/Rust: `snake_case` for functions/vars, `PascalCase` for types.
  - JS/TS/Java: `camelCase` for functions/vars, `PascalCase` for types.
  - Go: `MixedCaps`, exported = capitalized.
- Then match the surrounding codebase. Consistency with neighboring code beats personal preference.
  - If the module uses `db_conn` everywhere, the new function uses `db_conn`, not `database_connection`.
  - If existing code abbreviates `ctx` for context, do the same — do not split conventions within a file.
- Abbreviations: only ones already established in the codebase or the language community (`id`, `url`, `ctx`, `db`, `io`, `req`, `res`). Do not invent new ones.
- Names describe purpose, not implementation. `user_count` over `n`, `pending_jobs` over `arr2`.
- No magic numbers / unnamed literals when the value carries meaning beyond its literal form (timeouts, retry limits, status codes, buffer sizes). Extract to a named constant. Pure literals like `0`/`1` for indexing stay inline.

## Functions and modules

- Length is a smell, not a rule. Judge by complexity.
  - How many concepts the function juggles.
  - How deep the control flow goes.
  - How much state it touches.
- A function that does one thing in 80 lines is fine. A function that does three things in 20 lines is not.
- Use early returns to flatten control flow. Avoid nesting beyond ~3 levels.
- Split when a function mixes distinct concerns (parse + validate + dispatch). Keep it whole when it is one linear pipeline.
- Module boundaries: prefer fewer, well-defined public symbols. Keep internal helpers private (`_helper`, file-local, package-private).
- Avoid circular imports. If two modules need each other, either extract a third module or the dependency direction is wrong.

## Error handling

- Fail-fast by default. Unexpected states crash with a clear message, not a swallowed exception.
- Do not add `try/except` around code you do not know how to recover from. Let it propagate.
- Catch narrowly — by specific exception type — when you do catch.
- No fallback defaults for "just in case." If a config value is missing, error out; do not silently substitute `""` or `0`.
- Validate at system boundaries (user input, external API responses, file I/O, IPC). Internal callers are trusted.
- Retries only when the operation is idempotent and the failure mode is genuinely transient. Otherwise, fail and let the caller decide.

## Types

- In typed languages, prefer specific types over escape hatches (`any` in TS, `Any` in Python, `interface{}` in Go).
- Use `unknown` / typed casts at boundaries where data shape is not yet known; refine before passing inward.
- Generics / type parameters: introduce only when there are two real call sites with the same structure. Do not write generic helpers for hypothetical reuse.

## Tests

- Unit tests use mocks for external dependencies (DB, network, filesystem). Goal: fast and deterministic.
- Integration tests use real dependencies (real DB, real HTTP, real filesystem). Goal: catch contract drift between layers.
- Test names describe the behavior, not the function. `rejects_invalid_email` over `test_validate_1`.
- Cover the golden path first, then notable edge cases. Do not write a test per branch just for coverage.
- Do not mock what you own. Mocking your own modules in unit tests usually signals the seam is in the wrong place.

## Dependencies

- Adding a dependency is a permanent cost. Justify it: is the standard library or an existing dependency enough?
- Prefer well-maintained, widely-used libraries over niche ones for the same job.
- Lock files (`package-lock.json`, `Cargo.lock`, `uv.lock`, `poetry.lock`) are committed. Do not regenerate them without intent.
- When bumping a dependency, note the reason in the commit message (security, feature, bugfix).
- Import order follows the language's standard tool (`isort`, `gofmt`, `rustfmt`, ESLint). Do not hand-order against the tool.

## Security

- Never introduce command injection, XSS, SQL injection, or other OWASP-style vulnerabilities. If you notice you wrote insecure code, fix it immediately.
- Never commit secrets. If you see `.env`, credentials, tokens, etc. in a staging area, stop and warn the user.
