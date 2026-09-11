"""The one native starter replacement supported for Silent source builds."""

SNAKE = 'RING_OF_THE_SNAKE'
DRAKE = 'RING_OF_THE_DRAKE'
TOUCH = 'TOUCH_OF_OROBAS'
STARTERS = {SNAKE, DRAKE}


def uses_orobas_replacement(relic_ids, ancient_history):
    ids = list(relic_ids)
    if TOUCH not in ids and DRAKE not in ids:
        return False
    if (not ids or ids[0] != DRAKE or ids.count(DRAKE) != 1
            or ids.count(TOUCH) != 1 or SNAKE in ids
            or sum(ancient == 'OROBAS' and reward == TOUCH and act == 2
                   for act, ancient, reward in ancient_history) != 1):
        raise ValueError('Invalid Silent starter replacement provenance or inventory')
    return True
