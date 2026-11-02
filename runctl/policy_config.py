"""All tunable whole-run policy values; configuration is logged per episode."""
import json
import math
import warnings
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / 'configs/bot-policy.json'


def load_policy_config(path=None, **overrides):
    values = json.loads(DEFAULT_CONFIG.read_text())
    supplied = json.loads(Path(path).read_text()) if path else {}
    supplied.update(overrides)
    if 'crisis_boss_loss_fraction' in supplied:
        supplied.pop('crisis_boss_loss_fraction')
        warnings.warn('crisis_boss_loss_fraction is obsolete and ignored; use crisis_boss_loss_threshold in HP.',
                      UserWarning, stacklevel=2)
    if supplied.keys() - values.keys():
        raise ValueError(f'Unknown bot configuration: {sorted(supplied.keys() - values.keys())}')
    values.update(supplied)
    integer_keys = {'crisis_samples_per_parent', 'crisis_keep_per_parent', 'crisis_extra_depth',
                    'max_rollout_depth', 'reward_rollout_depth', 'post_boss_rollout_depth', 'route_beam_width', 'seed',
                    'samples_per_parent', 'keep_per_parent', 'lookahead_pairs', 'boss_target_after_act_floor'}
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f'{key} must be finite and nonnegative')
        if key in integer_keys and type(value) is not int:
            raise ValueError(f'{key} must be an integer')
    for prefix in ('', 'weak_'):
        total = values[prefix+'short_weight'] + values[prefix+'long_weight']
        if not math.isfinite(total) or total <= 0:
            raise ValueError('Score weights must have finite positive total')
    total_tail_weight = values['leaf_top_weight'] + values['leaf_bottom_weight']
    if not math.isfinite(total_tail_weight) or total_tail_weight <= 0:
        raise ValueError('Tail weights must have finite positive total')
    for key in ['rest_hp_fraction', 'unknown_combat_probability', 'leaf_top_fraction', 'leaf_bottom_fraction']:
        if not 0 < values[key] <= 1:
            raise ValueError(f'{key} must be in (0,1]')
    if not 0 <= values['max_rollout_depth'] <= 4:
        raise ValueError('max_rollout_depth must be in [0,4]')
    if values['reward_rollout_depth'] not in (3, 4, 5):
        raise ValueError('reward_rollout_depth must be 3, 4 or 5')
    if not 0 <= values['post_boss_rollout_depth'] <= 6:
        raise ValueError('post_boss_rollout_depth must be in [0,6]')
    if values['reward_rollout_depth'] + values['crisis_extra_depth'] > 6:
        raise ValueError('Reward crisis rollout depth must not exceed 6')
    if not 1 <= values['crisis_keep_per_parent'] <= values['crisis_samples_per_parent'] + 1:
        raise ValueError('Invalid crisis branching parameters')
    if values['samples_per_parent'] < 1 or not 1 <= values['keep_per_parent'] <= values['samples_per_parent'] + 1:
        raise ValueError('Invalid normal branching parameters')
    if not 0 <= values['lookahead_pairs'] <= 3:
        raise ValueError('lookahead_pairs must be in [0,3]')
    if values['route_beam_width'] < 1:
        raise ValueError('route_beam_width must be positive')
    return values


def choose_card_with_margin(scores, skip_index, *, crisis, config):
    """Scores keyed by actual legal option index, never a fabricated skip.

    The user's rule is strict: equality with skip + margin still skips.
    Forced selections have no skip index and must choose a legal card.
    """
    if not scores or any(not math.isfinite(value) for value in scores.values()):
        raise ValueError('Card scores must be nonempty and finite')
    best = max(scores, key=lambda i: (scores[i], i == skip_index, -i))
    if skip_index is not None:
        if skip_index not in scores:
            raise ValueError('Skip must be a scored legal option')
        margin = config['crisis_card_min_gain'] if crisis else config['normal_card_min_gain']
        if scores[best] <= scores[skip_index] + margin:
            return skip_index
    return best
