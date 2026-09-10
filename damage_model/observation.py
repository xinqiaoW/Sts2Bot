"""Validate HP labels while allowing verified native combat mechanics."""


def validate_hp(observation, target):
    required = ('initialHp', 'initialMaxHp', 'finalHp', 'finalMaxHp', 'netHpLoss', 'playerDied')
    if any(k not in observation for k in required):
        raise ValueError('Incomplete observation')
    if any(type(observation[k]) is not int for k in required[:5]):
        raise ValueError('HP fields must be integers')
    if type(observation['playerDied']) is not bool:
        raise ValueError('Death must be boolean')
    initial_max, final_max = observation['initialMaxHp'], observation['finalMaxHp']
    if initial_max <= 0 or final_max <= 0:
        raise ValueError('Invalid max HP')
    if observation['initialHp'] != initial_max:
        raise ValueError('Not full HP')
    if final_max != initial_max:
        # 0.111.0: ScrollOfBiting applies PaperCutsPower(2). Each damaging
        # attack hit removes 2 max HP; CreatureCmd.LoseMaxHp clamps at 1.
        paper_cuts = (target.get('id') in ('SCROLLS_OF_BITING_NORMAL', 'SCROLLS_OF_BITING_WEAK')
                      and target.get('monsters') == ['SCROLL_OF_BITING'])
        # 0.111.0: BrightestFlame.OnPlay loses 2 max HP, also when upgraded.
        # Store.finish separately verifies the complete actual starting deck.
        brightest_flame = any(c.get('id') == 'BRIGHTEST_FLAME' for c in
                              observation.get('initialBuild', {}).get('cards', []))
        if not ((paper_cuts or brightest_flame) and final_max < initial_max
                and (final_max == 1 or (initial_max - final_max) % 2 == 0)):
            raise ValueError('Unexpected max HP change')
    if not 0 <= observation['finalHp'] <= final_max:
        raise ValueError('Invalid terminal HP')
    if observation['netHpLoss'] != observation['initialHp'] - observation['finalHp']:
        raise ValueError('Invalid HP loss')
    if observation['playerDied'] != (observation['finalHp'] <= 0):
        raise ValueError('Invalid death label')
