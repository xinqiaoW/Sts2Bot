"""Full-health encounter loss and weighted build scoring using a trained model."""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import replace
from pathlib import Path

from damage_model.schema import Build
from . import ROOT
from .data import load_catalog
from .predict import Predictor

DEFAULT_CHECKPOINT = ROOT / 'checkpoints/train/selected'
ASSUMPTIONS = 'SILENT, A10, full HP at combat start, no potions, 8s solver; net HP loss'


class BuildScorer:
    """Load once and reuse. score = negative expected HP loss (higher is better).

    Compare builds with the same encounter weights. A weighted average is a
    one-encounter expectation, not the accumulated damage of a route.
    """

    def __init__(self, checkpoint=DEFAULT_CHECKPOINT, device='cpu'):
        self.predictor = Predictor(checkpoint, device)
        self.catalog = load_catalog()

    def score_many(self, requests, *, strict=False):
        inputs, groups = [], []
        for item in requests:
            # Current HP is deliberately unsupported: the training starts full.
            if 'current_hp' in item or 'hp' in item:
                raise ValueError('Current HP is unsupported; this model assumes full-health combat')
            build = Build.from_dict(item['build'])
            self.catalog.validate(build)
            encounter_act_id = item.get('encounter_act_id', build.act_id)
            if encounter_act_id not in self.catalog.acts:
                raise ValueError('Unknown encounter act')
            encounter_act = self.catalog.acts[encounter_act_id]['act']
            if encounter_act_id != build.act_id and encounter_act != build.act + 1:
                raise ValueError('Encounter projection must be the current or next act')
            # Validate the real owned build first. This inference-only context
            # changes target/act features, never invents the next Ancient reward.
            projected = replace(build, act_id=encounter_act_id, act=encounter_act)
            hp = item['max_hp']
            if isinstance(hp, bool) or not isinstance(hp, (int, float)) or not math.isfinite(hp) or hp <= 0:
                raise ValueError('max_hp must be finite and positive')
            if ('target' in item) == ('targets' in item):
                raise ValueError('Provide exactly one of target or targets (encounter -> weight)')
            weights = {item['target']: 1.0} if 'target' in item else item['targets']
            if not isinstance(weights, dict) or not weights:
                raise ValueError('targets must be a nonempty encounter -> positive weight mapping')
            if any(isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or w <= 0 for w in weights.values()):
                raise ValueError('Encounter weights must be finite and positive')
            total = sum(weights.values())
            if not math.isfinite(total):
                raise ValueError('Encounter weight sum must be finite')
            start = len(inputs)
            inputs.extend((projected, target, hp) for target in weights)
            groups.append((item, build, encounter_act_id, start, {t: w / total for t, w in weights.items()}))
        if not inputs:
            return []
        predictions = self.predictor.predict_many(inputs, strict=strict)
        output = []
        for item, build, encounter_act_id, start, weights in groups:
            encounters = [dict(target=t, weight=w, **p) for (t, w), p in
                          zip(weights.items(), predictions[start:start + len(weights)])]
            loss = sum(p['weight'] * p['expected_hp_loss'] for p in encounters)
            warnings = [] if item['max_hp'] == 70 else ['Training uses max_hp=70; other values are numeric extrapolation']
            if encounter_act_id != build.act_id:
                warnings.append('cross_act_projection_without_future_rewards')
            output.append(dict(id=item.get('id', build.id), build_id=build.id, act_id=build.act_id,
                               encounter_act_id=encounter_act_id,
                               max_hp=item['max_hp'], expected_hp_loss=loss, score=-loss,
                               death_probability=sum(p['weight'] * p['death_probability'] for p in encounters),
                               untrained_features=sorted({k for p in encounters for k in p['untrained_features']}),
                               warnings=warnings,
                               assumptions=ASSUMPTIONS, encounters=encounters))
        return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, help='JSONL: {id, build, max_hp, target or targets}')
    parser.add_argument('--output', help='Output JSONL; defaults to stdout')
    parser.add_argument('--checkpoint', default=str(DEFAULT_CHECKPOINT))
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--strict', action='store_true')
    args = parser.parse_args()
    items = [json.loads(line) for line in Path(args.input).read_text().splitlines() if line.strip()]
    results = BuildScorer(args.checkpoint, args.device).score_many(items, strict=args.strict)
    data = ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in results)
    if args.output:
        Path(args.output).write_text(data, encoding='utf-8')
    else:
        print(data, end='')


if __name__ == '__main__':
    main()
