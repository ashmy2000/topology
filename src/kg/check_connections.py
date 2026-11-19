"""Read-only checks: python -m kg.check_connections [--servicenow-only]."""
import argparse
import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from neo4j.exceptions import DriverError, Neo4jError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--servicenow-only', action='store_true')
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[2] / '.env')
    failed = False
    required = ('PDI_URL', 'PDI_USER', 'PDI_PASSWORD')
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        print('ServiceNow FAIL: missing ' + ', '.join(missing))
        failed = True
    else:
        try:
            response = requests.get(
                os.environ['PDI_URL'].rstrip('/') + '/api/now/table/cmdb_ci',
                auth=(os.environ['PDI_USER'], os.environ['PDI_PASSWORD']),
                params={'sysparm_limit': 1, 'sysparm_fields': 'sys_id,name,short_description'},
                headers={'Accept': 'application/json'}, timeout=(10, 60))
            if response.status_code != 200:
                print(f'ServiceNow FAIL: HTTP {response.status_code}. '
                      'Check instance credentials and Table API permissions.')
                failed = True
            else:
                rows = response.json()['result']
                print(f'ServiceNow OK: authenticated; CMDB readable; sample records: {len(rows)}')
                for row in rows:
                    print(f"  {row['name']} (sys_id={row['sys_id']})")
        except (requests.RequestException, ValueError, KeyError):
            print('ServiceNow FAIL: request or response failed. Check URL, network/VPN, and instance availability.')
            failed = True
    if not args.servicenow_only:
        from kg.db import DB, driver
        try:
            driver.verify_connectivity()
            count = driver.execute_query('MATCH (n) RETURN count(n) AS count', database_=DB).records[0]['count']
            print(f'Neo4j OK: authenticated; database={DB}; nodes={count}')
        except (DriverError, Neo4jError, ValueError) as error:
            print(f'Neo4j FAIL: {type(error).__name__}. Check NEO4J_* settings and database availability.')
            failed = True
        finally:
            driver.close()
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
