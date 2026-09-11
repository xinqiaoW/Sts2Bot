    // Restore losslessly interned strings before expanding card entries.
    if (payload.string_entries) {
      const strings = payload.string_entries;
      const restoreStrings = value => {
        if (Array.isArray(value)) return value.map(restoreStrings);
        if (value && typeof value === 'object') {
          if (Object.keys(value).length === 1 && Object.hasOwn(value, '$s')) {
            if (!Number.isInteger(value.$s) || value.$s < 0 || value.$s >= strings.length) {
              throw new Error('Invalid viewer string reference');
            }
            return strings[value.$s];
          }
          return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, restoreStrings(item)]));
        }
        return value;
      };
      payload.datasets = restoreStrings(payload.datasets);
      payload.card_entries = restoreStrings(payload.card_entries);
      delete payload.string_entries;
    }
    (payload.datasets || []).forEach(dataset => {
      if (!dataset.build_columns) return;
      const columns = dataset.build_columns;
      const keys = Object.keys(columns);
      const count = columns[keys[0]].length;
      if (keys.some(key => columns[key].length !== count)) throw new Error('Invalid viewer build column');
      dataset.builds = Array.from({length: count}, (_, i) =>
        Object.fromEntries(keys.map(key => [key, columns[key][i]])));
      delete dataset.build_columns;
    });
