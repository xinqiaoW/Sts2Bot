from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import time

from .env import RealRunEnv, atomic_json


def main():
    parser = argparse.ArgumentParser(description="Run the real-game M1 environment in a dedicated runtime")
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument("--seed-prefix", default="RUNCTL")
    parser.add_argument("--policy-seed", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--policy", choices=['model', 'random-map'], default='model')
    parser.add_argument("--policy-config", type=Path)
    args = parser.parse_args()
    if args.episodes < 1:
        parser.error("episodes must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    runtime = json.loads(args.runtime.read_text(encoding="utf-8"))
    started = time.time()
    episodes = []
    bot = None
    if args.policy == 'model':
        import torch
        from .policy import BotPolicy
        from .policy_config import load_policy_config
        torch.set_num_threads(4)
        bot = BotPolicy(config=load_policy_config(args.policy_config))
        atomic_json(args.output / 'policy-config.json', bot.config)
    with RealRunEnv(runtime) as env:
        for index in range(args.episodes):
            seed = f"{args.seed_prefix}{index}"
            policy = random.Random(args.policy_seed + index)
            try:
                observation = env.reset(seed, policy_seed=args.policy_seed + index, timeout_seconds=args.timeout,
                                        decision_mode='all' if bot else 'map', action_timeout_seconds=300 if bot else 60)
                while observation.get("status") != "complete":
                    print(json.dumps({"runId": env.run_id, "decisionSeq": observation["decisionSeq"],
                                      "state": {k: observation["state"][k] for k in ["act", "floor", "hp", "gold"]}}), flush=True)
                    choice = bot.choose(observation) if bot else policy.randrange(len(observation['options']))
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
