"""Control: the factory carries nothing from the project it was copied from.

Blocked: a name of the original project or of its stack (its ORM, database,
host) anywhere under factory/ or .claude/, outside CREDITS.md files.
Neighbour: the same names in CREDITS.md stay allowed (attribution).
Not understood: a file that isn't UTF-8 text is reported by name, not skipped.

Also: a CODING_STANDARDS.md template exists at the root, and reviewer-standards
says what to do in a target repo that has none.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Spelled in pieces so this file doesn't match itself.
FORBIDDEN = re.compile(r"\b(" + "|".join(["fsa" + "linear", "driz" + "zle", "ne" + "on", "ver" + "cel"]) + r")\b", re.I)


def scanned_files():
    for top in ("factory", ".claude"):
        for path in sorted((ROOT / top).rglob("*")):
            rel = path.relative_to(ROOT)
            if not path.is_file() or path.name == "CREDITS.md":
                continue
            if rel.parts[:2] == ("factory", "jobs") or "__pycache__" in rel.parts:
                continue
            yield path


def leftovers(paths):
    hits = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            hits.append(f"{path.relative_to(ROOT)}: not UTF-8 text, can't be checked")
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if FORBIDDEN.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()}")
    return hits


class Leftovers(unittest.TestCase):
    def test_no_leftover_names(self):
        self.assertEqual(leftovers(scanned_files()), [])

    def test_the_scan_sees_a_leftover(self):
        import tempfile
        with tempfile.TemporaryDirectory(dir=ROOT / "factory") as tmp:
            bad = Path(tmp) / "x.md"
            bad.write_text("Run the " + "Driz" + "zle migration.\n")
            self.assertEqual(len(leftovers([bad])), 1)

    def test_credits_may_name_the_origin(self):
        names = [p.name for p in scanned_files()]
        self.assertNotIn("CREDITS.md", names)

    def test_binary_file_is_reported(self):
        import tempfile
        with tempfile.TemporaryDirectory(dir=ROOT / "factory") as tmp:
            bad = Path(tmp) / "x.bin"
            bad.write_bytes(b"\xff\xfe\x00bad")
            self.assertIn("not UTF-8", leftovers([bad])[0])


class StandardsTemplate(unittest.TestCase):
    def test_template_exists(self):
        text = (ROOT / "CODING_STANDARDS.md").read_text()
        self.assertTrue(text.startswith("# "), "CODING_STANDARDS.md must be a Markdown document")

    def test_reviewer_handles_a_missing_file(self):
        text = (ROOT / ".claude" / "agents" / "reviewer-standards.md").read_text()
        self.assertIn("If `CODING_STANDARDS.md` doesn't exist", text)


if __name__ == "__main__":
    unittest.main()
