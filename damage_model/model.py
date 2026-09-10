from __future__ import annotations

import json
from pathlib import Path
import random
import numpy as np
import torch
from torch import nn
from .schema import Build, canonical
from .encoding import Encoder


class DamageNet(nn.Module):
    def __init__(self, features, hidden=128):
        super().__init__()
        self.body = nn.Sequential(nn.Linear(features,hidden),nn.SiLU(),nn.Linear(hidden,hidden),nn.SiLU())
        self.head = nn.Linear(hidden,2)

    def forward(self,x):
        y = self.head(self.body(x))
        return y[:,0],y[:,1]


def train(store,catalog,output,epochs=100,device='cpu',seed=20260905,min_train_builds=20):
    if epochs < 1: raise ValueError('epochs must be positive')
    torch.set_num_threads(4)
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    rows=list(store.rows())
    teachers={canonical(row['teacher']) for row in rows}
    if len(teachers)!=1: raise ValueError('Training requires exactly one frozen teacher configuration')
    encoder=Encoder.from_catalog(catalog)
    splits={name:[] for name in ('train','validation','test')}
    for row in rows: splits[row['split']].append(row)
    if len({r['build_id'] for r in splits['train']}) < min_train_builds:
        raise ValueError('Insufficient distinct training builds; refusing to present a tiny smoke model as trained')
    if not splits['validation'] or not splits['test']: raise ValueError('Missing held-out families')
    build_sets={s:{r['build_id'] for r in records} for s,records in splits.items()}
    family_sets={s:{r['build']['family'] for r in records} for s,records in splits.items()}
    for left,right in (('train','validation'),('train','test'),('validation','test')):
        if build_sets[left]&build_sets[right] or family_sets[left]&family_sets[right]: raise ValueError('Split leakage')
    def tensors(records):
        x=np.stack([encoder.encode(Build.from_dict(r['build']),r['target']['id'],r['result']['trainingObservation']['initialMaxHp']) for r in records])
        y=np.array([r['result']['trainingObservation']['netHpLoss']/70 for r in records],dtype=np.float32)
        death=np.array([r['result']['trainingObservation']['playerDied'] for r in records],dtype=np.float32)
        # Unequal repeat counts should not change which build/target combinations dominate.
        counts={}
        for r in records:
            key=(r['build_id'],r['target']['id']); counts[key]=counts.get(key,0)+1
        weight=np.array([1/counts[(r['build_id'],r['target']['id'])] for r in records],dtype=np.float32)
        return tuple(torch.as_tensor(v,device=device) for v in (x,y,death,weight))
    data={s:tensors(rs) for s,rs in splits.items()}
    model=DamageNet(len(encoder.positions)).to(device)
    optimizer=torch.optim.AdamW(model.parameters(),lr=1e-3,weight_decay=1e-4)
    best=float('inf'); best_state=None; history=[]
    for epoch in range(epochs):
        model.train(); x,y,d,w=data['train']
        order=torch.randperm(len(x),device=device)
        for indices in order.split(256):
            mean,death=model(x[indices]); weights=w[indices]
            loss=(((mean-y[indices])**2+0.1*nn.functional.binary_cross_entropy_with_logits(death,d[indices],reduction='none'))*weights).sum()/weights.sum()
            optimizer.zero_grad(); loss.backward(); optimizer.step()
        model.eval()
        with torch.no_grad():
            vx,vy,vd,vw=data['validation']; prediction,_=model(vx)
            metric=float((((prediction-vy)**2)*vw).sum()/vw.sum())
        history.append({'epoch':epoch+1,'validation_mse_hp':metric*4900})
        if metric<best:
            best=metric; best_state={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
    model.load_state_dict(best_state)
    metrics={}
    with torch.no_grad():
        for split,(x,y,d,w) in data.items():
            pred,death=model(x)
            combinations={}
            for index,row in enumerate(splits[split]):
                combinations.setdefault((row['build_id'],row['target']['id']),[]).append(index)
            mean_errors=torch.stack([(pred[indices].mean()-y[indices].mean())*70
                                     for indices in combinations.values()])
            # Individual seed errors include irreducible combat randomness.
            metrics[split]={'rows':len(x),'builds':len(build_sets[split]),'families':len(family_sets[split]),
                'mae_hp':float((abs(pred-y)*w).sum()/w.sum())*70,
                'rmse_hp':float((((pred-y)**2*w).sum()/w.sum()).sqrt())*70,
                'death_brier':float(((torch.sigmoid(death)-d)**2*w).sum()/w.sum()),
                'pair_mean_mae_hp':float(mean_errors.abs().mean()),
                'pair_mean_rmse_hp':float(mean_errors.square().mean().sqrt()),
                'pairs':len(combinations)}
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    artifact={'schema_version':1,'state_dict':best_state,'encoder':encoder.spec,'hidden':128,
              'teacher':json.loads(next(iter(teachers))),'metrics':metrics,'seed':seed,
              'training_build_ids':sorted(build_sets['train']),'trained_targets':sorted({r['build']['act_id']+':'+r['target']['id'] for r in splits['train']}),
              'label_scale':70.0}
    torch.save(artifact,output/'model.pt')
    (output/'metrics.json').write_text(json.dumps({'metrics':metrics,'history':history},indent=2),encoding='utf-8')
    return metrics


def predict(checkpoint,build,target_id,max_hp):
    artifact=torch.load(checkpoint,map_location='cpu',weights_only=True)
    if build.act_id+':'+target_id not in artifact['trained_targets']: raise ValueError('Target has no training coverage')
    encoder=Encoder(artifact['encoder']); model=DamageNet(len(encoder.positions),artifact['hidden'])
    model.load_state_dict(artifact['state_dict']); model.eval()
    with torch.no_grad():
        mean,death=model(torch.from_numpy(encoder.encode(build,target_id,max_hp)[None,:]))
    return {'expected_hp_loss':max(0.0,min(float(max_hp),float(mean[0])*artifact['label_scale'])),
            'death_probability':float(torch.sigmoid(death[0]))}
