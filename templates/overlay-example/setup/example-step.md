Replace this prompt with the one step you want an agent to carry out on a fresh machine.

Write it the way you would brief a careful colleague who has never seen this environment: what the end state is, where the files live, how to verify it worked. Reference overlay values as `${VAR}` — they are substituted from `vars.json` before the agent reads this.

The step that runs this prompt is satisfied when its `check` command exits 0, so say plainly what that end state is. For this placeholder it is the file `$HOME/.config/example-overlay/ready`.

Never ask the agent to invent a credential. If a secret is needed, have it stop and report BLOCKED, and put the human-facing instructions in the step's `manual` field.
