"""Chair choke-point hard redaction (VA cold review 2026-07-08, P2-1).

filter_self_id is best-effort; these tests pin the STRUCTURAL guarantee:
no brand token in member-derived text can survive build_chair_prompt.
Leak phrasings below are the exact cases the cold reviewer proved passed
the regex filter unchanged.
"""
import re
import sys
import pathlib
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from anonymizer import build_chair_prompt, redact_model_names

BRANDS = ["Claude", "ChatGPT", "Gemini", "GPT-4", "Bard", "Codex",
          "Anthropic", "OpenAI", "DeepMind"]

COLD_REVIEW_LEAKS = [
    "This response comes from Gemini.",
    "My name is Claude.",
    "I, Claude, believe the answer is yes.",
    "(Powered by GPT-4)",
    "Claude thinks this is correct.",
    "根據我作為Google的Gemini模型的訓練",
]


def brands_in(text: str):
    return [b for b in BRANDS if re.search(rf"\b{re.escape(b)}\b", text, re.I)]


class TestChairChokePoint(unittest.TestCase):
    def test_cold_review_leaks_never_reach_chair(self):
        for leak in COLD_REVIEW_LEAKS:
            prompt = build_chair_prompt(
                question="測試議題",
                anon_responses={"A": leak, "B": "正常回答", "C": "正常回答"},
                member_statuses={"A": "done", "B": "done", "C": "done"},
                chair_system="",
            )
            # strip the standing instruction line, which legitimately lists brands
            body = "\n".join(
                l for l in prompt.splitlines() if not l.startswith("重要：")
            )
            self.assertEqual(brands_in(body), [], f"leaked via: {leak!r}")

    def test_followup_question_addressing_member_by_brand_is_redacted(self):
        prompt = build_chair_prompt(
            question="測試議題",
            anon_responses={"A": "回答"},
            member_statuses={"A": "done"},
            chair_system="",
            is_resummary=True,
            followup_summaries=[
                {"member": "A", "question": "Claude 你覺得呢?",
                 "response": "I am made by Anthropic and I agree."}
            ],
        )
        body = "\n".join(
            l for l in prompt.splitlines() if not l.startswith("重要：")
        )
        self.assertEqual(brands_in(body), [])

    def test_main_question_is_intentionally_not_redacted(self):
        prompt = build_chair_prompt(
            question="比較 ChatGPT 和 Gemini 哪個比較好?",
            anon_responses={"A": "回答"},
            member_statuses={"A": "done"},
            chair_system="",
        )
        self.assertIn("ChatGPT", prompt.split("以下為")[0] + prompt)

    def test_redact_replaces_with_neutral_token(self):
        out = redact_model_names("Claude and Gemini and GPT-4o disagree")
        self.assertEqual(brands_in(out), [])
        self.assertIn("[某AI]", out)


if __name__ == "__main__":
    unittest.main()
