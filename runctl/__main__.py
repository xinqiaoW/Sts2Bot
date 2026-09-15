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
    args = parser.parse_args()
    if args.episodes < 1:
        parser.error("episodes must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    runtime = json.loads(args.runtime.read_text(encoding="utf-8"))
    started = time.time()
    episodes = []
    with RealRunEnv(runtime) as env:
        for index in range(args.episodes):
            seed = f"{args.seed_prefix}{index}"
            policy = random.Random(args.policy_seed + index)
            try:
                observation = env.reset(seed, policy_seed=args.policy_seed + index, timeout_seconds=args.timeout)
                while observation.get("status") != "complete":
                    print(json.dumps({"runId": env.run_id, "decisionSeq": observation["decisionSeq"],
                                      "state": {k: observation["state"][k] for k in ["act", "floor", "hp", "gold"]}}), flush=True)
                    observation = env.step(policy.randrange(len(observation["options"])))
                episodes.append(observation)
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
