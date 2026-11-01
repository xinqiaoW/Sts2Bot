"""Fixed short-search boss setup and ordinary lethal sentinel in an isolated runtime."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runctl.env import RealRunEnv, atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--dll', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    runtime = json.loads(args.runtime.read_text())
    runtime['log_path'] = str(args.output.resolve() / 'native.log')
    cases = [
        dict(name='boss-setup', encounterId='VANTOM_BOSS', enemyCurrentHp=150,
             initialPlayerEnergy=3, cards=[dict(cardId='FOOTWORK', pile='Hand'),
                 dict(cardId='NOXIOUS_FUMES', pile='Hand'), dict(cardId='STRIKE_SILENT', pile='Hand', count=2),
                 dict(cardId='DEFEND_SILENT', pile='Hand', count=2),
                 dict(cardId='STRIKE_SILENT', pile='Draw', count=3), dict(cardId='DEFEND_SILENT', pile='Draw', count=3)]),
        dict(name='ordinary-lethal', encounterId='FUZZY_WURM_CRAWLER_WEAK', enemyCurrentHp=12,
             initialPlayerEnergy=2, expectedInitialProjectedBattleHpLost=0, expectedInitialCombatEndedTurn=1,
             expectedInitialAbsentActionCardId='FOOTWORK',
             cards=[dict(cardId='FOOTWORK', pile='Hand'), dict(cardId='STRIKE_SILENT', pile='Hand', count=2)]),
    ]
    with RealRunEnv(runtime) as env:
        target = Path(runtime['game_dir']) / 'mods/CombatSolver'
        shutil.copy2(args.dll, target / 'CombatSolver.dll')
        shutil.copy2(ROOT / 'vendor/CombatSolver/CombatSolver.json', target / 'CombatSolver.json')
        for case in cases:
            name = case.pop('name')
            request = dict(schemaVersion=1, runId=uuid.uuid4().hex, scenarioId='BOSS-SETUP-' + name,
                characterId='SILENT', seed='BOSSSETUP0305', ascension=10, initialPlayerHp=70,
                initialPlayerMaxHp=70, clearPlayerPiles=True, clearRunDeck=True,
                forceShortSearchOnly=True, shortSearchBudgetOverrideMilliseconds=2000,
                searchMaxDegreeOfParallelismForTest=1, performancePresetForTest='Low',
                potionPolicyForTest='Disabled', enableNoGcRegionForTest=False,
                expectedInitialSearchPhase='Short', expectedInitialDeepSearchTriggered=False,
                stopAfterInitialSolverResultAssertion=True, timeoutSeconds=120, exitOnComplete=False, **case)
            atomic_json(args.output / (name + '-request.json'), request)
            result = env.game.run(request)
            atomic_json(args.output / (name + '-result.json'), result)
            print(json.dumps(dict(case=name, status=result['status'], metrics=result.get('solverMetrics'),
                                  error=result.get('error')), ensure_ascii=False), flush=True)
            if result['status'] != 'Passed':
                raise RuntimeError(f'{name} failed; retained full result and native.log')


if __name__ == '__main__':
    main()
