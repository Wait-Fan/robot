"""Box-type GA from Ananno 2024, with an injected fixed-pallet evaluator.

This implements the paper's algorithm structure and Table 5 seeds, not a claim
of matching its experimental results. DEAP is optional until optimization runs.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Any, Callable

from .models import Box
from .packer import check_cancelled
from .paper_config import PaperConfig


@dataclass(frozen=True)
class TypeEvaluation:
    feasible: bool
    heterogeneity: float
    compactness: float
    payload: Any = None


@dataclass
class GAResult:
    best: TypeEvaluation | None
    sequence: list[str]
    trace: list[dict]


def _custom_sequences(groups: dict[str, list[Box]]) -> list[list[str]]:
    """Table 5's descending/ascending pairs; key ties use type names."""
    names = sorted(groups)
    metrics = (
        lambda name: groups[name][0].weight,
        lambda name: len(groups[name]),
        lambda name: groups[name][0].length * groups[name][0].width,
        lambda name: groups[name][0].volume,
        lambda name: groups[name][0].volume * len(groups[name]),
    )
    return [sorted(names, key=lambda name: (sign * metric(name), name))
            for metric in metrics for sign in (-1, 1)]


def _repair_permutation(sequence: list[str], genes: list[str]) -> None:
    """Replace duplicate occurrences in place with canonical missing genes."""
    missing = iter(name for name in genes if name not in sequence)
    seen = set()
    for index, name in enumerate(sequence):
        if name in seen:
            sequence[index] = next(missing)
        seen.add(sequence[index])


