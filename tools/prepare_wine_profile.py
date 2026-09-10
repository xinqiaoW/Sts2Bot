"""Prepare only an isolated collector profile; never target the interactive save."""
import argparse
import json
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('data_dir',type=Path)
args=p.parse_args()
root=args.data_dir.resolve()
if '.runtime' not in root.parts: raise ValueError('Expected an isolated .runtime directory')
settings=root/'default/1/settings.save'
data=json.loads(settings.read_text(encoding='utf-8-sig'))
data['mod_settings']={'mods_enabled':True,'mod_list':[]}
settings.write_text(json.dumps(data),encoding='utf-8')
progress=root/'default/1/modded/profile1/saves/progress.save'
if not progress.exists():
    raise ValueError('Initialize the isolated game profile before preparing it')
data=json.loads(progress.read_text(encoding='utf-8-sig'))
data['enable_ftues']=False
progress.write_text(json.dumps(data),encoding='utf-8')
(root/'combat_solver_settings.json').write_text(json.dumps({
    'enableNoGcRegion':False,'searchMaxDegreeOfParallelism':1}),encoding='utf-8')
print('Isolated collector profile prepared:',root)
