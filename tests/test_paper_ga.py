import builtins
from dataclasses import replace
import random
import unittest
from unittest.mock import patch

from ananno_phase2.models import Box
from ananno_phase2.packer import PackingCancelled
from ananno_phase2.paper_config import PaperConfig
from ananno_phase2.paper_ga import TypeEvaluation, optimize_types


def small_config(**changes):
    return replace(PaperConfig(), population_size=12, mu=6, lambda_=10,
                   generations=8, max_stagnation=3, **changes)


def groups_fixture():
    # Independent rankings distinguish all five Table 5 properties.
    return {name: [Box(f"{name}{i}", length, width, height, weight, name)
                   for i in range(quantity)]
            for name, length, width, height, weight, quantity in
            [("A", 1, 1, 4, 5, 2), ("B", 2, 3, 1, 2, 4),
             ("C", 2, 2, 2, 9, 1), ("D", 3, 1, 1, 1, 3)]}


class PaperGATests(unittest.TestCase):
    def test_table5_seeds_use_type_properties_and_cache_duplicate_sequences(self):
        seen = []

        def evaluate(sequence):
            seen.append(tuple(sequence))
            return TypeEvaluation(True, 1, .4)

        config = replace(PaperConfig(), population_size=10, mu=5, lambda_=2,
                         generations=1, max_stagnation=1,
                         crossover_probability=0, mutation_probability=0)
        optimize_types(groups_fixture(), evaluate, config)
        self.assertEqual(seen, [tuple(s) for s in [
            "CABD", "DBAC", "BDAC", "CADB", "BCDA", "ADCB",
            "CBAD", "DABC", "ACDB"]])

    def test_infeasible_attractive_scores_are_penalized_and_payload_is_retained(self):
        payload = {"placements": ["A0", "B0"]}

        def evaluate(sequence):
            if sequence[0] == "A":
                return TypeEvaluation(True, 10, .1, payload)
            return TypeEvaluation(False, -100, 100, {"partial": True})

        groups = {"A": [Box("A0", 1, 1, 1)], "B": [Box("B0", 2, 1, 1)]}
        result = optimize_types(groups, evaluate, small_config())
        self.assertEqual(result.sequence, ["A", "B"])
        self.assertTrue(result.best.feasible)
        self.assertIs(result.best.payload, payload)

    def test_pareto_choice_prioritizes_compactness_over_heterogeneity(self):
        groups = {"A": [Box("A0", 1, 1, 1)], "B": [Box("B0", 2, 1, 1)]}
        result = optimize_types(groups, lambda s: TypeEvaluation(
            True, 3 if s[0] == "A" else 1, .8 if s[0] == "A" else .4), small_config())
        self.assertEqual(result.sequence, ["A", "B"])
        self.assertEqual(result.best.compactness, .8)

    def test_evolution_keeps_permutations_and_repeats_without_changing_global_rng(self):
        groups = groups_fixture()
        groups.update({name: [Box(name, 1, 1, 1)] for name in "EFGH"})

        def run():
            seen = []

            def evaluate(sequence):
                self.assertEqual(sorted(sequence), list("ABCDEFGH"))
                seen.append(tuple(sequence))
                compactness = sum((i + 1) * ord(gene) for i, gene in enumerate(sequence)) / 3000
                return TypeEvaluation(True, 2, compactness, tuple(sequence))

            config = replace(small_config(), crossover_probability=.7,
                             mutation_probability=.3)
            result = optimize_types(groups, evaluate, config)
            self.assertEqual(len(seen), len(set(seen)))
            self.assertGreater(len(seen), config.population_size)
            return result, seen

        before = random.getstate()
        first, first_seen = run()
        self.assertEqual(random.getstate(), before)
        second, second_seen = run()
        self.assertEqual(first, second)
        self.assertEqual(first_seen, second_seen)

    def test_all_infeasible_stops_after_configured_stagnation(self):
        calls = []
        result = optimize_types(groups_fixture(), lambda s: (
            calls.append(tuple(s)) or TypeEvaluation(False, 0, 1)), small_config())
        self.assertIsNone(result.best)
        self.assertEqual(result.sequence, [])
        self.assertEqual([row["generation"] for row in result.trace], [0, 1, 2, 3])
        self.assertTrue(all(row["feasible"] == 0 for row in result.trace))

    def test_empty_and_single_type_are_evaluated_once(self):
        for groups, expected in [({}, []), ({"A": [Box("A0", 1, 1, 1)]}, ["A"])]:
            with self.subTest(expected=expected):
                seen = []
                result = optimize_types(groups, lambda s: (
                    seen.append(s[:]) or TypeEvaluation(True, 0, .5)), small_config())
                self.assertEqual(seen, [expected])
                self.assertEqual(result.sequence, expected)
                self.assertTrue(result.best.feasible)

    def test_cancellation_during_evaluation_propagates(self):
        seen = []

        def evaluate(sequence):
            seen.append(sequence)
            return TypeEvaluation(True, 1, .5)

        with self.assertRaises(PackingCancelled):
            optimize_types(groups_fixture(), evaluate, small_config(), cancelled=lambda: bool(seen))
        self.assertEqual(len(seen), 1)

    def test_missing_deap_has_explicit_optional_dependency_error(self):
        original_import = builtins.__import__

        def without_deap(name, *args, **kwargs):
            if name == "deap":
                raise ImportError("not installed")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=without_deap):
            with self.assertRaisesRegex(RuntimeError, "DEAP"):
                optimize_types({}, lambda s: TypeEvaluation(True, 0, 0), small_config())

    def test_mu_one_and_single_initial_individual_do_not_require_two_parents(self):
        config = replace(PaperConfig(), population_size=1, mu=1, lambda_=2,
                         generations=2, max_stagnation=2,
                         crossover_probability=1, mutation_probability=0)
        result = optimize_types(groups_fixture(), lambda s: TypeEvaluation(True, 1, .5), config)
        self.assertEqual(sorted(result.sequence), list("ABCD"))
        self.assertEqual([row["population"] for row in result.trace], [1, 1, 1])

    def test_nonfinite_feasible_objectives_fail_before_nsga_selection(self):
        for heterogeneity, compactness in [(float("nan"), .4), (1, float("inf"))]:
            with self.subTest(heterogeneity=heterogeneity, compactness=compactness):
                with self.assertRaises(ValueError):
                    optimize_types(groups_fixture(), lambda s: TypeEvaluation(
                        True, heterogeneity, compactness), small_config())


if __name__ == "__main__":
    unittest.main()
