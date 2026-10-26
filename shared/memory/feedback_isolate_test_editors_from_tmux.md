---
name: feedback_isolate_test_editors_from_tmux
description: "test vim/nvim runs must set TMUX_TMPDIR to an empty dir as well as unset TMUX, or tmuxline rewrites the live tmux theme"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 45ae74cb-bebd-4001-a472-62992dab5c4f
  modified: 2026-10-16T10:41:49.415Z
---

When running a test vim/nvim (headless or not) on this machine, use `env -u TMUX TMUX_TMPDIR=<short empty dir>`, not just `env -u TMUX`. tmuxline.vim calls `tmux source` without checking `$TMUX`, so with TMUX unset it still reaches the live server through the default socket. Keep the dir path short: tmux sockets fail with "Filename too long" under the scratchpad path.

**Why:** on 2026-10-16 a test nvim from another session ran airline's tmuxline extension and replaced the user's live tmux theme. The dotfiles fix (common.vim sets `g:airline#extensions#tmuxline#enabled = 0` outside the PluginInstalled check) guards the normal case, but tests can still load other configs.

**How to apply:** any nvim/vim launch for testing, especially with a different HOME or XDG config. Let private tmux test servers exit on their own (a `sleep` pane), and don't use kill commands. Related: [[feedback_verify_in_user_env]]
