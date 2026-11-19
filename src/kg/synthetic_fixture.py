"""Validate the independent demo fixture or seed its designated Neo4j database."""

import argparse
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid5

from dotenv import dotenv_values
from neo4j import GraphDatabase
from neo4j.exceptions import DriverError, Neo4jError

FIXTURE = Path(__file__).resolve().parents[2] / 'fixtures' / 'topology-synthetic.json'
ENV_FILE = FIXTURE.parents[1] / '.env'
URI = 'bolt://127.0.0.1:17687'
DATABASE = 'topologysynthetic'
AURA_INSTANCE_ID = '99908d7e'
AURA_URI = f'neo4j+s://{AURA_INSTANCE_ID}.databases.neo4j.io'
AURA_DATABASE = '99908d7e'  # Confirmed by db.info() on the default Bolt session.
APPROVED_SHA256 = 'c5eaf16b82ab0cc2c892c9bdda0ed749b2d6208b92968bd2e61bf3a43fc98485'
LABEL = 'SyntheticTopologyDemo'
LABELS = {'CI', 'StorageArray', 'Server', 'Cluster', 'Service', 'BusinessApplication', 'Group', 'Alert'}
RELATIONSHIP_TYPES = {
    'DEPENDS_ON', 'MEMBERS', 'CONSUMES', 'DR_PROVIDED_BY', 'RECEIVES_DATA_FROM',
    'SUPPORT_GROUP', 'ON', 'GROUPED_UNDER',
}


def load_fixture(expected_checksum=None):
    payload = FIXTURE.read_bytes()
    checksum = hashlib.sha256(payload).hexdigest()
    if expected_checksum is not None and checksum != expected_checksum:
        raise ValueError('Fixture SHA-256 does not match the approved checksum.')
    fixture = json.loads(payload)
    namespace = UUID(fixture['namespace'])
    provenance = {'src_system': 'synthetic', 'src_instance': fixture['name']}
    ids = {key: uuid5(namespace, f'node:{key}').hex for key in fixture['nodes']}
    nodes = []
    for key, node in fixture['nodes'].items():
        labels = node['labels']
        if not labels or len(labels) != len(set(labels)) or set(labels) - LABELS:
            raise ValueError(f'Invalid labels for {key}')
        props = node['properties']
        if 'CI' in labels and 'sys_class_name' not in props:
            raise ValueError(f'Missing CI class for {key}')
        source_table = props.get('sys_class_name', f'synthetic_{labels[0].lower()}')
        nodes.append({
            'labels': labels,
            'props': {**props, **provenance, 'sys_id': ids[key], 'src_table': source_table},
        })

    relationships = []
    seen = set()
    for start, kind, end in fixture['relationships']:
        edge = (start, kind, end)
        if edge in seen or kind not in RELATIONSHIP_TYPES or start not in ids or end not in ids:
            raise ValueError(f'Invalid or duplicate relationship {edge}')
        seen.add(edge)
        relationships.append({
            'start': ids[start], 'end': ids[end], 'type': kind,
            'props': {
                **provenance, 'src_table': 'synthetic_relationship',
                'src_sys_id': uuid5(namespace, f'edge:{start}:{kind}:{end}').hex,
            },
        })
    return nodes, relationships, checksum


def require_empty(tx):
    nodes = tx.run('MATCH (n) RETURN count(n) AS total').single(strict=True)['total']
    relationships = tx.run('MATCH ()-[r]->() RETURN count(r) AS total').single(strict=True)['total']
    if nodes != 0 or relationships != 0:
        raise ValueError(f'Target must be empty. Found {nodes} nodes and {relationships} relationships.')


def create_fixture(tx, nodes, relationships):
    require_empty(tx)
    summary = tx.run(f'''
        UNWIND $nodes AS row
        CREATE (n:{LABEL})
        SET n = row.props, n:$(row.labels)
    ''', nodes=nodes).consume()
    if summary.counters.nodes_created != len(nodes):
        raise ValueError('The fixture node count did not match. Import rolled back.')
    summary = tx.run(f'''
        UNWIND $relationships AS row
        MATCH (a:{LABEL} {{sys_id: row.start}}), (b:{LABEL} {{sys_id: row.end}})
        CREATE (a)-[r:$(row.type)]->(b)
        SET r = row.props
    ''', relationships=relationships).consume()
    if summary.counters.relationships_created != len(relationships):
        raise ValueError('The fixture relationship count did not match. Import rolled back.')


def seed_database(uri, database, auth, nodes, relationships):
    with (
        GraphDatabase.driver(uri, auth=auth, connection_timeout=5) as driver,
        driver.session(database=database) as session,
    ):
        if session.run('CALL db.info() YIELD name RETURN name').single(strict=True)['name'] != database:
            raise ValueError('Unexpected database name.')
        session.execute_read(require_empty)
        print(f'Confirmed database {database} has 0 nodes and 0 relationships.', flush=True)
        # Competing imports use the same IDs. The constraint makes the losing transaction roll back.
        session.run(f'''
            CREATE CONSTRAINT synthetic_topology_demo_id IF NOT EXISTS
            FOR (n:{LABEL}) REQUIRE n.sys_id IS UNIQUE
        ''').consume()
        session.execute_write(create_fixture, nodes, relationships)


def aura_settings():
    settings = dotenv_values(ENV_FILE, interpolate=False)
    uri = settings.get('SYNTHETIC_AURA_URI')
    database = settings.get('SYNTHETIC_AURA_DATABASE')
    user = settings.get('SYNTHETIC_AURA_USER')
    password = settings.get('SYNTHETIC_AURA_PASSWORD')
    if uri != AURA_URI or database != AURA_DATABASE:
        raise ValueError('The Aura URI and database in .env must match the approved target.')
    if not user or not password:
        raise ValueError('Set SYNTHETIC_AURA_USER and SYNTHETIC_AURA_PASSWORD in .env.')
    return uri, database, (user, password)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['validate', 'import-local', 'import-aura'])
    parser.add_argument('--confirm-instance', help='Required Aura instance ID for import-aura')
    args = parser.parse_args()
    is_aura = args.action == 'import-aura'
    if is_aura and args.confirm_instance != AURA_INSTANCE_ID:
        parser.error(f'import-aura requires --confirm-instance {AURA_INSTANCE_ID}')
    try:
        nodes, relationships, checksum = load_fixture(APPROVED_SHA256 if is_aura else None)
        ci_count = sum('CI' in node['labels'] for node in nodes)
        print(f'{FIXTURE.name}  SHA-256 {checksum}')
        print(f'{len(nodes)} nodes ({ci_count} CIs), {len(relationships)} relationships')
        if args.action == 'import-local':
            password = os.environ.get('SYNTHETIC_NEO4J_PASSWORD')
            if not password:
                raise ValueError('Set SYNTHETIC_NEO4J_PASSWORD for the disposable server.')
            seed_database(URI, DATABASE, ('neo4j', password), nodes, relationships)
            print('Fixture imported into the disposable database.')
        elif is_aura:
            if (len(nodes), ci_count, len(relationships)) != (13, 8, 19):
                raise ValueError('Fixture graph counts do not match the approved counts.')
            uri, database, auth = aura_settings()
            print(f'Target: {uri}, database {database}', flush=True)
            seed_database(uri, database, auth, nodes, relationships)
            print('Fixture imported into the designated AuraDB database.')
    except (ValueError, DriverError, Neo4jError) as exc:
        if isinstance(exc, (DriverError, Neo4jError)):
            parser.exit(1, f'Neo4j operation failed ({type(exc).__name__}).\n')
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
