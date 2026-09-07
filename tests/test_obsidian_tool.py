"""Tests for tools/obsidian_tool.py — vault reads, writes, management, and
the note graph. Semantic search (ask_vault/index_vault) is not covered here:
it needs ChromaDB plus the embedding model, which is too slow for the suite."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json

import pytest

import tools.obsidian_tool as ob


@pytest.fixture(autouse=True)
def vault(tmp_path, monkeypatch):
    """Point the tool at a throwaway vault for every test."""
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    return tmp_path


class TestVaultResolution:
    def test_missing_vault_reports_setup(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_VAULT", "Z:/nope/not/here")
        assert "not found" in ob.search_vault("anything")

    def test_env_var_wins_over_defaults(self, vault):
        assert ob._vault() == vault


class TestWrite:
    def test_create_and_read(self, vault):
        ob.create_note("Ideas", "first thought")
        assert (vault / "Ideas.md").read_text(encoding="utf-8") == "first thought"
        assert "first thought" in ob.read_note("Ideas")

    def test_create_nests_folder(self, vault):
        ob.create_note("Lecture 1", "notes", folder="Uni/CS")
        assert (vault / "Uni" / "CS" / "Lecture 1.md").is_file()

    def test_duplicate_title_suffixes_instead_of_overwriting(self, vault):
        ob.create_note("Ideas", "original")
        ob.create_note("Ideas", "second")
        assert (vault / "Ideas.md").read_text(encoding="utf-8") == "original"
        assert (vault / "Ideas 2.md").is_file()

    def test_append_creates_missing_note(self, vault):
        out = ob.append_to_note("Brand New", "a line")
        assert "Created" in out
        assert "a line" in (vault / "Brand New.md").read_text(encoding="utf-8")

    def test_append_adds_newline_between_lines(self, vault):
        ob.create_note("Log", "line one")
        ob.append_to_note("Log", "line two")
        assert (vault / "Log.md").read_text(encoding="utf-8") == "line one\nline two\n"

    def test_daily_note_uses_iso_name_by_default(self, vault):
        from datetime import date
        ob.append_to_daily_note("did a thing")
        note = vault / f"{date.today().isoformat()}.md"
        assert "did a thing" in note.read_text(encoding="utf-8")

    def test_daily_note_honours_obsidian_config(self, vault):
        cfg = vault / ".obsidian"
        cfg.mkdir()
        (cfg / "daily-notes.json").write_text(
            json.dumps({"format": "YYYY-MM-DD", "folder": "Journal"}), encoding="utf-8"
        )
        from datetime import date
        ob.append_to_daily_note("captured")
        assert (vault / "Journal" / f"{date.today().isoformat()}.md").is_file()


class TestSafety:
    def test_create_rejects_folder_outside_vault(self):
        assert "outside the vault" in ob.create_note("evil", folder="../../escape")

    def test_list_rejects_folder_outside_vault(self):
        assert "outside the vault" in ob.list_notes(folder="../..")

    def test_move_rejects_folder_outside_vault(self, vault):
        ob.create_note("Note")
        assert "outside the vault" in ob.move_note("Note", "../../escape")

    def test_delete_moves_to_trash_not_erased(self, vault):
        ob.create_note("Doomed", "still here")
        out = ob.delete_note("Doomed")
        assert "recoverable" in out
        assert not (vault / "Doomed.md").exists()
        assert (vault / ".trash" / "Doomed.md").read_text(encoding="utf-8") == "still here"

    def test_trashed_notes_stay_out_of_listings(self, vault):
        ob.create_note("Doomed")
        ob.delete_note("Doomed")
        assert "Doomed" not in ob.list_notes()


class TestResolution:
    def test_resolve_by_path_and_wikilink(self, vault):
        ob.create_note("Lecture 1", "body", folder="Uni")
        assert "body" in ob.read_note("Uni/Lecture 1")
        assert "body" in ob.read_note("[[Lecture 1]]")
        assert "body" in ob.read_note("lecture 1")

    def test_wikilink_alias_and_heading_are_stripped(self, vault):
        ob.create_note("Target", "body")
        assert "body" in ob.read_note("[[Target|the alias]]")
        assert "body" in ob.read_note("[[Target#some heading]]")

    def test_unknown_note_reports_clearly(self):
        assert "no note named" in ob.read_note("does not exist")


class TestSearch:
    def test_title_and_body_matches(self, vault):
        ob.create_note("Calculus", "derivatives and limits")
        assert "Calculus.md" in ob.search_vault("calculus")
        assert "Calculus.md" in ob.search_vault("derivatives")

    def test_no_match_is_explicit(self):
        assert "No notes found" in ob.search_vault("nothing here")

    def test_empty_query_rejected(self):
        assert "empty search query" in ob.search_vault("   ")


class TestFrontmatterAndCanvas:
    def test_properties_surface_in_read(self, vault):
        (vault / "Note.md").write_text(
            "---\ntags: [math, uni]\nstatus: active\n---\nthe body\n", encoding="utf-8"
        )
        out = ob.read_note("Note")
        assert "Properties:" in out and "status: active" in out
        assert "the body" in out

    def test_canvas_text_nodes_are_readable(self, vault):
        (vault / "Board.canvas").write_text(
            json.dumps({"nodes": [{"type": "text", "text": "canvas idea"}]}),
            encoding="utf-8",
        )
        assert "canvas idea" in ob.read_note("Board")
        assert "Board.canvas" in ob.search_vault("canvas idea")


class TestGraph:
    def test_backlinks_and_outgoing(self, vault):
        ob.create_note("Calculus", "see [[Linear Algebra]] and [[Ghost]]")
        ob.create_note("Linear Algebra", "eigenvectors")
        assert "Calculus.md" in ob.get_backlinks("Linear Algebra")
        out = ob.get_outgoing_links("Calculus")
        assert "Linear Algebra" in out
        assert "no note yet" in out

    def test_no_backlinks_is_explicit(self, vault):
        ob.create_note("Lonely", "nothing links here")
        assert "No notes link to" in ob.get_backlinks("Lonely")

    def test_tags_from_body_and_frontmatter(self, vault):
        (vault / "A.md").write_text("---\ntags: [uni]\n---\nbody #math\n", encoding="utf-8")
        ob.create_note("B", "more #math")
        tags = ob.list_vault_tags()
        assert "#math (2)" in tags and "#uni (1)" in tags

    def test_tags_ignore_headings_and_code_fences(self, vault):
        ob.create_note("A", "# Heading not a tag\n```\n#notatag\n```\n#real")
        tags = ob.list_vault_tags()
        assert "#real" in tags
        assert "notatag" not in tags
        assert "Heading" not in tags

    def test_search_by_tag_matches_nested(self, vault):
        ob.create_note("A", "#math/calculus")
        assert "A.md" in ob.search_vault_by_tag("math")
        assert "A.md" in ob.search_vault_by_tag("#math/calculus")

    def test_search_by_unused_tag(self, vault):
        ob.create_note("A", "no tags")
        assert "No notes tagged" in ob.search_vault_by_tag("ghost")


class TestManage:
    def test_rename_repoints_wikilinks(self, vault):
        ob.create_note("Old Name", "content")
        ob.create_note("Linker", "see [[Old Name]] here")
        out = ob.rename_note("Old Name", "New Name")
        assert "updated links in 1 note" in out
        assert (vault / "New Name.md").is_file()
        assert "[[New Name]]" in (vault / "Linker.md").read_text(encoding="utf-8")

    def test_rename_preserves_alias_and_heading(self, vault):
        ob.create_note("Old", "content")
        ob.create_note("Linker", "[[Old|alias]] and [[Old#head]]")
        ob.rename_note("Old", "New")
        text = (vault / "Linker.md").read_text(encoding="utf-8")
        assert "[[New|alias]]" in text and "[[New#head]]" in text

    def test_rename_leaves_other_links_alone(self, vault):
        ob.create_note("Old", "c")
        ob.create_note("Older", "c")
        ob.create_note("Linker", "[[Old]] and [[Older]]")
        ob.rename_note("Old", "New")
        text = (vault / "Linker.md").read_text(encoding="utf-8")
        assert "[[New]]" in text and "[[Older]]" in text

    def test_rename_onto_existing_name_refused(self, vault):
        ob.create_note("A", "a")
        ob.create_note("B", "b")
        out = ob.rename_note("A", "B")
        assert "already exists" in out
        assert (vault / "A.md").is_file()

    def test_move_note(self, vault):
        ob.create_note("Note", "body")
        ob.move_note("Note", "Archive")
        assert (vault / "Archive" / "Note.md").is_file()

    def test_move_onto_existing_refused(self, vault):
        ob.create_note("Note", "one")
        ob.create_note("Note", "two", folder="Archive")
        assert "already exists" in ob.move_note("Note", "Archive")

    def test_manage_ops_on_missing_note(self):
        assert "no note named" in ob.delete_note("ghost")
        assert "no note named" in ob.rename_note("ghost", "x")
        assert "no note named" in ob.move_note("ghost", "x")
