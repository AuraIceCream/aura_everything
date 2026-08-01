from __future__ import annotations

import unittest

from aura_bio.routing import (
    CONTEXT_LEVEL_POLICY,
    LearnerLevel,
    QueryRouter,
    Subdomain,
    TaskType,
    TeachingMode,
    ordered_processes_in,
)


class TaskRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = QueryRouter()

    def assert_task(self, query: str, expected: TaskType) -> None:
        route = self.router.route(query)
        self.assertEqual(
            route.task_type.label,
            expected,
            f"{query!r} routed to {route.task_type.label} via {route.task_type.matched}",
        )

    def test_task_labels(self) -> None:
        cases = [
            ("Define osmosis.", TaskType.DEFINITION),
            ("What is a ribosome?", TaskType.DEFINITION),
            ("Explain how DNA replication occurs for a Class 12 student.", TaskType.PROCESS_EXPLANATION),
            ("What are the steps of glycolysis?", TaskType.PROCESS_EXPLANATION),
            ("Difference between mitosis and meiosis", TaskType.COMPARISON),
            ("Compare xylem and phloem", TaskType.COMPARISON),
            ("Calculate the allele frequency if 16% of the population is recessive.", TaskType.NUMERICAL),
            ("Is it true that we only use 10% of our brain?", TaskType.MISCONCEPTION_CORRECTION),
            ("Summarise this paper by Smith et al on CRISPR delivery.", TaskType.RESEARCH_PAPER),
            ("Write a 5 marks answer on photosynthesis.", TaskType.EXAM_ANSWER),
            ("Make a quiz on cell organelles", TaskType.QUIZ_GENERATION),
            ("Give me revision notes for genetics", TaskType.REVISION),
            ("Hello", TaskType.CONVERSATIONAL),
        ]
        for query, expected in cases:
            with self.subTest(query=query):
                self.assert_task(query, expected)

    def test_classification_reports_its_evidence(self) -> None:
        route = self.router.route("What are the stages of meiosis?")
        self.assertTrue(route.task_type.matched)
        self.assertEqual(route.task_type.source, "rules")
        self.assertGreater(route.task_type.confidence, 0.0)


class SubdomainRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = QueryRouter()

    def test_subdomain_labels(self) -> None:
        cases = [
            ("How does the Golgi apparatus modify proteins?", Subdomain.CELL_BIOLOGY),
            ("Explain the role of helicase in DNA replication", Subdomain.MOLECULAR_BIOLOGY),
            ("What is a Punnett square used for?", Subdomain.GENETICS),
            ("How does gram staining distinguish bacteria?", Subdomain.MICROBIOLOGY),
            ("Explain transpiration through stomata", Subdomain.BOTANY),
            ("What is a trophic level in a food web?", Subdomain.ECOLOGY),
            ("How does natural selection drive speciation?", Subdomain.EVOLUTION),
            ("Explain how antibodies recognise antigens", Subdomain.IMMUNOLOGY),
            ("Describe the electron transport chain", Subdomain.BIOCHEMISTRY),
            ("How does CRISPR editing work?", Subdomain.BIOTECHNOLOGY),
            ("What triggers an action potential in a neuron?", Subdomain.NEUROSCIENCE),
            ("Explain sequence alignment with BLAST", Subdomain.BIOINFORMATICS),
        ]
        for query, expected in cases:
            with self.subTest(query=query):
                route = self.router.route(query)
                self.assertEqual(
                    route.subdomain.label,
                    expected,
                    f"{query!r} routed to {route.subdomain.label}",
                )

    def test_unknown_topic_falls_back_to_general_biology(self) -> None:
        route = self.router.route("Tell me something interesting")
        self.assertEqual(route.subdomain.label, Subdomain.GENERAL_BIOLOGY)
        self.assertLess(route.subdomain.confidence, 0.35)


class LearnerLevelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = QueryRouter()

    def test_explicit_level_wins_and_is_recorded(self) -> None:
        route = self.router.route("Explain osmosis", learner_level="undergraduate")
        self.assertEqual(route.learner_level.label, LearnerLevel.UNDERGRADUATE)
        self.assertEqual(route.learner_level.confidence, 1.0)
        self.assertEqual(route.learner_level.source, "user")
        self.assertIn("learner_level", route.explicit_overrides)

    def test_stated_class_is_detected(self) -> None:
        cases = [
            ("Explain DNA replication for a Class 12 student", LearnerLevel.SENIOR_SECONDARY),
            ("Explain photosynthesis for class 7", LearnerLevel.MIDDLE_SCHOOL),
            ("Explain enzymes at BSc level", LearnerLevel.UNDERGRADUATE),
            ("Explain this for my PhD thesis introduction", LearnerLevel.RESEARCH),
        ]
        for query, expected in cases:
            with self.subTest(query=query):
                self.assertEqual(self.router.route(query).learner_level.label, expected)

    def test_advanced_vocabulary_lifts_inferred_level(self) -> None:
        route = self.router.route(
            "How does allosteric regulation alter enzyme kinetics in vivo?"
        )
        self.assertIn(
            route.learner_level.label,
            {LearnerLevel.UNDERGRADUATE, LearnerLevel.RESEARCH},
        )
        self.assertEqual(route.learner_level.source, "vocabulary")

    def test_simple_request_is_treated_as_general_public(self) -> None:
        route = self.router.route("Explain mitochondria in simple terms please")
        self.assertEqual(route.learner_level.label, LearnerLevel.GENERAL_PUBLIC)


class TeachingModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = QueryRouter()

    def test_modes(self) -> None:
        cases = [
            ("Don't give me the answer, just hint at how meiosis works", TeachingMode.SOCRATIC),
            ("Here's what I think photosynthesis is, check my understanding", TeachingMode.TEACH_BACK),
            ("Write a 5 marks answer on the nitrogen cycle", TeachingMode.EXAM),
            ("Give me flashcards for the Krebs cycle", TeachingMode.REVISION),
            ("This is for my homework on osmosis", TeachingMode.HOMEWORK_SUPPORT),
            ("Just tell me what ATP stands for", TeachingMode.DIRECT_ANSWER),
        ]
        for query, expected in cases:
            with self.subTest(query=query):
                self.assertEqual(self.router.route(query).teaching_mode.label, expected)

    def test_research_level_upgrades_default_mode(self) -> None:
        route = self.router.route("Explain chromatin remodelling", learner_level="research")
        self.assertEqual(route.teaching_mode.label, TeachingMode.RESEARCH)


class ContextLevelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = QueryRouter()

    def test_small_talk_skips_retrieval(self) -> None:
        route = self.router.route("hello")
        self.assertEqual(route.context_level, 0)
        self.assertFalse(route.needs_retrieval)
        self.assertEqual(route.retrieve_k, 0)

    def test_definition_uses_level_one(self) -> None:
        route = self.router.route("Define osmosis.")
        self.assertEqual(route.context_level, 1)
        self.assertEqual(route.retrieve_k, CONTEXT_LEVEL_POLICY[1]["retrieve"])
        self.assertEqual(route.rerank_k, CONTEXT_LEVEL_POLICY[1]["rerank"])

    def test_process_explanation_uses_level_two(self) -> None:
        self.assertEqual(self.router.route("How does glycolysis work?").context_level, 2)

    def test_deep_markers_escalate(self) -> None:
        route = self.router.route(
            "Critically evaluate the conflicting evidence on gut microbiome effects on immunity"
        )
        self.assertEqual(route.context_level, 4)
        self.assertEqual(route.max_revisions, 2)

    def test_young_learners_are_capped(self) -> None:
        route = self.router.route(
            "Critically evaluate photosynthesis models", learner_level="elementary"
        )
        self.assertLessEqual(route.context_level, 2)

    def test_explicit_context_level_is_honoured(self) -> None:
        route = self.router.route("Define osmosis.", context_level=4)
        self.assertEqual(route.context_level, 4)
        self.assertIn("context_level", route.explicit_overrides)


class VerificationFlagTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = QueryRouter()

    def test_process_verification_flag(self) -> None:
        self.assertTrue(self.router.route("Explain meiosis").needs_process_verification)
        self.assertFalse(self.router.route("Define an allele").needs_process_verification)

    def test_numerical_verification_flag(self) -> None:
        route = self.router.route("Calculate the heterozygote frequency under Hardy-Weinberg")
        self.assertTrue(route.needs_numerical_verification)

    def test_ordered_process_extraction(self) -> None:
        self.assertEqual(
            ordered_processes_in("Compare DNA replication and transcription"),
            ("dna replication", "transcription"),
        )


class LLMFallbackTests(unittest.TestCase):
    def test_llm_only_consulted_when_rules_are_unsure(self) -> None:
        calls: list[str] = []

        class Recorder:
            def classify(self, query: str, question: str, labels: list[str]) -> dict[str, object]:
                calls.append(question)
                return {"label": str(TaskType.SUMMARY), "confidence": 0.9}

        router = QueryRouter(classifier=Recorder())
        confident = router.route("What is the difference between mitosis and meiosis?")
        self.assertEqual(confident.task_type.source, "rules")
        self.assertNotIn("task type", calls)

    def test_llm_result_is_used_when_rules_are_weak(self) -> None:
        class Stub:
            def classify(self, query: str, question: str, labels: list[str]) -> dict[str, object]:
                return {"label": str(TaskType.SUMMARY), "confidence": 0.9}

        router = QueryRouter(classifier=Stub())
        route = router.route("the thing about cells")
        self.assertEqual(route.task_type.label, TaskType.SUMMARY)
        self.assertEqual(route.task_type.source, "llm")

    def test_invalid_llm_label_is_ignored(self) -> None:
        class Bad:
            def classify(self, query: str, question: str, labels: list[str]) -> dict[str, object]:
                return {"label": "not_a_label", "confidence": 0.99}

        router = QueryRouter(classifier=Bad())
        route = router.route("the thing about cells")
        self.assertEqual(route.task_type.source, "fallback")

    def test_classifier_failure_does_not_break_routing(self) -> None:
        class Broken:
            def classify(self, query: str, question: str, labels: list[str]) -> dict[str, object]:
                raise RuntimeError("model unavailable")

        route = QueryRouter(classifier=Broken()).route("the thing about cells")
        self.assertEqual(route.task_type.label, TaskType.CONCEPT_EXPLANATION)


