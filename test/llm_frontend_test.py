import os
import unittest
from unittest import mock

import llm_frontend


class FakeBackend:
    def __init__(self):
        self.calls = []

    def check_if_update_needed(self, current_article, new_text, suppress_out=True):
        self.calls.append(("check", os.environ.get("ACTIVE_MODEL")))
        return True

    def update_wp_page(self, current_article, new_text, suppress_out=True):
        self.calls.append(("full_page", os.environ.get("ACTIVE_MODEL")))
        return "updated article"

    def update_demographics_section(
        self,
        current_demographics_section,
        new_text,
        mini=True,
        suppress_out=True,
    ):
        self.calls.append(("demographics", os.environ.get("ACTIVE_MODEL"), mini))
        return "updated demographics"

    def update_lede(self, current_lede_text, population_sentence, suppress_out=True):
        self.calls.append(("lede", os.environ.get("ACTIVE_MODEL")))
        return "updated lede"


class LlmFrontendRoutingTests(unittest.TestCase):
    def test_check_uses_active_model_when_routing_disabled(self):
        backend = FakeBackend()
        requested_models = []

        with mock.patch.dict(
            os.environ,
            {
                "ACTIVE_MODEL": "gpt-5.3-codex",
            },
            clear=False,
        ):
            with mock.patch.object(
                llm_frontend,
                "_get_backend_module_for_model",
                side_effect=lambda model: requested_models.append(model) or backend,
            ):
                result = llm_frontend.check_if_update_needed("current", "new")
            restored_model = os.environ.get("ACTIVE_MODEL")

        self.assertTrue(result)
        self.assertEqual(requested_models, ["gpt-5.3-codex"])
        self.assertEqual(backend.calls, [("check", "gpt-5.3-codex")])
        self.assertEqual(restored_model, "gpt-5.3-codex")

    def test_check_routes_codex_to_mini_when_enabled(self):
        backend = FakeBackend()
        requested_models = []

        with mock.patch.dict(
            os.environ,
            {
                "ACTIVE_MODEL": "gpt-5.3-codex",
                llm_frontend.ENABLE_TASK_MODEL_ROUTING_ENV: "1",
            },
            clear=False,
        ):
            with mock.patch.object(
                llm_frontend,
                "_openai_chat_models_available",
                return_value=True,
            ):
                with mock.patch.object(
                    llm_frontend,
                    "_get_backend_module_for_model",
                    side_effect=lambda model: requested_models.append(model) or backend,
                ):
                    result = llm_frontend.check_if_update_needed("current", "new")
                restored_model = os.environ.get("ACTIVE_MODEL")

        self.assertTrue(result)
        self.assertEqual(requested_models, ["gpt-5.4-mini"])
        self.assertEqual(backend.calls, [("check", "gpt-5.4-mini")])
        self.assertEqual(restored_model, "gpt-5.3-codex")

    def test_update_wp_page_keeps_selected_claude_code_model_when_routing_enabled(self):
        backend = FakeBackend()
        requested_models = []

        with mock.patch.dict(
            os.environ,
            {
                "ACTIVE_MODEL": "claude-sonnet-4-6",
                llm_frontend.ENABLE_TASK_MODEL_ROUTING_ENV: "1",
            },
            clear=False,
        ):
            with mock.patch.object(
                llm_frontend,
                "_get_backend_module_for_model",
                side_effect=lambda model: requested_models.append(model) or backend,
            ):
                result = llm_frontend.update_wp_page("current", "new")
            restored_model = os.environ.get("ACTIVE_MODEL")

        self.assertEqual(result, "updated article")
        self.assertEqual(requested_models, ["claude-sonnet-4-6"])
        self.assertEqual(backend.calls, [("full_page", "claude-sonnet-4-6")])
        self.assertEqual(restored_model, "claude-sonnet-4-6")

    def test_update_lede_routes_claude_code_to_haiku_when_enabled(self):
        backend = FakeBackend()
        requested_models = []

        with mock.patch.dict(
            os.environ,
            {
                "ACTIVE_MODEL": "claude-opus-4-7",
                llm_frontend.ENABLE_TASK_MODEL_ROUTING_ENV: "1",
            },
            clear=False,
        ):
            with mock.patch.object(
                llm_frontend,
                "_get_backend_module_for_model",
                side_effect=lambda model: requested_models.append(model) or backend,
            ):
                result = llm_frontend.update_lede("current lede", "population sentence")
            restored_model = os.environ.get("ACTIVE_MODEL")

        self.assertEqual(result, "updated lede")
        self.assertEqual(requested_models, ["haiku"])
        self.assertEqual(backend.calls, [("lede", "haiku")])
        self.assertEqual(restored_model, "claude-opus-4-7")


if __name__ == "__main__":
    unittest.main()
