---
name: critical-file-safety
description: Use this skill whenever about to modify a file that is hard to recover if corrupted, or whenever about to delete any file. Hard-to-recover files include system configuration (anything under /etc, /boot, /usr, systemd unit files), bootloader/kernel config (grub, kernel .config, device tree sources, U-Boot env), network and firewall config (netplan, NetworkManager, nftables, iptables), shell and editor dotfiles, container/VM runtime config, and any file outside a git-managed project's own source tree. Triggers also include any rm, rm -rf, mv to /tmp or trash, truncate, or shred. Enforces backup-before-modify with a structured filename, and treats deletion as opt-in only.
---

# Critical File Safety

## Back up before modifying irrecoverable files

Source files inside a git-managed project can always be recovered from git. Other files cannot. Before modifying anything in the second category - system config, dotfiles, bootloader/kernel config, device trees, network config, or anything where a mistake means "reinstall and start over" - copy the file to a backup first.

### Backup filename format

```
<original-path>.bak.<purpose>-<version>.<YYYYMMDD-HHMMSS>
```

Components:
- `<purpose>` - why this backup exists (e.g. `prev-test`, `before-netplan-rewrite`, `pre-grub-edit`)
- `<version>` - a short tag distinguishing this backup from prior ones (e.g. `v1`, `prev`, `working`)
- `<YYYYMMDD-HHMMSS>` - timestamp at the moment of backup, generated with `date +%Y%m%d-%H%M%S`

### Example

```bash
sudo cp /etc/netplan/00-installer-config.yaml \
        /etc/netplan/00-installer-config.yaml.bak.prev-test-v1.$(date +%Y%m%d-%H%M%S) \
&& echo "[OK] backup created" \
&& ls -lh /etc/netplan/*.bak.*
```

Verify the backup exists and is non-empty before modifying the original. The backup must be in place *before* the first edit, not after.

## Deletion is opt-in only

Do not delete files unless the user has explicitly told you to delete them in the current session. This covers `rm`, `rm -rf`, `unlink`, `shred`, moving files into a trash or temp directory with the intent to discard, truncating with `> file` or `truncate -s 0`, and `find ... -delete`.

If deletion appears necessary to complete a task, stop and ask the user. In the question:
1. Name every file or directory that would be removed.
2. State why deletion is needed.
3. Wait for explicit approval before running the command.

The same rule applies to operations that overwrite without backup - if a destination file already exists and a copy/move would clobber it, treat that as a deletion of the existing file and ask first.
