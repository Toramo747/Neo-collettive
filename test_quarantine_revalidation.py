import unittest

from quarantine_revalidation import revalidate_quarantined_rows


def legacy_row(**overrides):
    row={
        "schema_v":2,
        "tagger_v":2,
        "migration_v":2,
        "gate_eligible":False,
        "quarantine_reason":"legacy_unverified_tagger_v1",
        "domain":"example.com",
        "source":"web",
        "family":"manual_data_entry",
        "problem_key_raw":"manual_data_entry:manual_data_entry",
        "problem_key":"manual_data_entry:manual_data_entry",
        "query":"manual data entry",
        "query_role":"buyer",
        "title":"Old manual data entry evidence",
        "snippet":"Old legacy snippet",
        "url":"https://example.com/manual-data-entry",
        "signal_types":[],
        "last_seen_epoch":1,
        "first_seen_epoch":1,
    }
    row.update(overrides)
    return row


class QuarantineRevalidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_refetch_can_promote(self):
        async def fetcher(url,row):
            return {
                "ok":True,
                "url":url,
                "title":"Manual data entry help needed",
                "body":"We need help with manual data entry every week. We are hiring a contractor and have a budget because the work is repetitive and time consuming.",
            }

        rows,stats=await revalidate_quarantined_rows(
            [legacy_row()],
            fetcher,
            limit=3,
            now_epoch=1000,
        )
        self.assertEqual(stats,{"attempted":1,"promoted":1,"failed":0,"unreachable":0})
        self.assertTrue(rows[0]["gate_eligible"])
        self.assertEqual(rows[0]["revalidated"],"promoted")
        self.assertIsNone(rows[0]["quarantine_reason"])
        self.assertEqual(rows[0]["last_seen_epoch"],1000)
        self.assertTrue({"PAIN","BUY_INTENT","PAID_DEMAND"} & set(rows[0]["signal_types"]))

    async def test_successful_refetch_that_fails_checks_stays_quarantined(self):
        async def fetcher(url,row):
            return {
                "ok":True,
                "url":url,
                "title":"Unrelated cooking article",
                "body":"A recipe about tomatoes and olive oil with no business workflow context.",
            }

        rows,stats=await revalidate_quarantined_rows([legacy_row()],fetcher,limit=3,now_epoch=1000)
        self.assertEqual(stats["failed"],1)
        self.assertFalse(rows[0]["gate_eligible"])
        self.assertEqual(rows[0]["revalidated"],"failed")
        self.assertNotEqual(rows[0].get("quarantine_reason"),None)

    async def test_third_fetch_failure_marks_unreachable(self):
        async def fetcher(url,row):
            return {"ok":False,"error":"timeout"}

        rows,stats=await revalidate_quarantined_rows(
            [legacy_row(revalidation_attempts=2)],
            fetcher,
            limit=3,
            max_fetch_attempts=3,
            now_epoch=1000,
        )
        self.assertEqual(stats,{"attempted":1,"promoted":0,"failed":0,"unreachable":1})
        self.assertFalse(rows[0]["gate_eligible"])
        self.assertEqual(rows[0]["revalidated"],"unreachable")
        self.assertEqual(rows[0]["revalidation_attempts"],3)

    async def test_cycle_limit_is_respected(self):
        calls=[]
        async def fetcher(url,row):
            calls.append(url)
            return {"ok":False,"error":"timeout"}

        input_rows=[
            legacy_row(url=f"https://example.com/{i}")
            for i in range(5)
        ]
        rows,stats=await revalidate_quarantined_rows(input_rows,fetcher,limit=2,now_epoch=1000)
        self.assertEqual(stats["attempted"],2)
        self.assertEqual(len(calls),2)
        self.assertEqual(sum(int(r.get("revalidation_attempts") or 0) for r in rows),2)

    async def test_disconfirm_is_never_touched(self):
        calls=[]
        async def fetcher(url,row):
            calls.append(url)
            return {"ok":True,"url":url,"title":"Manual data entry","body":"Manual data entry pain."}

        original=legacy_row(
            quarantine_reason="disconfirm",
            signal_types=["DISCONFIRM"],
            url="https://example.com/disconfirm",
        )
        rows,stats=await revalidate_quarantined_rows([original],fetcher,limit=3,now_epoch=1000)
        self.assertEqual(stats["attempted"],0)
        self.assertEqual(calls,[])
        self.assertEqual(rows[0],original)

    async def test_failed_fetch_can_never_promote(self):
        async def fetcher(url,row):
            return {"ok":False,"error":"http_503"}

        rows,stats=await revalidate_quarantined_rows(
            [legacy_row(signal_types=["PAIN","BUY_INTENT","PAID_DEMAND"])],
            fetcher,
            limit=3,
            now_epoch=1000,
        )
        self.assertEqual(stats["promoted"],0)
        self.assertFalse(rows[0]["gate_eligible"])
        self.assertEqual(rows[0]["quarantine_reason"],"legacy_unverified_tagger_v1")

    async def test_refetched_seller_launch_never_gets_pain(self):
        async def fetcher(url,row):
            return {
                "ok":True,
                "url":url,
                "title":"Show HN: Manual data entry automation for repetitive workflows",
                "body":"I built a product because manual data entry is repetitive and time consuming. Pricing is available.",
            }

        rows,stats=await revalidate_quarantined_rows([legacy_row()],fetcher,limit=3,now_epoch=1000)
        self.assertEqual(stats["failed"],1)
        self.assertFalse(rows[0]["gate_eligible"])
        self.assertEqual(rows[0]["revalidated"],"failed")
        self.assertEqual(rows[0]["quarantine_reason"],"seller_launch")
        self.assertEqual(rows[0]["signal_reverted"],"seller_launch")
        self.assertNotIn("PAIN",set(rows[0].get("signal_types") or []))

    async def test_terminal_failed_row_is_not_retried(self):
        calls=[]
        async def fetcher(url,row):
            calls.append(url)
            return {"ok":True,"url":url,"title":"Manual data entry","body":"Manual data entry is repetitive."}

        row=legacy_row(revalidated="failed",revalidation_reason="no_family")
        rows,stats=await revalidate_quarantined_rows([row],fetcher,limit=3,now_epoch=1000)
        self.assertEqual(stats["attempted"],0)
        self.assertEqual(calls,[])
        self.assertEqual(rows[0]["revalidated"],"failed")


if __name__=="__main__":
    unittest.main()
