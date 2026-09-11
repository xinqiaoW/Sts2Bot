"""Lossless dictionary encoding for repeated strings in offline view data."""
from collections import Counter


def pack_build_columns(payload):
    datasets = []
    for dataset in payload['datasets']:
        builds = dataset['builds']
        if not builds:
            datasets.append(dataset)
            continue
        keys = list(builds[0])
        assert all(set(build) == set(keys) for build in builds)
        datasets.append({**{key: value for key, value in dataset.items() if key != 'builds'},
                         'build_columns': {key: [build[key] for build in builds] for key in keys}})
    packed = {**payload, 'datasets': datasets}
    assert unpack_build_columns(packed) == payload
    return packed


def unpack_build_columns(payload):
    datasets = []
    for dataset in payload['datasets']:
        if 'build_columns' not in dataset:
            datasets.append(dataset)
            continue
        columns = dataset['build_columns']
        count = len(next(iter(columns.values())))
        assert all(len(column) == count for column in columns.values())
        datasets.append({**{key: value for key, value in dataset.items() if key != 'build_columns'},
                         'builds': [{key: column[i] for key, column in columns.items()} for i in range(count)]})
    return {**payload, 'datasets': datasets}


def unpack_strings(payload):
    if 'string_entries' not in payload:
        return payload
    entries = payload['string_entries']

    def restore(value):
        if isinstance(value, dict):
            if set(value) == {'$s'}:
                index = value['$s']
                if type(index) is not int or not 0 <= index < len(entries):
                    raise ValueError('Invalid viewer string reference')
                return entries[index]
            return {key: restore(item) for key, item in value.items()}
        if isinstance(value, list):
            return [restore(item) for item in value]
        return value

    return {key: restore(value) for key, value in payload.items() if key != 'string_entries'}


def pack_strings(payload):
    counts = Counter()

    def count(value):
        if isinstance(value, str) and len(value) >= 24:
            counts[value] += 1
        elif isinstance(value, dict):
            if '$s' in value or 'string_entries' in value:
                raise ValueError('Reserved viewer encoding key')
            for item in value.values():
                count(item)
        elif isinstance(value, list):
            for item in value:
                count(item)

    count(payload)
    entries = [value for value, frequency in counts.items() if frequency > 1]
    indices = {value: index for index, value in enumerate(entries)}

    def replace(value):
        if isinstance(value, str) and value in indices:
            return {'$s': indices[value]}
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        return value

    packed = {**replace(payload), 'string_entries': entries}
    assert unpack_strings(packed) == payload
    return packed
