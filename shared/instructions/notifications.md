# Notifications

## Completion notifications for multi-task work

- When a task spans **multiple planned steps** (e.g. work laid out via a plan, a multi-item checklist, or a long-running sequence of subtasks), send an explicit webhook notification once the whole plan is finished.
- This applies to multi-step plans only. Do **not** notify for single, one-shot tasks or quick questions.
- Use whatever notification skill is available in the current environment (e.g. `bell`, `noti`). If no relevant notification skill is available, skip the notification silently — do not error or block on it.
- The notification should summarize what was completed, not just say "done".
