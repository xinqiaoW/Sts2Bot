"""Combat oracles: map ``(build, encounter, hp)`` to an HP outcome.

* ``ModelOracle`` uses the trained expected-HP-loss checkpoints (``train.predict``).
  Several checkpoints form an ensemble; the member spread is available as a
  pessimism penalty (``loss = mean + pessimism * std``) so that a learner cannot
  exploit spots where the members disagree. Optional Gaussian noise breaks the
  determinism of a mean-only oracle.
* ``EmpiricalOracle`` samples the human ``damage_taken`` histogram of the
  encounter. It ignores the build, so it is only a reference for calibration.

``F`` was trained at 70/70 with the loss normalised by max HP, and max HP never
varied in the training data, so the oracle always queries it with
``F_BASE_MAX_HP`` and treats the output as an absolute HP loss.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from damage_model.schema import Build

F_BASE_MAX_HP = 70


@dataclass
class CombatRequest:
    build: Build
    target: str
    hp: int
    max_hp: int
    room_type: str


@dataclass
class CombatResult:
    hp_loss: int
    died: bool
    expected_loss: float | None = None
    death_probability: float | None = None
    spread: float | None = None
    untrained: int = 0


class CombatOracle:
    name = 'base'

    def resolve(self, requests: list[CombatRequest]) -> list[CombatResult]:
        raise NotImplementedError


class EmpiricalOracle(CombatOracle):
    """Human damage histograms per encounter (build-independent)."""
    name = 'empirical'

    def __init__(self, human_damage: dict, seed=0):
        self.rng = np.random.default_rng(seed)
        self.tables = {}
        for enc, hist in human_damage.items():
            values = np.array([int(k) for k in hist], dtype=float)
            counts = np.array([v for v in hist.values()], dtype=float)
            self.tables[enc] = (values, counts / counts.sum())

    def resolve(self, requests):
        out = []
        for req in requests:
            values, probs = self.tables.get(req.target, (np.array([0.0]), np.array([1.0])))
            loss = int(self.rng.choice(values, p=probs))
            out.append(CombatResult(hp_loss=loss, died=req.hp - loss <= 0, expected_loss=float((values * probs).sum())))
        return out


class ModelOracle(CombatOracle):
    name = 'model'

    def __init__(self, checkpoints, device='cpu', pessimism=0.0, noise_sd=0.0, use_death_head=True,
                 seed=0, batch_size=2048):
        from train.predict import Predictor
        self.predictors = [Predictor(path, device) for path in checkpoints]
        self.pessimism, self.noise_sd, self.use_death_head = pessimism, noise_sd, use_death_head
        self.rng = np.random.default_rng(seed)
        self.batch_size = batch_size
        self.trained_targets = set.intersection(*(p.trained_targets for p in self.predictors))

    def covers(self, act_id, target):
        return f'{act_id}:{target}' in self.trained_targets

    @staticmethod
    def _strip_stateful(build: Build) -> Build:
        """Drop cards with saved state (Mad Science, quest cards, Guilty) whose exact
        state key the sparse vocabulary never saw; they are rare and matter little."""
        from damage_model.card_state import DEFAULTS
        return Build(build.act_id, build.act, tuple(c for c in build.cards if c.id not in DEFAULTS),
                     build.relics, build.ancient_history, family=build.family)

    def _predict_member(self, predictor, inputs):
        try:
            return predictor.predict_many(inputs, batch_size=self.batch_size)
        except ValueError:
            pass
        results = []
        for item in inputs:
            try:
                results.extend(predictor.predict_many([item]))
            except ValueError:
                build, target, max_hp = item
                results.extend(predictor.predict_many([(self._strip_stateful(build), target, max_hp)]))
        return results

    def predict(self, requests):
        """Return ``(mean_loss_hp, std_loss_hp, death_probability, untrained_count)`` arrays."""
        inputs = [(r.build, r.target, F_BASE_MAX_HP) for r in requests]
        member_loss, member_death, untrained = [], [], np.zeros(len(requests), dtype=int)
        for predictor in self.predictors:
            results = self._predict_member(predictor, inputs)
            member_loss.append([r['normalized_expected_hp_loss'] * F_BASE_MAX_HP for r in results])
            member_death.append([r['death_probability'] for r in results])
            untrained += np.array([len(r['untrained_features']) for r in results])
        loss = np.asarray(member_loss)
        return loss.mean(0), loss.std(0) if len(self.predictors) > 1 else np.zeros(len(requests)), \
            np.asarray(member_death).mean(0), untrained

    def resolve(self, requests):
        if not requests:
            return []
        mean, std, death, untrained = self.predict(requests)
        out = []
        for i, req in enumerate(requests):
            loss = mean[i] + self.pessimism * std[i]
            if self.noise_sd > 0:
                loss += self.rng.normal(0.0, self.noise_sd)
            loss = int(round(max(0.0, loss)))
            died = req.hp - loss <= 0
            if self.use_death_head and not died and self.rng.random() < death[i]:
                died, loss = True, req.hp
            out.append(CombatResult(hp_loss=min(loss, req.hp), died=died, expected_loss=float(mean[i]),
                                    death_probability=float(death[i]), spread=float(std[i]), untrained=int(untrained[i])))
        return out
