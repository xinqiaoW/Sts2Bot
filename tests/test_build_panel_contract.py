import copy,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(Path(__file__).parent),str(ROOT/'experiments/standalone-simulator'),str(ROOT)]
from build_panel_contract import composition_key,build_acceptance_passed

def request():
 return dict(runId='one',trainingActId='UNDERDOCKS',seed=1,runCards=[dict(cardId='STRIKE_SILENT',count=1,upgradeLevels=0),dict(cardId='SLICE',count=1,upgradeLevels=1)],relics=[dict(relicId='PEN_NIB',integerMembers={'AttacksPlayed':1}),dict(relicId='BAG_OF_PREPARATION')])

def test_ids_act_seed_and_card_order_do_not_inflate_build_count():
 a=request();b=copy.deepcopy(a);b.update(runId='two',seed=9,trainingActId='HIVE');b['runCards'].reverse()
 assert composition_key(a)==composition_key(b)

@pytest.mark.parametrize('change',['upgrade','enchantment','persistent','counter','relic_order','card_count'])
def test_gameplay_build_changes_remain_distinct(change):
 a=request();b=copy.deepcopy(a)
 if change=='upgrade':b['runCards'][0]['upgradeLevels']=1
 if change=='enchantment':b['runCards'][0].update(enchantmentId='NIMBLE',enchantmentAmount=1)
 if change=='persistent':b['runCards'][0]['savedIntegerMembers']={'TestState':1}
 if change=='counter':b['relics'][0]['integerMembers']['AttacksPlayed']=2
 if change=='relic_order':b['relics'].reverse()
 if change=='card_count':b['runCards'].append(copy.deepcopy(b['runCards'][0]))
 assert composition_key(a)!=composition_key(b)

@pytest.mark.parametrize('builds,targets,unresolved,stale,expected',[(9999,80,0,0,False),(10000,79,0,0,False),(10000,80,1,0,False),(10000,80,0,1,False),(10000,80,0,0,True),(10020,80,0,0,True)])
def test_gate_requires_ten_thousand_real_builds_all_targets_and_no_difference(builds,targets,unresolved,stale,expected):
 assert build_acceptance_passed(dict(requiredValidatedBuilds=10000,targetCount=80),matched_builds=builds,matched_targets=targets,unresolved=unresolved,stale=stale)==expected

def test_lowered_target_is_not_accepted():
 assert not build_acceptance_passed(dict(requiredValidatedBuilds=96,targetCount=80),matched_builds=10000,matched_targets=80,unresolved=0,stale=0)

@pytest.mark.parametrize('points,expected', [(499999,False),(500000,True)])
def test_requested_checkpoint_floor_is_preserved(points,expected):
 assert build_acceptance_passed(dict(requiredValidatedBuilds=10000,targetCount=80),matched_builds=10000,matched_targets=80,unresolved=0,stale=0,checkpoint_count=points,checkpoint_target=500000)==expected