def optimize_types(
    groups: dict[str, list[Box]],
    evaluator: Callable[[list[str]], TypeEvaluation],
    config: PaperConfig,
    cancelled: Callable[[], bool] | None = None,
    log: Callable[[str], None] | None = None,
) -> GAResult:
    """Run DEAP μ+λ/NSGA-II and return the compactness-first Pareto choice.

    The evaluator must place *all* residual boxes with a fixed pallet count and
    set ``feasible=False`` if that fails. Adding pallets/restarting is the
    caller's responsibility. Identical type sequences are evaluated only once
    per run; passive evaluation/placement payload is retained with individuals.

    Variation follows DEAP's ``varOr`` scheme, using a private RNG rather than
    temporarily replacing process-global random state. The explicit evolution
    loop adds cancellation and the paper's infeasible-population stagnation.
    """
    check_cancelled(cancelled)
    try:
        from deap import base, tools
    except ImportError as exc:
        raise RuntimeError(
            "论文两阶段模式需要可选依赖 DEAP；请安装 requirements-ga.txt"
        ) from exc
    if any(not boxes for boxes in groups.values()):
        raise ValueError("箱型分组不能为空")

    genes = sorted(groups)
    rng = random.Random(config.seed)
    metadata = {
        name: {"quantity": len(boxes), "length": boxes[0].length,
               "width": boxes[0].width, "height": boxes[0].height,
               "weight": boxes[0].weight}
        for name, boxes in groups.items()
    }

    # Direct classes avoid process-global DEAP creator definitions and collisions
    # when the GUI starts another run or imports another optimization module.
    class TypeFitness(base.Fitness):
        weights = (-1.0, 1.0)

    class Individual(list):
        def __init__(self, sequence):
            super().__init__(sequence)
            self.fitness = TypeFitness()
            self.type_metadata = metadata
            self.evaluation: TypeEvaluation | None = None

        @property
        def payload(self):
            return self.evaluation.payload if self.evaluation is not None else None

        def __deepcopy__(self, memo):
            # DEAP archives deepcopy individuals; placements are passive and may
            # be large. Sharing the frozen evaluation preserves its exact payload.
            duplicate = clone(self)
            memo[id(self)] = duplicate
            return duplicate

    def clone(individual):
        duplicate = Individual(individual)
        if individual.fitness.valid:
            duplicate.fitness.values = individual.fitness.values
        duplicate.evaluation = individual.evaluation
        return duplicate

    def mate(first, second):
        if len(genes) >= 2:
            cut = rng.randrange(1, len(genes))
            first[cut:], second[cut:] = second[cut:], first[cut:]
            _repair_permutation(first, genes)
            _repair_permutation(second, genes)
        return first, second

    def mutate(individual):
        if len(genes) >= 2:
            first, second = rng.sample(range(len(genes)), 2)
            individual[first], individual[second] = individual[second], individual[first]
        return (individual,)

    toolbox = base.Toolbox()
    toolbox.register("clone", clone)
    toolbox.register("mate", mate)
    toolbox.register("mutate", mutate)
    toolbox.register("select", tools.selNSGA2)
    cache: dict[tuple[str, ...], TypeEvaluation] = {}

    def evaluate_invalid(population):
        evaluated = 0
        for individual in population:
            check_cancelled(cancelled)
            if individual.fitness.valid:
                continue
            key = tuple(individual)
            if key not in cache:
                evaluation = evaluator(list(individual))
                check_cancelled(cancelled)
                if not isinstance(evaluation, TypeEvaluation):
                    raise TypeError("GA evaluator 必须返回 TypeEvaluation")
                if evaluation.feasible and not all(math.isfinite(value) for value in (
                    evaluation.heterogeneity, evaluation.compactness
                )):
                    raise ValueError("可行个体的目标值必须为有限数值")
                cache[key] = evaluation
                evaluated += 1
            individual.evaluation = cache[key]
            evaluation = individual.evaluation
            individual.fitness.values = (
                (evaluation.heterogeneity, evaluation.compactness) if evaluation.feasible
                else (math.inf, -math.inf)
            )
        return evaluated

    population = [Individual(sequence) for sequence in _custom_sequences(groups)[:config.population_size]]
    while len(population) < config.population_size:
        population.append(Individual(rng.sample(genes, len(genes))))
    front = tools.ParetoFront()
    trace = []
    stagnant = 0

    def record(generation, evaluated):
        front.update(individual for individual in population if individual.evaluation.feasible)
        preferred = min(front, key=lambda item: (
            -item.evaluation.compactness, item.evaluation.heterogeneity, tuple(item)
        ), default=None)
        row = {"generation": generation, "evaluated": evaluated,
               "population": len(population),
               "feasible": sum(ind.evaluation.feasible for ind in population),
               "heterogeneity": preferred.evaluation.heterogeneity if preferred is not None else None,
               "compactness": preferred.evaluation.compactness if preferred is not None else None,
               "stagnation": stagnant}
        trace.append(row)
        if log:
            log(f"GA 第{generation}代：可行{row['feasible']}/{row['population']}，"
                f"新增评估{evaluated}，停滞{stagnant}")
        return frozenset(ind.fitness.values for ind in front), preferred

    signature, preferred = record(0, evaluate_invalid(population))
    for generation in range(1, config.generations + 1):
        check_cancelled(cancelled)
        offspring = []
        for _ in range(config.lambda_):
            check_cancelled(cancelled)
            operation = rng.random()
            if operation < config.crossover_probability:
                parents = (rng.sample(population, 2) if len(population) >= 2
                           else [population[0], population[0]])
                first, second = map(toolbox.clone, parents)
                child, _ = toolbox.mate(first, second)
                del child.fitness.values
                child.evaluation = None
            elif operation < config.crossover_probability + config.mutation_probability:
                child, = toolbox.mutate(toolbox.clone(rng.choice(population)))
                del child.fitness.values
                child.evaluation = None
            else:
                child = toolbox.clone(rng.choice(population))
            offspring.append(child)
        evaluated = evaluate_invalid(offspring)
        # Archive before environmental selection so an equally fit discarded
        # individual's coordinates remain available for the final Pareto choice.
        front.update(individual for individual in offspring if individual.evaluation.feasible)
        population = toolbox.select(population + offspring, config.mu)
        current = frozenset(ind.fitness.values for ind in front)
        stagnant = stagnant + 1 if current == signature else 0
        signature, preferred = record(generation, evaluated)
        if stagnant >= config.max_stagnation:
            break
    check_cancelled(cancelled)
    return GAResult(preferred.evaluation if preferred is not None else None,
                    list(preferred) if preferred is not None else [], trace)
