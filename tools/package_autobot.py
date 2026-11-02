"""Package the tested mod and Python bot, reusing the player's existing model."""
import argparse
import json
from pathlib import Path
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--include-model', action='store_true', help='Optional full package instead of the small update')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    mod = root / 'vendor/CombatSolver'
    version = json.loads((mod / 'CombatSolver.json').read_text())['version']
    files = [(mod / '.godot/mono/temp/bin/Release/CombatSolver.dll', 'CombatSolver/CombatSolver.dll'),
             (mod / 'tools/CombatSolver.MemoryCleaner/bin/Release/net48/CombatSolver.MemoryCleaner.exe',
              'CombatSolver/CombatSolver.MemoryCleaner.exe'),
             (mod / 'CombatSolver.json', 'CombatSolver/CombatSolver.json'),
             (mod / 'THIRD_PARTY_NOTICES.md', 'CombatSolver/THIRD_PARTY_NOTICES.md'),
             (mod / f'docs/{version}-RELEASE_NOTES.md', '更新说明.md')]
    for package in ('runctl', 'train', 'damage_model'):
        files.extend((p, 'advisor-service/' + p.relative_to(root).as_posix())
                     for p in sorted((root / package).rglob('*.py')) if p.name != 'score_examples.py')
    paths = ['catalogs/game-0.111.0.raw.json', 'configs/real-runs-8s.json',
             'configs/mutations-targeted-8s.json', 'configs/reward-policy.json', 'configs/bot-policy.json',
             'tools/prepare_windows_autobot.py', 'tools/prepare_autobot_runtime.py',
             'tools/install_bot_update.py', 'tools/install_scoring_horizon_update.py',
             'docs/policy-configuration.md', 'docs/policy-cleanup-20261102.md',
             'docs/history/autobot-progress-20261101.md',
             'docs/autobot.md', 'docs/autobot-progress.md', 'docs/autobot-evaluation-plan.md',
             'docs/counter-state.md', 'docs/card-advisor.md', 'docs/relic-rules.md']
    report = root / 'docs/autobot-evaluation.md'
    if report.exists(): paths.append(report.relative_to(root).as_posix())
    if args.include_model:
        paths.extend('checkpoints/train/selected/' + name for name in ('artifact.json', 'vocab.json', 'weights.pt'))
    files.extend((root / p, 'advisor-service/' + p) for p in paths)
    files.append((root / 'requirements-advisor.txt', 'advisor-service/requirements.txt'))
    for source, _ in files:
        if not source.is_file(): raise FileNotFoundError(source)
    args.output.mkdir(parents=True, exist_ok=False)
    path = args.output / f'CombatSolver-{version}-autobot-{"full" if args.include_model else "update"}.zip'
    instructions = f'''CombatSolver {version} 全流程机器人本地测试版

首次安装可使用包内 advisor-service。已有安装请关闭 Bot 和游戏，使用统一安装器保留参数：
python advisor-service/tools/install_bot_update.py --target <已安装advisor-service目录> --bot <含runtime.json的Bot目录>
安装器备份旧文件、只补缺失配置，不覆盖已有值；不要整目录覆盖 configs。
CombatSolver 文件夹用于准备命令的 --mod 参数。
已有独立 Bot 目录无需重新准备；安装器读取 runtime.json 的 game_dir 定位实际 Mod。
战斗搜索通过独立目录 runtime.json 的 combat_search_mode="settings" 启用玩家设置。
之后在 Bot 独立游戏的 CombatSolver 设置里调整性能档位/自定义预算，下一局读取。
如需更新原游戏的人工评分面板，也可覆盖原 Mod 的 DLL、manifest、NOTICE 和 MemoryCleaner。
更新包默认不重复下载模型或 Python 依赖。首次使用者需要模型及 requirements.txt 依赖。

完整启动命令与参数说明见 advisor-service/docs/autobot.md。
一次准备后双击输出目录中的“启动自动爬塔.bat”。
全自动机器人使用独立游戏与存档，无需另开 HTTP 评分服务。
请使用自己的原版游戏与已安装 RitsuLib；本包不包含第三方游戏和依赖文件。
当前评测状态见 docs/autobot-progress.md。历史版本的结果不代表当前版本胜率。
'''
    with zipfile.ZipFile(path, 'x', zipfile.ZIP_DEFLATED) as archive:
        for source, target in files: archive.write(source, target)
        archive.writestr('安装说明.txt', instructions)
    print(path)
    print(f'{path.stat().st_size / 1024 / 1024:.2f} MiB')


if __name__ == '__main__':
    main()
