"""Create the local CombatSolver patch and model service packages once."""
from pathlib import Path
import argparse
import json
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='New output directory (defaults to dist/card-advisor-<current version>)')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    repo = root / 'vendor/CombatSolver'
    version = json.loads((repo / 'CombatSolver.json').read_text())['version']
    args.output = args.output or Path(f'dist/card-advisor-{version}')
    args.output.mkdir(parents=True, exist_ok=False)
    # Patch distribution: preserve the existing installation's Windows memory
    # cleaner; no game or third-party dependency DLLs are redistributed here.
    files = [
        (repo / '.godot/mono/temp/bin/Release/CombatSolver.dll', 'CombatSolver/CombatSolver.dll'),
        (repo / 'CombatSolver.json', 'CombatSolver/CombatSolver.json'),
        (repo / 'THIRD_PARTY_NOTICES.md', 'CombatSolver/THIRD_PARTY_NOTICES.md'),
        (root / 'docs/card-advisor.md', 'README.md'),
    ]
    with zipfile.ZipFile(args.output / f'CombatSolver-{version}-card-advisor-patch.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
        for source, target in files:
            archive.write(source, target)
    with zipfile.ZipFile(args.output / 'advisor-service.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
        for package in ['train', 'damage_model']:
            for source in sorted((root / package).rglob('*.py')):
                archive.write(source, 'advisor-service/' + source.relative_to(root).as_posix())
        paths = ['catalogs/game-0.111.0.raw.json', 'configs/real-runs-8s.json', 'configs/mutations-targeted-8s.json', 'configs/reward-policy.json', 'docs/policy-configuration.md', 'docs/policy-cleanup-20261102.md', 'docs/counter-state.md']
        for path in paths:
            archive.write(root / path, 'advisor-service/' + path)
        for name in ['artifact.json', 'vocab.json', 'weights.pt']:
            archive.write(root / 'checkpoints/train/selected' / name, 'advisor-service/checkpoints/train/selected/' + name)
        archive.write(root / 'requirements-advisor.txt', 'advisor-service/requirements.txt')
        archive.write(root / 'docs/card-advisor.md', 'advisor-service/README.md')
    print(args.output / f'CombatSolver-{version}-card-advisor-patch.zip')
    print(args.output / 'advisor-service.zip')


if __name__ == '__main__':
    main()
