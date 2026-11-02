from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import secrets
import time

from .env import RealRunEnv, atomic_json


def action_timeout(runtime, policy, override=None):
    maximum = 3600 if runtime.get('combat_search_mode') == 'settings' else 300
    default = min(1800, maximum) if policy == 'model' else 60
    value = override if override is not None else runtime.get('action_timeout_seconds', default)
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f'action_timeout_seconds must be an integer in 1..{maximum}')
    return value


def main():
    parser = argparse.ArgumentParser(description="Run the real-game M1 environment in a dedicated runtime")
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--episodes", type=int, default=1)
    seeds = parser.add_mutually_exclusive_group()
    seeds.add_argument("--seed", help="Exact shared game seed (one episode)")
    seeds.add_argument("--seed-prefix", help="Legacy deterministic batch prefix; episode index is appended")
    parser.add_argument("--policy-seed", type=int, default=0)
    parser.add_argument("--timeout", type=int, help="Whole-run deadline; default 1h for evaluation, 4h with player search settings")
    parser.add_argument("--action-timeout", type=int, help="Seconds to wait for each policy decision; overrides runtime action_timeout_seconds")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--policy", choices=['model', 'random-map'], default='model')
    parser.add_argument("--policy-config", type=Path)
    args = parser.parse_args()
    if args.episodes < 1:
        parser.error("episodes must be positive")
    if args.seed is not None and args.episodes != 1:
        parser.error("--seed requires --episodes 1")
    args.output.mkdir(parents=True, exist_ok=True)
    runtime = json.loads(args.runtime.read_text(encoding="utf-8"))
    timeout = args.timeout if args.timeout is not None else runtime.get('timeout_seconds',
        14400 if runtime.get('combat_search_mode') == 'settings' else 3600)
    decision_timeout = action_timeout(runtime, args.policy, args.action_timeout)
    started = time.time()
    episodes = []
    bot = None
    if args.policy == 'model':
        import torch
        from .policy import BotPolicy
        from .policy_config import load_policy_config
        bot = BotPolicy(config=load_policy_config(args.policy_config))
        torch.set_num_threads(bot.reward_config['cpu_threads'])
        atomic_json(args.output / 'policy-config.json', bot.config)
        atomic_json(args.output / 'reward-config.json', bot.reward_config)
    with RealRunEnv(runtime) as env:
        for index in range(args.episodes):
            seed = args.seed if args.seed is not None else (f"{args.seed_prefix}{index}" if args.seed_prefix is not None
                else ''.join(secrets.choice('0123456789ABCDEFGHJKLMNPQRSTUVWXYZ') for _ in range(12)))
            seed = seed.upper().replace('O', '0').replace('I', '1').strip()
            policy = random.Random(args.policy_seed + index)
            try:
                observation = env.reset(seed, policy_seed=args.policy_seed + index, timeout_seconds=timeout,
                                        decision_mode='all' if bot else 'map', action_timeout_seconds=decision_timeout)
                print(json.dumps(dict(runId=env.run_id, seed=seed, character='SILENT', ascension=10,
                    startingAct=observation.get('state', {}).get('actId')), ensure_ascii=False), flush=True)
                while observation.get("status") != "complete":
                    print(json.dumps({"runId": env.run_id, "decisionSeq": observation["decisionSeq"],
                                      "screen": observation.get("screen"), "actionTimeoutSeconds": decision_timeout,
                                      "state": {k: observation["state"][k] for k in ["act", "floor", "hp", "gold"]}}), flush=True)
                    decision_started = time.monotonic()
                    choice = bot.choose(observation) if bot else policy.randrange(len(observation['options']))
                    print(json.dumps({"runId": env.run_id, "decisionSeq": observation["decisionSeq"],
                                      "choice": choice, "policyElapsedSeconds": round(time.monotonic() - decision_started, 3)}), flush=True)
                    if bot:
                        with (args.output / 'decisions.jsonl').open('a', encoding='utf-8') as log:
                            log.write(json.dumps(dict(runId=env.run_id, seed=seed, **bot.last_report), ensure_ascii=False, allow_nan=False)+'\n')
                    observation = env.step(choice)
                episodes.append(dict(observation, seed=seed, artifactDirectory=str(env.run_dir)))
                atomic_json(args.output / "summary.json", dict(started=started, elapsed=time.time()-started,
                            completed=len(episodes), episodes=episodes))
                print(json.dumps(observation), flush=True)
            except Exception as exc:
                # A failed experiment remains failed, not a fabricated loss or
                # a silently replaced seed. A later invocation can retry explicitly.
                atomic_json(args.output / "failure.json", dict(runId=env.run_id, seed=seed,
                            completed=len(episodes), error=repr(exc), artifactDirectory=str(env.run_dir)))
                raise


if __name__ == "__main__":
    main()
