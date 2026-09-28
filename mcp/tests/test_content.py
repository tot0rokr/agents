"""scaffold / remove_content — where new content lands and what is refused."""

from __future__ import annotations

from tests._helpers import HarnessTestCase, make_overlay, register_and_install, write_skill


class ScaffoldTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        from integrated_harness_kit_mcp.tools import content

        self.content = content
        make_overlay(self.repo, "work", priority=60)
        register_and_install(self.repo, "work", priority=60)

    def test_skill_lands_in_the_base_tree(self):
        result = self.content.scaffold(
            "skills", "new-skill", description="does a thing", repo_path=str(self.repo)
        )
        self.assertTrue(result["ok"], result)
        skill = self.repo / "universal" / "skills" / "new-skill" / "SKILL.md"
        self.assertTrue(skill.is_file())
        self.assertIn("name: new-skill", skill.read_text())

    def test_command_and_subagent_and_instruction(self):
        for kind, rel in (
            ("commands", "shared/commands/c1.md"),
            ("subagents", "shared/subagents/s1.md"),
            ("instructions", "shared/instructions/i1.md"),
        ):
            name = rel.rsplit("/", 1)[1][:-3]
            result = self.content.scaffold(kind, name, description="d", repo_path=str(self.repo))
            self.assertTrue(result["ok"], result)
            self.assertTrue((self.repo / rel).is_file(), rel)

    def test_overlay_target_writes_into_the_overlay_and_links_back(self):
        result = self.content.scaffold(
            "memory",
            "internal-fact",
            description="an internal fact",
            target="overlay:work",
            repo_path=str(self.repo),
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["path"], "overlays/work/memory/internal-fact.md")
        self.assertTrue(result["apply"]["ok"], result["apply"])
        link = self.repo / "shared" / "memory" / "internal-fact.md"
        self.assertTrue(link.is_symlink())

    def test_overlay_memory_gets_an_index_line(self):
        self.content.scaffold(
            "memory",
            "internal-fact",
            description="an internal fact",
            target="overlay:work",
            repo_path=str(self.repo),
        )
        fragment = (self.repo / "overlays" / "work" / "memory" / "MEMORY.md").read_text()
        self.assertIn("internal-fact.md", fragment)
        self.assertIn("an internal fact", (self.repo / "shared" / "memory" / "MEMORY.md").read_text())

    def test_existing_name_is_refused_with_provenance(self):
        write_skill(self.repo, "taken")
        result = self.content.scaffold("skills", "taken", repo_path=str(self.repo))
        self.assertFalse(result["ok"])
        self.assertEqual(result["source"], {"kind": "base"})

    def test_a_name_an_overlay_already_supplies_is_refused(self):
        self.content.scaffold(
            "memory", "claimed", target="overlay:work", repo_path=str(self.repo)
        )
        result = self.content.scaffold("memory", "claimed", repo_path=str(self.repo))
        self.assertFalse(result["ok"])
        self.assertEqual(result["source"], {"kind": "overlay", "alias": "work"})

    def test_bad_kind_and_bad_name(self):
        self.assertFalse(self.content.scaffold("nope", "x", repo_path=str(self.repo))["ok"])
        self.assertFalse(self.content.scaffold("skills", "../x", repo_path=str(self.repo))["ok"])

    def test_unknown_overlay_lists_the_registered_ones(self):
        result = self.content.scaffold(
            "memory", "x", target="overlay:ghost", repo_path=str(self.repo)
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["registered"], ["work"])


class RemoveContentTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        from integrated_harness_kit_mcp.tools import content

        self.content = content
        make_overlay(
            self.repo,
            "work",
            priority=60,
            memories={"owned": "---\nname: owned\n---\n\nx\n"},
        )
        register_and_install(self.repo, "work", priority=60)

    def test_base_content_is_removed(self):
        write_skill(self.repo, "temp")
        result = self.content.remove_content("skills", "temp", repo_path=str(self.repo))
        self.assertTrue(result["ok"], result)
        self.assertFalse((self.repo / "universal" / "skills" / "temp").exists())

    def test_overlay_owned_content_is_refused(self):
        result = self.content.remove_content("memory", "owned", repo_path=str(self.repo))
        self.assertFalse(result["ok"])
        self.assertIn("work", result["error"])
        self.assertTrue((self.repo / "shared" / "memory" / "owned.md").is_symlink())

    def test_missing_content(self):
        self.assertFalse(self.content.remove_content("skills", "ghost", repo_path=str(self.repo))["ok"])
