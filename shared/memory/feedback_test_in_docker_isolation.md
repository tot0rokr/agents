---
name: feedback_test_in_docker_isolation
description: Run tests that execute code or have side effects inside a disposable Docker container built for the test, never on the host; the user's HOME, live sessions, browsers, credentials and remotes stay out of reach
metadata:
  type: feedback
---

Run any test that executes the code under test, or exercises a tool with side effects, inside a throwaway Docker container set up for that test. Read-only checks (reading files, `--version`, listing state) may stay on the host.

Container rules:
- Image: reuse a fitting local image or a small official base. Test-only builds get their own tag (`<name>-test`); never retag or overwrite images the user runs.
- Mounts: the code under test read-only (or a copy in the scratchpad), plus one scratch output dir. Never mount the real HOME, `~/.claude`, `~/.ssh`, `~/.config`, credential files, `docker.sock`, or X11 sockets.
- Environment: a fresh HOME inside the container and only the variables the test needs. Don't pass DISPLAY, TMUX*, SSH_AUTH_SOCK, session variables (CLAUDE*, RH_*), or tokens.
- Network: `--network none` by default. Open it only when the test needs it, prefer a stub service inside the container over real hosts, and never push, publish or log in from a test. A test that needs its own Docker network takes its subnet from the machine's subnet rule when an overlay supplies one ([[feedback_docker_subnet_explicit]]); never let Docker pick from its default pool.
- Privileges: run as a non-root user (`--user $(id -u):$(id -g)` or the image's user). No `--privileged`; add a capability or seccomp exception only when the program under test requires it, and say which and why.
- Lifecycle: `--rm`, a recognizable name or label (`claude-test-<topic>`), and `--memory`/`--cpus` limits for heavy runs. Remove every container, volume and network you created when done. Never stop, exec into or modify containers you did not create.

If a test cannot run in a container (real hardware, the user's live session, a real login), stop and ask before running it on the host, and say exactly what it will touch.

In the report, state the image, mounts, network mode and results.

**Why:** Tests run on the host have reached the user's live state. For example, a test sync command overwrote config in the user's running desktop sessions, and keeping tests away from the real config needed fragile temp-HOME setups. The user asked for Docker isolation as the default (2026-11-02).

**How to apply:** Before running a test, write the `docker run` line first and check it against the rules above. Isolate first, then confirm in the real environment only read-only or with the user's go ([[feedback_verify_in_user_env]]). Editor tests also follow [[feedback_isolate_test_editors_from_tmux]].
