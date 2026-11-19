"""Fetch all CMDB data from the PDI and save it as raw JSON, exactly as the Table API returns it."""
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

# relationships, every table a CI field points to (found in the fetched CI data),
# and the tickets that point to CIs: past failures we can replay through the graph
TABLES = ['cmdb_rel_ci', 'cmdb_rel_type', 'cmn_location', 'sys_user_group', 'sys_user', 'core_company',
          'cmn_department', 'cmn_cost_center', 'cmdb_model', 'alm_asset', 'cmn_schedule',
          'incident', 'problem', 'change_request', 'task_ci',
          # ServiceNow's reference: which relationship type and direction each pair of classes should use
          'cmdb_rel_type_suggest',
          # CI-to-person and CI-to-team links, and the class tree (one graph label per class level)
          'cmdb_rel_person', 'cmdb_rel_group', 'sys_db_object']
# only the CMDB part of the table catalogue: 916 of 6,973 rows on the PDI
QUERIES = {'sys_db_object': 'nameSTARTSWITHcmdb'}
OUT_DIR = Path(__file__).resolve().parents[2] / 'out' / 'pdi'
PAGE_SIZE = 1000


def get(path, params):
    response = requests.get(f"{os.environ['PDI_URL']}/api/now/{path}", params=params,
                            auth=(os.environ['PDI_USER'], os.environ['PDI_PASSWORD']),
                            headers={'Accept': 'application/json'})
    response.raise_for_status()
    return response


def ci_classes():
    """Every CI class in use, with its row count, from the Aggregate API."""
    groups = get('stats/cmdb_ci', {'sysparm_count': 'true', 'sysparm_group_by': 'sys_class_name'}).json()['result']
    return {group['groupby_fields'][0]['value']: int(group['stats']['count']) for group in groups}


def fetch_table(table, query=''):
    """Return every row of `table` matching `query` and the total the API reports. Each field is {value, display_value}."""
    rows = []
    while True:
        response = get(f'table/{table}', {
            'sysparm_display_value': 'all',
            # a fixed sort order, so consecutive pages neither overlap nor skip rows
            'sysparm_query': f'{query}^ORDERBYsys_id',
            'sysparm_limit': PAGE_SIZE,
            'sysparm_offset': len(rows),
        })
        page = response.json()['result']
        rows += page
        if len(page) < PAGE_SIZE:
            return rows, int(response.headers['X-Total-Count'])


def main():
    load_dotenv()
    (OUT_DIR / 'ci').mkdir(parents=True, exist_ok=True)
    # a parent table such as cmdb_ci returns only its own fields, so fetch each class from its own table
    for ci_class, count in ci_classes().items():
        rows, total = fetch_table(ci_class, f'sys_class_name={ci_class}')
        (OUT_DIR / 'ci' / f'{ci_class}.json').write_text(json.dumps(rows, indent=2))
        print(f'{ci_class}: {len(rows)} rows fetched, API reports {total}, class count {count}')
    for table in TABLES:
        rows, total = fetch_table(table, QUERIES.get(table, ''))
        (OUT_DIR / f'{table}.json').write_text(json.dumps(rows, indent=2))
        print(f'{table}: {len(rows)} rows fetched, API reports {total}')
    # where and when the extract was taken: the loader copies it onto every node and relationship
    manifest = {'src_system': 'servicenow', 'src_instance': urlparse(os.environ['PDI_URL']).hostname.split('.')[0],
                'extracted_at': datetime.now(UTC).isoformat(timespec='seconds')}
    (OUT_DIR / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(f'manifest: {manifest}')


if '__main__' == __name__:
    main()
