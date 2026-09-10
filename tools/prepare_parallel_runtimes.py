"""Create isolated Wine prefixes from an idle template, sharing read-only game files."""
import argparse
import json
from pathlib import Path
import shutil


def prepare(base_path, template, count, start=1):
    base_path=Path(base_path).resolve()
    base=json.loads(base_path.read_text())
    project=base_path.parent.parent
    root=(project/'.runtime').resolve()
    template=Path(template).resolve()
    if not template.is_relative_to(root) or not template.is_dir():
        raise ValueError('Template must be an idle prefix inside this project .runtime')
    data_relative=Path(base['data_dir']).relative_to(Path(base['env']['WINEPREFIX']))
    outputs=[]
    for index in range(start,start+count):
        name=f'worker-{index:02d}'
        prefix=root/f'prefix-{name}'
        config_path=base_path.parent/f'runtime-{name}.json'
        if prefix.exists() or config_path.exists(): raise ValueError(f'Already exists: {name}')
        shutil.copytree(template,prefix,symlinks=True)
        data=prefix/data_relative
        for marker in data.glob('combat_solver_test_*.json'): marker.unlink()
        for marker in ('collector.stop','collector.lock'): (data/marker).unlink(missing_ok=True)
        # No gameplay unlocks are added or removed from the copied profile.
        progress=data/'default/1/modded/profile1/saves/progress.save'
        value=json.loads(progress.read_text());value['enable_ftues']=False
        progress.write_text(json.dumps(value))
        runtime={**base,'data_dir':str(data),'env':{**base['env'],'WINEPREFIX':str(prefix)},
                 'log_path':str(project/'logs'/f'{name}-game.log')}
        config_path.write_text(json.dumps(runtime,indent=2))
        outputs.append(str(config_path))
    return outputs


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--base',required=True);p.add_argument('--template',required=True)
    p.add_argument('--count',type=int,required=True);p.add_argument('--start',type=int,default=1)
    args=p.parse_args()
    if args.count<1: raise ValueError('count must be positive')
    print(json.dumps(prepare(args.base,args.template,args.count,args.start)))
