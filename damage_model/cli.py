from __future__ import annotations
import argparse
import json
from pathlib import Path
from .catalog import Catalog
from .schema import Build
from .store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--catalog', default='catalogs/game-0.111.0.raw.json')
    parser.add_argument('--config', default='configs/real-runs.json')
    parser.add_argument('--db', default='data/collection-real-runs-v2.sqlite')
    parser.add_argument('--teacher', default='configs/teacher.json')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('catalog-report')
    sub.add_parser('status')
    importer = sub.add_parser('import-runs', help='Import genuine .run files; never generate an inventory')
    importer.add_argument('--directory', required=True)
    sync = sub.add_parser('sync-runs', help='Fetch one durable page of public run exports')
    sync.add_argument('--source-dir', default='data/external/spire-codex')
    sync.add_argument('--start', default='2026-09-05T00:00:00Z')
    worker = sub.add_parser('work')
    worker.add_argument('--runtime', required=True)
    worker.add_argument('--limit', type=int, default=8)
    worker.add_argument('--fallback-db', help='Validated mutation queue, claimed only when the real queue is empty')
    trainer = sub.add_parser('train')
    trainer.add_argument('--output', default='checkpoints/real-runs')
    trainer.add_argument('--epochs', type=int, default=100)
    trainer.add_argument('--device', default='cpu')
    predict = sub.add_parser('predict')
    predict.add_argument('--checkpoint', required=True)
    predict.add_argument('--build', required=True)
    predict.add_argument('--target', required=True)
    predict.add_argument('--max-hp', type=int, required=True)
    args = parser.parse_args()
    catalog = Catalog.load(args.catalog, args.config)
    if args.command == 'catalog-report':
        print(json.dumps({'cards':len(catalog.card_pool), 'relics':len(catalog.relic_pool),
                          'excluded':catalog.excluded}, indent=2))
        return
    if args.command == 'predict':
        from .model import predict
        build = Build.from_dict(json.loads(Path(args.build).read_text(encoding='utf-8')))
        catalog.validate(build)
        print(json.dumps(predict(args.checkpoint, build, args.target, args.max_hp)))
        return
    store = Store(args.db)
    try:
        if args.command == 'status':
            print(json.dumps({'jobs':store.counts(), 'builds':store.db.execute('SELECT COUNT(*) FROM builds').fetchone()[0]}))
            return
        from .provenance import teacher_for
        teacher = teacher_for(catalog, args.teacher)
        if args.command in ('import-runs', 'sync-runs'):
            if catalog.config.get('build_source') != 'spire_codex_run_v1':
                raise ValueError('Real-run import requires configs/real-runs.json')
            if args.command == 'import-runs':
                from .run_import import import_files
                report = import_files(store, catalog, teacher, args.directory)
            else:
                from .run_source import sync_page
                report = sync_page(store, catalog, teacher, args.source_dir, args.start)
            print(json.dumps(report, ensure_ascii=False))
        elif args.command == 'work':
            from .worker import work
            from .priority_store import open_priority
            queues, fallback = open_priority(store, args.fallback_db, teacher)
            try:
                if not work(queues, catalog, args.runtime, args.limit, teacher):
                    raise SystemExit(2)
            finally:
                if fallback is not None: fallback.db.close()
        elif args.command == 'train':
            from .model import train
            print(json.dumps(train(store, catalog, args.output, args.epochs, args.device)))
    finally:
        store.db.close()


if __name__ == '__main__':
    main()
