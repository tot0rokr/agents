"""update / audit_drift / commit — classification and the refusals that matter."""

from __future__ import annotations

import subprocess

from tests._helpers import (
    HarnessTestCase,
    install_doctor_stub,
    make_overlay,
    register_and_install,
    write_command,
)


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)


class AuditDriftTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        from integrated_harness_kit_mcp.tools import maintenance

        self.maintenance = maintenance
        # A directory git already tracks, so a new file inside it is reported
        # as that file rather than as an untracked directory.
        write_command(self.repo, "seed")
        make_overlay(
            self.repo,
            "work",
            priority=60,
            memories={"internal": "---\nname: internal\n---\n\nx\n"},
        )
        register_and_install(self.repo, "work", priority=60)
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@e", "add", "-A")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "base")

    def audit(self) -> dict:
        return self.maintenance.audit_drift(repo_path=str(self.repo))

    def test_a_clean_repo_has_no_committable_paths(self):
        result = self.audit()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["committable"], [])

    def test_base_source_edits_are_committable(self):
        (self.repo / "shared" / "commands" / "new.md").write_text("---\ndescription: d\n---\n")
        result = self.audit()
        self.assertIn("shared/commands/new.md", result["committable"])
        entry = next(e for e in result["entries"] if e["path"] == "shared/commands/new.md")
        self.assertEqual(entry["category"], "base_source")

    def test_artifacts_are_classified_and_not_committable(self):
        (self.repo / "claude" / "settings.json").write_text("{}\n")
        result = self.audit()
        paths = {e["path"]: e["category"] for e in result["entries"]}
        self.assertEqual(paths.get("claude/settings.json"), "artifact")
        self.assertNotIn("claude/settings.json", result["committable"])

    def test_a_dirty_overlay_is_reported_separately(self):
        (self.repo / "overlays" / "work" / "memory" / "scratch.md").write_text("x\n")
        result = self.audit()
        self.assertEqual(len(result["overlays"]), 1)
        self.assertEqual(result["overlays"][0]["alias"], "work")
        self.assertIn("overlay_commit", result["overlays"][0]["hint"])


class CommitTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        from integrated_harness_kit_mcp.tools import maintenance

        self.maintenance = maintenance
        make_overlay(
            self.repo,
            "work",
            priority=60,
            memories={"internal": "---\nname: internal\n---\n\nx\n"},
        )
        register_and_install(self.repo, "work", priority=60)
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@e", "add", "-A")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "base")
        git(self.repo, "config", "user.name", "t")
        git(self.repo, "config", "user.email", "t@e")

    def commit(self, paths, message="a change"):
        return self.maintenance.commit(paths, message, repo_path=str(self.repo))

    def test_a_base_source_file_is_committed(self):
        (self.repo / "shared" / "commands" / "new.md").write_text("---\ndescription: d\n---\n")
        result = self.commit(["shared/commands/new.md"])
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["staged"], ["shared/commands/new.md"])
        self.assertIn("a change", result["head"])

    def test_render_artifacts_are_refused(self):
        (self.repo / "claude" / "settings.json").write_text("{}\n")
        result = self.commit(["claude/settings.json"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["refused"][0]["reason"], "artifact")

    def test_overlay_owned_paths_are_refused_with_a_hint(self):
        result = self.commit(["shared/memory/internal.md"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["refused"][0]["reason"], "overlay_owned")
        self.assertIn("overlay_commit", result["refused"][0]["hint"])

    def test_credentials_are_refused(self):
        (self.repo / "overlays" / "work").mkdir(exist_ok=True)
        secret = self.repo / "overlays" / "work" / "secrets"
        secret.mkdir(exist_ok=True)
        (secret / "token.env").write_text("TOKEN=x\n")
        result = self.commit(["overlays/work/secrets/token.env"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["refused"][0]["reason"], "credential")

    def test_nothing_is_staged_when_one_path_is_refused(self):
        (self.repo / "shared" / "commands" / "ok.md").write_text("---\ndescription: d\n---\n")
        (self.repo / "claude" / "settings.json").write_text("{}\n")
        result = self.commit(["shared/commands/ok.md", "claude/settings.json"])
        self.assertFalse(result["ok"])
        staged = git(self.repo, "diff", "--cached", "--name-only").stdout
        self.assertEqual(staged.strip(), "")

    def test_empty_message_and_empty_paths(self):
        self.assertFalse(self.commit(["shared/commands/x.md"], message="  ")["ok"])
        self.assertFalse(self.commit([])["ok"])

    def test_missing_path(self):
        result = self.commit(["shared/commands/ghost.md"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["refused"][0]["reason"], "does not exist")


class UpdateTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        from integrated_harness_kit_mcp.tools import maintenance

        self.maintenance = maintenance
        install_doctor_stub(self.repo)
        make_overlay(self.repo, "work", priority=60, settings={"model": "work-model"})
        register_and_install(self.repo, "work", priority=60)

    def test_update_renders_reapplies_overlays_and_runs_doctor(self):
        result = self.maintenance.update(with_pull=False, repo_path=str(self.repo))
        self.assertTrue(result["ok"], result)
        names = [step["step"] for step in result["steps"]]
        self.assertEqual(names, ["render artifacts", "overlay install", "doctor.sh"])
        self.assertIn("work-model", (self.repo / "claude" / "settings.json").read_text())

    def test_a_failing_doctor_fails_the_update(self):
        install_doctor_stub(self.repo, "#!/usr/bin/env bash\necho broken\nexit 1\n")
        result = self.maintenance.update(with_pull=False, repo_path=str(self.repo))
        self.assertFalse(result["ok"])

    def test_pull_failure_stops_before_rendering(self):
        result = self.maintenance.update(with_pull=True, repo_path=str(self.repo))
        self.assertFalse(result["ok"])
        self.assertEqual([s["step"] for s in result["steps"]], ["git pull --ff-only"])