class SupersedingClassifierTests(unittest.TestCase):
    """A classifier that has measured itself against the rules may overrule them.

    Without this, a *confidently wrong* rule is unreachable. That is not
    hypothetical: the trained task-type router scored 0.723 balanced accuracy
    on held-out questions against the rules' 0.606, and the pipeline showed
    exactly 0.606 either way, because the rules were confident enough that the
    classifier was never asked.
    """

    class Measured:
        """Reports itself better than the rules on task type only."""

        def __init__(self, label: object = TaskType.SUMMARY, confidence: float = 0.1) -> None:
            self.label, self.confidence = label, confidence
            self.asked: list[str] = []

        def supersedes(self, dimension: str) -> bool:
            return dimension == "task type"

        def classify(self, query: str, question: str, labels: list[str]) -> dict[str, object]:
            self.asked.append(question)
            return {"label": str(self.label), "confidence": self.confidence}

    CONFIDENT = "What is the difference between mitosis and meiosis?"

    def test_superseding_classifier_overrules_a_confident_rule(self) -> None:
        clf = self.Measured()
        route = QueryRouter(classifier=clf).route(self.CONFIDENT)
        self.assertIn("task type", clf.asked)
        self.assertEqual(route.task_type.label, TaskType.SUMMARY)
        self.assertEqual(route.task_type.source, "llm")

    def test_low_reported_confidence_does_not_veto_a_superseding_model(self) -> None:
        """The old gate discarded any answer that lost the confidence contest.

        A six-class model's posterior sits near 0.167 even when its argmax is
        right, so comparing it against a rule's hand-set number threw away
        correct predictions. A model that has measured itself is not
        second-guessed by that proxy.
        """

        clf = self.Measured(confidence=0.01)
        route = QueryRouter(classifier=clf).route(self.CONFIDENT)
        self.assertEqual(route.task_type.label, TaskType.SUMMARY)

    def test_dimensions_it_does_not_claim_keep_rules_first(self) -> None:
        clf = self.Measured()
        route = QueryRouter(classifier=clf).route(self.CONFIDENT)
        self.assertNotIn("biology subdomain", clf.asked)
        self.assertEqual(route.subdomain.source, "rules")

    def test_an_explicitly_declared_level_is_never_superseded(self) -> None:
        class All(self.Measured):
            def supersedes(self, dimension: str) -> bool:
                return True

        clf = All(label=LearnerLevel.RESEARCH, confidence=0.95)
        route = QueryRouter(classifier=clf).route(self.CONFIDENT, learner_level="elementary")
        self.assertEqual(route.learner_level.label, LearnerLevel.ELEMENTARY)
        self.assertEqual(route.learner_level.source, "user")
        self.assertNotIn("learner level", clf.asked)

    def test_a_classifier_without_the_method_keeps_the_old_contract(self) -> None:
        """The LLM classifier has never been scored, so nothing changes for it."""

        class Unmeasured:
            def __init__(self) -> None:
                self.asked: list[str] = []

            def classify(self, query: str, question: str, labels: list[str]) -> dict[str, object]:
                self.asked.append(question)
                return {"label": str(TaskType.SUMMARY), "confidence": 0.99}

        clf = Unmeasured()
        route = QueryRouter(classifier=clf).route(self.CONFIDENT)
        self.assertNotIn("task type", clf.asked)
        self.assertEqual(route.task_type.source, "rules")

    def test_invalid_label_still_falls_back_even_when_superseding(self) -> None:
        clf = self.Measured(label="not_a_label", confidence=0.99)
        route = QueryRouter(classifier=clf).route(self.CONFIDENT)
        self.assertEqual(route.task_type.source, "rules")


class SupersedeMarginTests(unittest.TestCase):
    def test_a_model_only_supersedes_when_it_clearly_beats_the_rules(self) -> None:
        from aura_bio.routing.encoder_router import RouterModel

        def model(cv: float, rules: float) -> RouterModel:
            return RouterModel("task type", None, (), (), cv_score=cv, rule_score=rules)

        self.assertTrue(model(0.79, 0.45).supersedes_rules)
        # Both numbers are cross-validated on ~390 questions; a point or two
        # apart is noise and must not hand the dimension over.
        self.assertFalse(model(0.47, 0.45).supersedes_rules)
        self.assertFalse(model(0.40, 0.45).supersedes_rules)

    def test_an_unmeasured_model_does_not_supersede(self) -> None:
        """A model saved before rule_score existed must not claim a dimension.

        Defaulting the missing value to 0.0 would make every such model look
        like it had beaten rules that score nothing, silently handing it
        dimensions it was never compared on.
        """

        from aura_bio.routing.encoder_router import RouterModel

        unmeasured = RouterModel("task type", None, (), (), cv_score=0.79, rule_score=None)
        self.assertFalse(unmeasured.supersedes_rules)


class RouteSerialisationTests(unittest.TestCase):
    def test_summary_matches_srs_shape(self) -> None:
        route = QueryRouter().route("Explain how DNA replication occurs for a Class 12 student.")
        summary = route.summary()
        self.assertEqual(
            set(summary),
            {
                "domain",
                "subdomain",
                "task_type",
                "learner_level",
                "teaching_mode",
                "context_level",
                "needs_retrieval",
                "needs_process_verification",
            },
        )
        self.assertEqual(summary["domain"], "biology")
        self.assertEqual(summary["subdomain"], Subdomain.MOLECULAR_BIOLOGY)
        self.assertEqual(summary["task_type"], TaskType.PROCESS_EXPLANATION)
        self.assertEqual(summary["learner_level"], LearnerLevel.SENIOR_SECONDARY)
        self.assertTrue(summary["needs_process_verification"])

    def test_full_dict_is_json_safe(self) -> None:
        import json

        route = QueryRouter().route("Compare mitosis and meiosis")
        json.dumps(route.as_dict())


if __name__ == "__main__":
    unittest.main()
