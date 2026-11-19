"""Admission controls of spec §6, enforced by `job create` and `job queue`.

- A ticket starts only once every blocker is finished: closed as done. A
  blocker that is open, or closed as not planned or duplicate, still blocks.
- No new job while the merge requests waiting for a human (open, not drafts)
  reach config `max_waiting_for_human`.
- `job queue` gives the reason on the row (`blocked`, `hold`) that
  /factory run shows.

Forge calls go through the real factory/bin/forge, backed by the fake gh.
"""

import unittest

from helpers import FactoryCase

LABEL = "factory"


class AdmissionCase(FactoryCase):
    scripts = ("job",)

    def setUp(self):
        super().setUp()
        self.world = self.use_fake_forge()

    def ticket(self, title="Do it", body=""):
        return self.world.ticket(title, body=body, labels=[LABEL])

    def waiting(self, n, draft=False):
        for _ in range(n):
            self.world.mr(draft=draft)

    def create(self, n):
        return self.bin("job", "create", str(n))

    def queue(self):
        res = self.bin("job", "queue")
        self.assertEqual(res.returncode, 0, res.stderr)
        return [line.split("\t") for line in res.stdout.splitlines()]

    def assert_created(self, res):
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(len(list(self.jobs.iterdir())), 1)

    def assert_not_created(self, res, says):
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn(says, res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertEqual(list(self.jobs.iterdir()), [])


class Blockers(AdmissionCase):
    # ---- blocked ----

    def test_open_blocker_holds_the_ticket(self):
        b = self.world.ticket("blocker")
        n = self.ticket(body=f"Bloqué par #{b}")
        self.assert_not_created(self.create(n), f"#{b}")
        [row] = [r for r in self.queue() if r[1] == str(n)]
        self.assertEqual(row[0], "blocked")
        self.assertIn(f"#{b}", row[4])
        self.assertIn("not merged", row[4])

    def test_blocker_closed_without_being_done_still_holds(self):
        b = self.world.ticket("blocker")
        self.world.close(b, "not_planned")
        n = self.ticket(body=f"Bloqué par #{b}")
        self.assert_not_created(self.create(n), f"#{b}")
        self.assertEqual([r[0] for r in self.queue() if r[1] == str(n)], ["blocked"])

    # ---- neighbour that passes ----

    def test_blocker_done_lets_the_ticket_in(self):
        b = self.world.ticket("blocker")
        self.world.close(b)
        n = self.ticket(body=f"Bloqué par #{b}")
        self.assertEqual([r[0] for r in self.queue() if r[1] == str(n)], ["new"])
        self.assert_created(self.create(n))

    # ---- input not understood ----

    def test_unreadable_blockers_hold_the_ticket(self):
        n = self.ticket()
        self.world.block(n, 999)
        self.world.without_native_dependencies(code=403)
        self.assert_not_created(self.create(n), "illisibles")


class ReviewCapacity(AdmissionCase):
    # ---- blocked ----

    def test_limit_reached_holds_new_jobs(self):
        self.waiting(3)
        n = self.ticket()
        self.assert_not_created(self.create(n), "3 merge requests waiting for a human (limit 3)")
        [row] = [r for r in self.queue() if r[1] == str(n)]
        self.assertEqual(row[0], "hold")
        self.assertIn("waiting for a human", row[4])

    def test_lower_limit_from_config(self):
        self.config["max_waiting_for_human"] = 1
        self.write_config()
        self.waiting(1)
        self.assert_not_created(self.create(self.ticket()), "(limit 1)")

    # ---- neighbours that pass ----

    def test_drafts_do_not_count(self):
        self.waiting(2)
        self.waiting(5, draft=True)
        n = self.ticket()
        self.assertEqual([r[0] for r in self.queue() if r[1] == str(n)], ["new"])
        self.assert_created(self.create(n))

    def test_running_jobs_resume_at_the_limit(self):
        self.waiting(3)
        n = self.ticket()
        self.make_job("001-test", issue=n, stage="build", round=1)
        self.assertEqual([r[0] for r in self.queue() if r[1] == str(n)], ["resume"])

    # ---- input not understood ----

    def test_malformed_limit_is_refused(self):
        n = self.ticket()
        for bad in ("3", 0, -1, 1.5, True, None):
            with self.subTest(max_waiting_for_human=bad):
                self.config["max_waiting_for_human"] = bad
                self.write_config()
                self.assert_not_created(self.create(n), "max_waiting_for_human")
                res = self.bin("job", "queue")
                self.assertEqual(res.returncode, 1)
                self.assertIn("max_waiting_for_human", res.stderr)

    def test_unreadable_merge_requests_hold_new_jobs(self):
        n = self.ticket()
        self.world.edit(lambda s: s.update(pulls_error=502))
        self.assert_not_created(self.create(n), "demandes de fusion illisibles")
        self.assertEqual(self.bin("job", "queue").returncode, 1)


if __name__ == "__main__":
    unittest.main()
