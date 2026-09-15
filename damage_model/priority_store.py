"""Two-queue preferences and three-queue task allocation with idle borrowing."""
from collections import Counter
from pathlib import Path

from .schema import canonical
from .store import Store


class PriorityStore:
    def __init__(self, primary, fallback, teacher=None, *, preferred='real'):
        if preferred not in ('real', 'mutation'):
            raise ValueError('Invalid preferred collection dataset')
        self.preferred = preferred
        if primary.db.execute('PRAGMA database_list').fetchone()[2] == fallback.db.execute('PRAGMA database_list').fetchone()[2]:
            raise ValueError('Fallback queue must use a separate database')
        self.primary, self.fallback = primary, fallback
        self.db = primary.db
        teachers = {r[0] for store in (primary, fallback)
                    for r in store.db.execute('SELECT DISTINCT teacher FROM jobs')}
        if len(teachers) > 1 or (teacher is not None and teachers - {canonical(teacher)}):
            raise ValueError('Both queues must use the same frozen teacher')

    def counts(self):
        counts = Counter(self.primary.counts())
        counts.update(self.fallback.counts())
        return dict(counts)

    def claim(self, seconds=180):
        if self.counts().get('failed', 0):
            return None
        order = (('real', self.primary), ('mutation', self.fallback))
        if self.preferred == 'mutation':
            order = order[::-1]
        for name, store in order:
            job = store.claim(seconds)
            if job is not None:
                if name == 'mutation':
                    from .mutations import validate_lineage
                    validate_lineage(store.db, job['build_id'])
                return {**job, 'collection_dataset': name}
        return None

    def owner(self, job):
        name = job.get('collection_dataset')
        if name not in ('real', 'mutation'):
            raise ValueError('Missing queue ownership')
        return self.primary if name == 'real' else self.fallback

    def finish(self, job, result):
        return self.owner(job).finish(job, result)

    def retry_startup(self, job, result, max_attempts=3):
        return self.owner(job).retry_startup(job, result, max_attempts)

    def retry_or_quarantine_native(self, job, result, **kwargs):
        return self.owner(job).retry_or_quarantine_native(job, result, **kwargs)


def open_priority(primary, fallback_path, teacher=None, *, preferred='real'):
    if not fallback_path:
        if preferred != 'real':
            raise ValueError('Mutation preference requires a mutation queue')
        return primary, None
    if not Path(fallback_path).is_file():
        raise ValueError('Initialize and validate the mutation database before collecting')
    fallback = Store(fallback_path)
    try:
        from .mutations import require_mutation_database
        require_mutation_database(fallback.db)
        return PriorityStore(primary, fallback, teacher, preferred=preferred), fallback
    except BaseException:
        fallback.db.close()
        raise


DATASET_CYCLE = ('real', 'real', 'mutation', 'targeted')


class AllocationStore(PriorityStore):
    """2:1:1 successful claims per worker cycle; empty queues lend capacity.

    The ratio applies to task starts, not CPU seconds or guaranteed valid labels.
    A native retry is routed back to its original database, never another queue.
    """
    def __init__(self, primary, fallback, targeted, teacher=None, *, offset=0):
        super().__init__(primary, fallback, teacher)
        PriorityStore(primary, targeted, teacher)
        paths = [s.db.execute('PRAGMA database_list').fetchone()[2] for s in (primary, fallback, targeted)]
        if len(set(paths)) != 3: raise ValueError('All three queues must be separate')
        from .mutations import require_mutation_database
        require_mutation_database(targeted.db)
        import json
        policy = json.loads(targeted.db.execute("SELECT value FROM collection_settings WHERE key='mutation_policy'").fetchone()[0])
        if not policy.get('target_selection'): raise ValueError('Targeted queue lacks an encounter selection policy')
        if type(offset) is not int or offset < 0: raise ValueError('Invalid allocation offset')
        self.stores = {'real': primary, 'mutation': fallback, 'targeted': targeted}
        self.cursor = offset % len(DATASET_CYCLE)

    def counts(self):
        total = Counter()
        for store in self.stores.values(): total.update(store.counts())
        return dict(total)

    def claim(self, seconds=180):
        if self.counts().get('failed', 0): return None
        preferred = DATASET_CYCLE[self.cursor]
        for name in dict.fromkeys([preferred, *DATASET_CYCLE]):
            store = self.stores[name]
            job = store.claim(seconds)
            if job is not None:
                if name != 'real':
                    from .mutations import validate_lineage
                    validate_lineage(store.db, job['build_id'])
                self.cursor = (self.cursor + 1) % len(DATASET_CYCLE)
                return {**job, 'collection_dataset': name}
        return None

    def owner(self, job):
        try: return self.stores[job['collection_dataset']]
        except KeyError: raise ValueError('Missing three-queue ownership') from None


def open_allocation(primary, fallback_path, targeted_path, teacher=None, *, offset=0):
    if not fallback_path or not targeted_path: raise ValueError('Three-queue allocation requires both mutation databases')
    opened = []
    try:
        from .mutations import require_mutation_database
        for path in (fallback_path, targeted_path):
            if not Path(path).is_file(): raise ValueError('Initialize mutation queues before collection')
            store = Store(path); opened.append(store); require_mutation_database(store.db)
        return AllocationStore(primary, *opened, teacher, offset=offset), opened
    except BaseException:
        for store in opened: store.db.close()
        raise
