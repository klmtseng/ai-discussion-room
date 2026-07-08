"""Hardening cases from validity-audit 2026-07-08.

These are the mid-sentence self-identification forms the original
_SELF_ID_PATTERNS missed. Neutral third-person mentions of AI products
inside answer content are preserved by design (not attribution signals),
so they are asserted UNCHANGED here.
"""
import unittest

import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from anonymizer import filter_self_id


LEAK_MARKERS = (
    "made by Anthropic", "Google trained me", "OpenAI trained me",
    "Claude 模型", "作為Google的Gemini", "GPT-4 級別的我", "claude.ai",
)


class TestSelfIdHardening(unittest.TestCase):
    def assert_scrubbed(self, text, *forbidden):
        out = filter_self_id(text, "A")
        for f in forbidden:
            self.assertNotIn(f, out, f"leak: {f!r} survived in {out!r}")

    def test_made_by_vendor_mid_sentence(self):
        self.assert_scrubbed("I'm Claude, made by Anthropic.",
                             "Claude", "made by Anthropic")

    def test_vendor_trained_me(self):
        self.assert_scrubbed("Gemini here! Google trained me well.",
                             "Gemini here", "Google trained me")
        self.assert_scrubbed("This reminds me of how OpenAI trained me.",
                             "OpenAI trained me")

    def test_zh_residual_model_suffix(self):
        self.assert_scrubbed("我是由 Anthropic 開發的 Claude 模型",
                             "Anthropic", "Claude 模型")

    def test_zh_zuowei_vendor_model(self):
        self.assert_scrubbed("作為Google的Gemini,我的看法是",
                             "作為Google的Gemini")

    def test_level_of_me(self):
        self.assert_scrubbed("GPT-4 級別的我覺得", "GPT-4 級別的我")

    def test_product_url(self):
        self.assert_scrubbed("你可以到 claude.ai 找我", "claude.ai")

    def test_neutral_third_person_preserved(self):
        # By design: content ABOUT models is not an attribution signal.
        text = "市面上的大型語言模型各有優劣,選擇時應看使用情境。"
        self.assertEqual(filter_self_id(text, "A"), text)


if __name__ == "__main__":
    unittest.main()
