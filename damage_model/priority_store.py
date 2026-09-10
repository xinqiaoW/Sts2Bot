"""One worker owns both queues and gives real runs priority at each claim."""
from collections import Counter
from pathlib import Path

from .schema import canonical
from .store import Store


class PriorityStore:
    def __init__(self, primary, fallback, teacher=None):
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
        for name, store in (('real', self.primary), ('mutation', self.fallback)):
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


def open_priority(primary, fallback_path, teacher=None):
    if not fallback_path:
        return primary, None
    if not Path(fallback_path).is_file():
        raise ValueError('Initialize and validate the mutation database before collecting')
    fallback = Store(fallback_path)
    try:
        from .mutations import require_mutation_database
        require_mutation_database(fallback.db)
        return PriorityStore(primary, fallback, teacher), fallback
    except BaseException:
        fallback.db.close()
        raise
