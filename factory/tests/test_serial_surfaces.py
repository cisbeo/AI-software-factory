"""Control: one job at a time builds on a serial surface (config `serial_surfaces`).

Two jobs touching the same serial surface (by default `migration`) would race:
both would write the next schema change, whatever the target repo's migration
tool. `job advance <job> build` refuses while another job on that surface is
between build and merging.

Blocked: a second `migration` job entering build while one is in review.
Neighbour: a `ui` job entering build at the same time; a second `migration`
job once the first is merged; `serial_surfaces` emptied.
Not understood: `serial_surfaces` that isn't a list of names, or that names a
surface `surface_reviewers` doesn't know: refused, job untouched.
"""

import unittest

from helpers import FactoryCase, write


def intake(surfaces):
    return {"decision": "ACCEPT", "rescoped": False, "risk": "medium", "surfaces": surfaces}


class SerialSurfaces(FactoryCase):
    scripts = ("job",)

    def spec_job(self, job_id, surfaces):
        d = self.make_job(job_id, stage="spec", intake=intake(surfaces),
                          agents={"reviewers": {"spec": "sonnet"}})
        write(d / "intake.md", "DECISION: ACCEPT\nRISK: medium\nSURFACES: "
              + (", ".join(surfaces) or "none") + "\nRESCOPED: no\n\nScope.\n")
        write(d / "spec.md", "# Spec\n")
        return job_id

    def advance(self, job_id, stage="build"):
        return self.bin("job", "advance", job_id, stage)

    # ---- blocked ----

    def test_second_migration_job_waits(self):
        self.make_job("001-first", issue=1, stage="review", round=1, intake=intake(["migration"]))
        self.spec_job("002-second", ["migration"])
        before = self.read_job("002-second")
        res = self.advance("002-second")
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("serial surface migration", res.stderr)
        self.assertIn("001-first", res.stderr)
        self.assertEqual(self.read_job("002-second"), before)
        self.assertEqual(self.forge_calls(), [])

    # ---- neighbours that pass ----

    def test_other_surface_builds_alongside(self):
        self.make_job("001-first", issue=1, stage="review", round=1, intake=intake(["migration"]))
        self.spec_job("002-second", ["ui"])
        res = self.advance("002-second")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.read_job("002-second")["stage"], "build")

    def test_migration_job_builds_once_the_first_is_merged(self):
        self.make_job("001-first", issue=1, stage="merged", round=1, intake=intake(["migration"]),
                      ended="2026-11-19T01:00:00Z")
        self.spec_job("002-second", ["migration"])
        self.assertEqual(self.advance("002-second").returncode, 0)

    def test_no_serial_surface_configured(self):
        self.config["serial_surfaces"] = []
        self.write_config()
        self.make_job("001-first", issue=1, stage="review", round=1, intake=intake(["migration"]))
        self.spec_job("002-second", ["migration"])
        self.assertEqual(self.advance("002-second").returncode, 0)

    # ---- input not understood ----

    def test_malformed_serial_surfaces_is_refused(self):
        for bad in ("migration", [1], [""], ["billing"], None):
            with self.subTest(serial_surfaces=bad):
                self.config["serial_surfaces"] = bad
                self.write_config()
                self.spec_job("002-second", ["ui"])
                before = self.read_job("002-second")
                res = self.advance("002-second")
                self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
                self.assertIn("serial_surfaces", res.stderr)
                self.assertNotIn("Traceback", res.stderr)
                self.assertEqual(self.read_job("002-second"), before)


if __name__ == "__main__":
    unittest.main()
