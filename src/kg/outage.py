"""Outage impact: if a CI or a site fails, which business applications and services break, and who do we call?

Runs the step queries in queries/ against the graph loaded by kg/load_pdi.py.
Set CI (or, for a site outage, empty CI and set SITE) below, then run the file in PyCharm.
Prints a table and writes the result as JSON to out/outage/.
"""
import json
import re
from pathlib import Path

from neo4j import Query, RoutingControl

from kg.db import DB, driver

QUERIES = Path(__file__).resolve().parents[2] / 'queries'
OUT_DIR = Path(__file__).resolve().parents[2] / 'out' / 'outage'
CI = 'nyc rac nas200'  # sys_id or unique name of the failed CI
SITE = '450 Lexington Avenue, New York,NY'  # cmn_location name of a failed site; used when CI is empty


def run_read(cypher, **params):
    result = driver.execute_query(
        Query(cypher, timeout=5), params, database_=DB, routing_=RoutingControl.READ,
    )
    return [record.data() for record in result.records]


def run(query, **params):
    return run_read((QUERIES / f'{query}.cypher').read_text(), **params)


def find_ci(key):
    """sys_id of the CI with this sys_id or name; a name shared by several CIs is refused with the candidates."""
    found = run('find_ci', key=key)
    assert 1 == len(found), f'{key!r} matches {len(found)} CIs: {found}'
    return found[0]['sys_id']


def walk(ids):
    return set(run('walk', ids=list(ids))[0]['ids'])


def impact(seeds):
    # walk, then take down every cluster whose members are all down, and walk again until nothing new is down
    down = walk(seeds)
    while True:
        clusters = run('cluster', down=list(down))
        all_down = {c['sys_id'] for c in clusters if c['all_down']}
        if not all_down:
            break
        down = walk(down | all_down)
    degraded = clusters
    at_risk = walk(c['sys_id'] for c in degraded) - down

    apps = run('business_apps', down=list(down), at_risk=list(at_risk))
    down |= {a['sys_id'] for a in apps if 'down' == a['status']}
    at_risk |= {a['sys_id'] for a in apps if 'down' != a['status']}
    services = run('services', down=list(down), at_risk=list(at_risk))

    hit = down | at_risk | {c['sys_id'] for c in degraded}
    calls = {c['sys_id']: c for c in run('who_to_call', ids=list(seeds) + [x['sys_id'] for x in apps + services])}
    for x in apps + services:
        x |= calls[x['sys_id']]
        paths = run('path', start=x['sys_id'], seeds=list(seeds), hit=list(hit))
        x['path'] = next(iter(paths), None)
    return {
        'fix': sorted((calls[s] for s in seeds), key=lambda row: row['ci_name']),
        'inform': apps + services,
        'degraded_clusters': degraded,
        'alerts': run('alerts', down=list(down)),
        'down': sorted(down),
        'at_risk': sorted(at_risk),
        'beyond_seeds': len(down - set(seeds)),
    }


def names(ids):
    return [r['name'] for r in driver.execute_query(
        'MATCH (c:CI) WHERE c.sys_id IN $ids RETURN c.name AS name ORDER BY name', ids=list(ids), database_=DB).records]


def show(title, result):
    print(f"== {title}: {len(result['fix'])} failed, {result['beyond_seeds']} CIs down beyond them, "
          f"{len(result['at_risk'])} at risk")
    print('FIX')
    for row in result['fix']:
        print(f"  {row['ci_name']:40} {row['call']} ({row['route']})")
    print('INFORM')
    for row in result['inform']:
        dr = f", DR copy {row['dr_copy']}: {row['dr_status']}" if row.get('dr_copy') else ''
        print(f"  {row['kind']:21} {row['name']:36} {row['status']:22} {row['call']} ({row['route']}){dr}")
        path = ' > '.join(row['path']['names']) if row['path'] else 'no recorded dependency path'
        print(f"  {'':21} via {path}")
    for c in result['degraded_clusters']:
        print(f"DEGRADED cluster {c['name']}: {c['hosts_down']} of {c['hosts_total']} hosts down")
    for a in result['alerts']:
        where = 'on trace' if a['on_trace'] else f"off trace, linked: {'; '.join(a['links'])}"
        print(f"ALERT {a['alert']} {a['source']} {a['severity']} on {a['ci']}: {where}")
    if 'not_reached' in result:
        print(f"GAP at the site but on no dependency path: {', '.join(names(result['not_reached']))}")


def main():
    if CI:
        title = CI
        result = impact([find_ci(CI)])
    else:
        title = SITE
        site = run('site', site=SITE)[0]
        result = impact(site['seeds'])
        result['not_reached'] = sorted(set(site['located']) - set(result['down']) - set(result['at_risk']))
    show(title, result)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{re.sub(r'\W+', '_', title).strip('_').lower()}.json"
    path.write_text(json.dumps(result, indent=2, default=str))
    print(f'written: {path}')
    driver.close()


if '__main__' == __name__:
    main()
