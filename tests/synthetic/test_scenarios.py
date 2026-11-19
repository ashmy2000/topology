"""Exercise the API and its real Cypher against the seeded synthetic graph."""

import os

import pytest
from fastapi.testclient import TestClient
from neo4j import GraphDatabase, NotificationDisabledClassification

from kg import outage
from kg.api import app
from kg.synthetic_fixture import DATABASE, URI, aura_settings, load_fixture

KEY = 'vesperloom-local-fixture-test-key'
HEADERS = {'X-API-Key': KEY}


@pytest.fixture
def client(monkeypatch):
    if os.getenv('SYNTHETIC_TEST_AURA') == '1':
        uri, database, auth = aura_settings()
    else:
        password = os.getenv('SYNTHETIC_NEO4J_PASSWORD')
        if not password:
            pytest.skip('Set SYNTHETIC_NEO4J_PASSWORD after seeding the disposable database')
        uri, database, auth = URI, DATABASE, ('neo4j', password)
    with GraphDatabase.driver(
        uri, auth=auth, connection_timeout=5,
        notifications_disabled_classifications=[NotificationDisabledClassification.UNRECOGNIZED],
    ) as driver:
        monkeypatch.setattr(outage, 'driver', driver)
        monkeypatch.setattr(outage, 'DB', database)
        monkeypatch.setenv('IMPACT_API_KEY', KEY)
        with TestClient(app) as test_client:
            yield test_client


def id_of(name):
    nodes, _, _ = load_fixture()
    return next(node['props']['sys_id'] for node in nodes if node['props'].get('name') == name)


def test_seeded_graph_counts_and_labels(client):
    assert client.get('/ready').json() == {'status': 'ready'}
    assert outage.run_read('MATCH (n) RETURN count(n) AS total') == [{'total': 13}]
    assert outage.run_read('MATCH (n:CI) RETURN count(n) AS total') == [{'total': 8}]
    observed = outage.run_read('MATCH ()-[r]->() RETURN type(r) AS kind, count(*) AS total')
    assert {row['kind']: row['total'] for row in observed} == {
        'DEPENDS_ON': 4, 'MEMBERS': 3, 'CONSUMES': 2, 'DR_PROVIDED_BY': 1,
        'RECEIVES_DATA_FROM': 1, 'SUPPORT_GROUP': 5, 'ON': 2, 'GROUPED_UNDER': 1,
    }
    labels = outage.run_read('MATCH (n) UNWIND labels(n) AS label RETURN DISTINCT label')
    assert {row['label'] for row in labels} == {
        'CI', 'StorageArray', 'Server', 'Cluster', 'Service', 'BusinessApplication',
        'Group', 'Alert', 'SyntheticTopologyDemo',
    }


@pytest.mark.parametrize(
    'seed, status, down_names, risk_names, team, path_tail',
    [
        (
            'Vesperloom Primary Array', 'down',
            [
                'Vesperloom Database A', 'Vesperloom Database B', 'Vesperloom Database C',
                'Vesperloom Database Cluster', 'Lantern Ledger Primary Service', 'Lantern Ledger',
            ],
            [], 'Vesperloom Array Operations', ['MEMBERS', 'DEPENDS_ON'],
        ),
        (
            'Vesperloom Database A', 'at risk', [],
            ['Vesperloom Database Cluster', 'Lantern Ledger Primary Service', 'Lantern Ledger'],
            'Vesperloom Database Operations', ['MEMBERS'],
        ),
    ],
)
def test_synthetic_failure(client, seed, status, down_names, risk_names, team, path_tail):
    response = client.get('/api/v1/cis/search', params={'query': seed}, headers=HEADERS)
    assert response.status_code == 200
    search = response.json()
    assert not search['truncated']
    assert len(search['candidates']) == 1
    candidate = search['candidates'][0]
    assert candidate['name'] == seed
    seed_id = candidate['sys_id']
    assert seed_id == id_of(seed)
    assert candidate['source_table'].startswith('synthetic_')

    response = client.post('/api/v1/impact', json={'ci_id': seed_id}, headers=HEADERS)
    assert response.status_code == 200
    impact = response.json()
    assert impact['failed_ci'] == candidate
    assert impact['additional_cis_down'] == len(down_names)
    assert set(impact['down_ci_ids']) == {id_of(name) for name in down_names}
    assert set(impact['at_risk_ci_ids']) == {id_of(name) for name in risk_names}
    expected_clusters = [] if down_names else [{
        'sys_id': id_of('Vesperloom Database Cluster'),
        'name': 'Vesperloom Database Cluster', 'hosts_down': 1, 'hosts_total': 3,
    }]
    assert impact['degraded_clusters'] == expected_clusters

    items = {item['name']: item for item in impact['affected']}
    assert set(items) == {'Lantern Ledger', 'Lantern Ledger Primary Service'}
    application = items['Lantern Ledger']
    service = items['Lantern Ledger Primary Service']
    assert application['kind'] == 'business application'
    assert service['kind'] == 'service'
    assert application['status'] == service['status'] == status
    assert application['ownership']['contact'] == 'Lantern Ledger Support'
    assert service['ownership']['status'] == 'missing'
    assert application['dr_copy'] == 'Lantern Ledger Recovery Service'
    assert application['dr_status'] == ('up, data current only to the failure' if down_names else 'up')

    assert impact['fix']['contact'] == team
    assert impact['fix']['status'] == 'recorded'
    for ci_id, ownership in [
        (seed_id, impact['fix']), (application['sys_id'], application['ownership']),
        (service['sys_id'], service['ownership']),
    ]:
        response = client.get(f'/api/v1/cis/{ci_id}/ownership', headers=HEADERS)
        assert response.status_code == 200
        assert response.json()['contacts'] == [ownership]

    path = application['path']
    assert path['names'][0] == 'Lantern Ledger'
    assert path['names'][-1] == seed
    assert path['types'] == ['CONSUMES', 'DEPENDS_ON', *path_tail]
    nodes, edges, _ = load_fixture()
    nodes_by_name = {node['props'].get('name'): node['props'] for node in nodes}
    edges_by_key = {(edge['start'], edge['type'], edge['end']): edge['props'] for edge in edges}
    expected_nodes = [nodes_by_name[name] for name in path['names']]
    assert path['node_records'] == [[node['src_table'], node['sys_id']] for node in expected_nodes]
    expected_edges = [
        edges_by_key[start['sys_id'], kind, end['sys_id']]
        for start, kind, end in zip(expected_nodes, path['types'], expected_nodes[1:])
    ]
    assert path['link_records'] == [[edge['src_table'], edge['src_sys_id']] for edge in expected_edges]
    assert impact['ownership_gap_ci_ids'] == [service['sys_id']]
    assert impact['uncertainty'] == ['Some CIs have no support contact in the available graph.']
    assert impact['human_review_required'] is True

    alerts = {alert['alert']: alert for alert in impact['alerts']}
    assert set(alerts) == {'SYN-ALERT-001', 'SYN-ALERT-002'}
    assert alerts['SYN-ALERT-001']['on_trace'] == bool(down_names)
    assert alerts['SYN-ALERT-002']['on_trace']
    assert alerts['SYN-ALERT-002']['grouped_under'] == 'SYN-ALERT-001'
