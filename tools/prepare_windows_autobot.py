"""Prepare an isolated, visible Windows game for the whole-run bot.

Run from the advisor/bot service directory. Asset hard links save disk space;
the bot's settings, mods and user profile are separate from the player's game.
"""
import argparse
import errno
import json
import os
from pathlib import Path
import shutil
import sys
import uuid


def write_launcher(output, service_root, python_executable):
    def literal(value):
        return "'" + str(value).replace("'", "''") + "'"
    script = f'''$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath {literal(service_root)}
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$runtime = Join-Path $PSScriptRoot 'runtime.json'
$report = Join-Path $PSScriptRoot ('reports/' + $stamp)
& {literal(python_executable)} -m runctl --runtime $runtime --episodes 1 --policy-config {literal(service_root / 'configs/bot-policy.json')} --output $report
if ($LASTEXITCODE -ne 0) {{
    Write-Host ('Bot stopped with an error. Logs: ' + $report) -ForegroundColor Red
    exit $LASTEXITCODE
}}
Write-Host ('Run finished. Logs: ' + $report)
'''
    (output/'start-autobot.ps1').write_text(script, encoding='utf-8-sig')
    (output/'启动自动爬塔.bat').write_text('@echo off\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-autobot.ps1"\npause\n', encoding='ascii', newline='\r\n')


def link_asset(source, destination):
    try:
        os.link(source, destination)
    except OSError as exc:
        if exc.errno not in (errno.EXDEV, errno.EPERM, errno.EACCES): raise
        shutil.copy2(source, destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, required=True, help='Folder containing SlayTheSpire2.exe')
    parser.add_argument('--output', type=Path, required=True, help='New folder, preferably on the same drive as the game')
    parser.add_argument('--mod', type=Path, required=True, help='New CombatSolver folder containing DLL and manifest')
    parser.add_argument('--ritsu-lib', type=Path, help='Installed STS2-RitsuLib mod folder')
    args = parser.parse_args()
    if os.name != 'nt': parser.error('Use this preparation entry on Windows')
    game, output, mod = args.game.resolve(), args.output.resolve(), args.mod.resolve()
    ritsu = (args.ritsu_lib or game/'mods/STS2-RitsuLib').resolve()
    for required in (game/'SlayTheSpire2.exe', mod/'CombatSolver.dll', mod/'CombatSolver.json', mod/'THIRD_PARTY_NOTICES.md'):
        if not required.is_file(): parser.error(f'Missing file: {required}')
    if not ritsu.is_dir(): parser.error('Provide --ritsu-lib with your installed STS2-RitsuLib folder')
    if output.exists(): parser.error('Output must be a new folder; never overwrite a running worker')
    if output == game or game in output.parents: parser.error('Place the isolated runtime outside the original game folder')
    output.mkdir(parents=True)
    target = output/'game'
    shutil.copytree(game, target, copy_function=link_asset,
                    ignore=lambda directory, names: {'mods', 'override.cfg'} if Path(directory) == game else set())
    (target/'mods').mkdir()
    shutil.copytree(mod, target/'mods/CombatSolver')
    shutil.copytree(ritsu, target/'mods/STS2-RitsuLib')
    # Never edit an asset hard link: override.cfg was excluded from linking.
    profile_name = 'CombatSolver-Autobot-' + uuid.uuid4().hex[:12]
    original = game/'override.cfg'
    settings = original.read_text(encoding='utf-8-sig') if original.exists() else ''
    settings += f'\n[application]\nconfig/use_custom_user_dir=true\nconfig/custom_user_dir_name="{profile_name}"\n'
    (target/'override.cfg').write_text(settings, encoding='utf-8')
    profile = Path(os.environ['APPDATA'])/profile_name
    profile.mkdir(parents=True, exist_ok=False)
    settings_path = profile/'default/1/settings.save'
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps(dict(schema_version=8, seen_ea_disclaimer=True,
        mod_settings=dict(mods_enabled=True, mod_list=[]))), encoding='utf-8')
    (profile/'combat_solver_settings.json').write_text(json.dumps(dict(enableNoGcRegion=False,
        searchMaxDegreeOfParallelism=1)), encoding='utf-8')
    runtime = dict(kind='run_control', game_dir=str(target), data_dir=str(profile), combat_search_mode='settings',
        command=[str(target/'SlayTheSpire2.exe'), '--force-steam=off'],
        env=dict(COMBATSOLVER_RUN_CONTROL='1', STS2_CARD_ADVISOR_DISABLED='1'),
        log_path=str(output/'native.log'))
    path = output/'runtime.json'
    path.write_text(json.dumps(runtime, ensure_ascii=False, indent=2), encoding='utf-8')
    write_launcher(output, Path(__file__).resolve().parents[1], Path(sys.executable).resolve())
    print(f'Prepared runtime: {path}')
    print(f'Isolated profile: {profile}')
    print(f'Run: python -m runctl --runtime "{path}" --episodes 1 --seed-prefix WINDOWS --output "{output / "report"}"')
    print(f'One-click launcher: {output / "启动自动爬塔.bat"}')


if __name__ == '__main__': main()
