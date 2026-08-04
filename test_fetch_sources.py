#!/usr/bin/env python3
"""Unit tests for the tiered-fetch logic — the branchy, reliability-critical parts
that don't need the network: tier fallthrough, the degraded-detection predicate,
Reddit's validity marker, the Medium feed-URL builder, and auth totality.

Run: python3 -m unittest test_fetch_sources -v   (stdlib only, no deps)
"""
import os
import tempfile
import unittest

os.environ.setdefault("BRIEF_SECRETS_DIR", tempfile.mkdtemp())  # isolate from real secrets

import auth
import fetch_sources as fs


class RunTiers(unittest.TestCase):
    def test_serves_first_acceptable_and_skips_empty_raise_rejected(self):
        tiers = [
            ("a", lambda: [], None),                                  # empty → skip
            ("b", lambda: (_ for _ in ()).throw(RuntimeError()), None),  # raises → skip
            ("c", lambda: [{"x": 1}], lambda items: False),           # rejected → skip
            ("d", lambda: [{"ok": 1}], None),                         # served
        ]
        items, tier = fs.run_tiers("test", tiers)
        self.assertEqual(tier, "d")
        self.assertEqual(items, [{"ok": 1}])

    def test_all_fail_returns_empty_none(self):
        items, tier = fs.run_tiers("test", [("a", lambda: [], None)])
        self.assertEqual((items, tier), ([], None))


class DegradedPredicate(unittest.TestCase):
    """Guards the Block fix: Medium's always-`follows` state must not mask a
    Reddit/Substack degrade, and the zero-setup default must not false-alarm."""

    def test_no_creds_configured_never_degraded(self):
        prov = {"reddit": "public", "substack": "feeds", "medium": "follows"}
        self.assertEqual(fs.is_degraded(prov, {"reddit": False, "substack": False}), [])

    def test_configured_but_fell_back_is_degraded(self):
        prov = {"reddit": "public", "substack": "feeds", "medium": "follows"}
        self.assertEqual(
            sorted(fs.is_degraded(prov, {"reddit": True, "substack": True})),
            ["reddit", "substack"])

    def test_medium_follows_does_not_mask_reddit_degrade(self):
        # Reddit configured + fell back, Medium healthy on follows → still degraded.
        prov = {"reddit": "public", "substack": "subscriptions", "medium": "follows"}
        self.assertEqual(fs.is_degraded(prov, {"reddit": True, "substack": True}), ["reddit"])

    def test_healthy_personalized_not_degraded(self):
        prov = {"reddit": "home-oauth", "substack": "subscriptions", "medium": "follows"}
        self.assertEqual(fs.is_degraded(prov, {"reddit": True, "substack": True}), [])


class RedditValidityMarker(unittest.TestCase):
    def test_rejects_rpopular_degrade_accepts_overlap(self):
        accept = fs._reddit_rss_is_personalized({"subreddits": ["programming", "rust"]})
        self.assertFalse(accept([{"_subreddit": "funny"}, {"_subreddit": "pics"}]))
        self.assertTrue(accept([{"_subreddit": "funny"}, {"_subreddit": "programming"}]))

    def test_lenient_when_no_subreddits_configured(self):
        accept = fs._reddit_rss_is_personalized({"subreddits": []})
        self.assertTrue(accept([{"_subreddit": "anything"}]))


class MediumFeedURL(unittest.TestCase):
    def test_builds_author_tag_publication_and_rejects_unknown(self):
        self.assertEqual(fs._medium_feed_url({"type": "author", "handle": "@foo"}),
                         "https://medium.com/feed/@foo")
        self.assertEqual(fs._medium_feed_url({"type": "tag", "handle": "ai"}),
                         "https://medium.com/feed/tag/ai")
        self.assertEqual(fs._medium_feed_url({"type": "publication", "handle": "better-programming"}),
                         "https://medium.com/feed/better-programming")
        self.assertIsNone(fs._medium_feed_url({"type": "bogus", "handle": "x"}))
        self.assertIsNone(fs._medium_feed_url({"type": "author", "handle": ""}))


class AuthTotality(unittest.TestCase):
    """With an empty secrets dir, every accessor returns None — never raises."""

    def test_missing_secrets_return_none(self):
        self.assertIsNone(auth.reddit_bearer())
        self.assertIsNone(auth.substack_cookie_header())
        self.assertIsNone(auth.read_json_secret("nonexistent.json"))
        self.assertIsNone(auth.read_secret("nonexistent"))


class NoSignalCap(unittest.TestCase):
    """Items with zero engagement in a group that HAS engagement signals must be
    capped at 0.6 score_norm so they can't out-rank real engagement. Editorial
    sources (no signals for the whole group) must NOT be capped."""

    def test_zero_signal_item_capped_in_mixed_group(self):
        items = [
            {"points": 100, "num_comments": 50, "created_at": 1, "url": "a"},
            {"points": 0, "num_comments": 0, "created_at": 2, "url": "b"},
        ]
        fs.score_source(items, {}, 1.0)
        self.assertLessEqual(items[1]["score_norm"], 0.6)

    def test_editorial_group_not_capped(self):
        items = [
            {"points": 0, "num_comments": 0, "created_at": 2, "url": "a"},
            {"points": 0, "num_comments": 0, "created_at": 1, "url": "b"},
        ]
        fs.score_source(items, {}, 1.0)
        self.assertGreater(items[0]["score_norm"], 0.6)


if __name__ == "__main__":
    unittest.main()
