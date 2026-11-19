"""Build the Bond Trading mock slice on the PDI from bond_slice_spec.json, and log every write in ledger.json.

A re-run creates nothing new: new CIs are found by name plus the MOCK marker, updates skip fields that already hold
the new value, deleted rows are gone, and relationships are found by parent + type + child.
"""
import json
import os
from collections import defaultdict
from pathlib import Path

import requests
from dotenv import load_dotenv

from kg.pdi import OUT_DIR, fetch_table, get

MOCK_DIR = Path(__file__).resolve().parent
SPEC = MOCK_DIR / 'bond_slice_spec.json'
LEDGER = MOCK_DIR / 'ledger.json'
MARKER = 'MOCK demo'
# business rule "Update life cycle from legacy" fills these on any update while they are empty, so log them too
LIFE_CYCLE = ['life_cycle_stage', 'life_cycle_stage_status']


def send(method, path, body=None):
    """Write to the PDI. Any non-2xx status or an "error" key in the body is a failed write."""
    response = requests.request(method, f"{os.environ['PDI_URL']}/api/now/{path}", json=body,
                                params={'sysparm_exclude_reference_link': 'true'},
                                auth=(os.environ['PDI_USER'], os.environ['PDI_PASSWORD']),
                                headers={'Accept': 'application/json'})
    response.raise_for_status()
    if 204 == response.status_code:
        return {}
    body = response.json()
    assert 'error' not in body, body
    return body['result']


def read(table, query, fields):
    """Raw values (sys_ids for references) of the rows matching `query`."""
    return get(f'table/{table}', {'sysparm_query': query, 'sysparm_fields': ','.join(fields),
                                  'sysparm_exclude_reference_link': 'true'}).json()['result']


def log(ledger, section, entry):
    """Record one write and save the ledger at once, so a run that stops half-way still lists what it wrote."""
    ledger[section].append(entry)
    LEDGER.write_text(json.dumps(ledger, indent=2))
    print(f'{section}: {entry}')


def reaches(edges, start, goal):
    """True if `goal` can be reached from `start` following parent -> child."""
    seen, todo = set(), [start]
    while todo:
        node = todo.pop()
        if goal == node:
            return True
        if node not in seen:
            seen.add(node)
            todo += edges[node]
    return False


def main():
    load_dotenv()
    spec = json.loads(SPEC.read_text())
    if LEDGER.exists():
        ledger = json.loads(LEDGER.read_text())
    else:
        ledger = {'created': [], 'updated': [], 'deleted': [], 'relationships': [], 'notes': []}

    # 1. business app and new CIs: local key -> sys_id
    keys = {}
    for record in [spec['business_app']] + spec['new_cis']:
        name = record['fields']['name']
        found = read(record['table'], f'name={name}^short_descriptionSTARTSWITH{MARKER}', ['sys_id'])
        if found:
            sys_id = found[0]['sys_id']
        else:
            sys_id = send('POST', f"table/{record['table']}", record['fields'])['sys_id']
        keys[record['local_key']] = sys_id
        # also logs a record created by a run that stopped before logging it
        if sys_id in [entry['sys_id'] for entry in ledger['created']]:
            continue
        # only the business app has a number (APM...); server classes have no number field
        number = read(record['table'], f'sys_id={sys_id}', ['number'])[0].get('number', '')
        # model_id is not sent, so no asset should appear; the count proves it
        assets = read('alm_asset', f'ci={sys_id}', ['sys_id'])
        log(ledger, 'created', {'local_key': record['local_key'], 'table': record['table'], 'name': name,
                                'sys_id': sys_id, 'number': number, 'assets': len(assets)})

    # 2. pre-check: every field to update holds the spec's old value, or already the new one (re-run)
    before = {}
    for update in spec['updates']:
        row = read(update['table'], f"sys_id={update['sys_id']}", list(update['fields']) + LIFE_CYCLE)[0]
        for field, change in update['fields'].items():
            new = keys.get(change['new'], change['new'])
            assert row[field] in (change['old'], new), f"{update['name']}.{field}: live {row[field]!r}"
        before[update['sys_id']] = row
    for delete in spec['deletes']:
        for row in read('cmdb_rel_ci', f"sys_id={delete['sys_id']}", ['parent', 'type', 'child']):
            assert (delete['parent_sys_id'], delete['type_sys_id'], delete['child_sys_id']) == (
                row['parent'], row['type'], row['child']), delete

    # 3. updates, one record at a time; re-read to log what changed, including the derived life cycle
    for update in spec['updates']:
        old = before[update['sys_id']]
        changes = {field: keys.get(change['new'], change['new']) for field, change in update['fields'].items()}
        changes = {field: new for field, new in changes.items() if old[field] != new}
        if not changes:
            continue
        send('PATCH', f"table/{update['table']}/{update['sys_id']}", changes)
        new = read(update['table'], f"sys_id={update['sys_id']}", list(update['fields']) + LIFE_CYCLE)[0]
        assert all(new[field] == value for field, value in changes.items()), (update['name'], changes, new)
        for field in list(changes) + LIFE_CYCLE:
            if old[field] != new[field]:
                log(ledger, 'updated', {'table': update['table'], 'sys_id': update['sys_id'], 'name': update['name'],
                                        'field': field, 'old': old[field], 'new': new[field]})

    # 4. delete the backwards rows; the ledger keeps each full row so it can be re-inserted
    for delete in spec['deletes']:
        for row in fetch_table('cmdb_rel_ci', f"sys_id={delete['sys_id']}")[0]:
            send('DELETE', f"table/cmdb_rel_ci/{delete['sys_id']}")
            log(ledger, 'deleted', {'why': delete['why'], 'row': row})

    # 5. new relationships, refusing any row that would close a loop with the live rows
    live = fetch_table('cmdb_rel_ci')[0]
    existing = {(row['parent']['value'], row['type']['value'], row['child']['value']) for row in live}
    edges = defaultdict(list)
    for parent, _, child in existing:
        edges[parent].append(child)
    for rel in spec['relationships']:
        parent = rel['parent'].get('sys_id') or keys[rel['parent']['local_key']]
        child = rel['child'].get('sys_id') or keys[rel['child']['local_key']]
        if (parent, rel['type_sys_id'], child) in existing:
            continue
        assert not reaches(edges, child, parent), f"{rel['id']} would close a loop"
        created = send('POST', 'table/cmdb_rel_ci', {'parent': parent, 'type': rel['type_sys_id'], 'child': child})
        edges[parent].append(child)
        log(ledger, 'relationships', {'id': rel['id'], 'sys_id': created['sys_id'], 'parent': rel['parent']['name'],
                                      'type': rel['type'], 'child': rel['child']['name']})

    # 6. the mock alerts for the nas200 outage (em_alert does not exist on the PDI)
    (OUT_DIR / 'em_alert.json').write_text(json.dumps(spec['alerts'], indent=2))
    print(f"em_alert.json: {len(spec['alerts'])} synthetic alerts")
    print(f"ledger totals: {', '.join(f'{section} {len(entries)}' for section, entries in ledger.items())}")


if '__main__' == __name__:
    main()
