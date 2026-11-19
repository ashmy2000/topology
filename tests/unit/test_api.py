from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from neo4j import RoutingControl
from neo4j.exceptions import ServiceUnavailable

from kg import impact_service, outage
from kg.api import app

KEY = 'synthetic-test-key-for-the-topology-api'
STORAGE = 'a' * 32
SERVER = 'b' * 32
APPLICATION = 'c' * 32
HEADERS = {'X-API-Key': KEY}


def ci(ci_id, name, ci_type='cmdb_ci_server'):
    return {'sys_id': ci_id, 'name': name, 'ci_type': ci_type, 'source_table': ci_type}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('IMPACT_API_KEY', KEY)
    with TestClient(app) as client:
        yield client


def test_health_and_readiness(client, monkeypatch):
    read = Mock(return_value=[{'ready': 1}])
    monkeypatch.setattr('kg.api.run_read', read)
    assert client.get('/health').json() == {'status': 'ok'}
    assert client.get('/ready').json() == {'status': 'ready'}
    read.side_effect = ServiceUnavailable('private connection details')
    response = client.get('/ready')
    assert response.status_code == 503
    assert response.json() == {'detail': 'Graph database unavailable'}


@pytest.mark.parametrize('key', [None, 'wrong-key'])
def test_topology_endpoints_require_authentication(client, key):
    headers = {} if key is None else {'X-API-Key': key}
    assert client.get('/api/v1/cis/search?query=storage', headers=headers).status_code == 401
    assert client.post('/api/v1/impact', json={'ci_id': STORAGE}, headers=headers).status_code == 401
    assert client.get(f'/api/v1/cis/{STORAGE}/ownership', headers=headers).status_code == 401


def test_unconfigured_authentication_fails_closed(client, monkeypatch):
    monkeypatch.delenv('IMPACT_API_KEY')
    assert client.get('/api/v1/cis/search?query=storage', headers=HEADERS).status_code == 503


@pytest.mark.parametrize('count', [1, 2, 3])
def test_search_preserves_candidates_and_reports_truncation(client, monkeypatch, count):
    matches = [ci(f'{i:032x}', 'Oracle DB') for i in range(count)]
    read = Mock(return_value=matches)
    monkeypatch.setattr(impact_service, 'run_read', read)
    response = client.get('/api/v1/cis/search?query=Oracle&limit=2', headers=HEADERS)
    assert response.json() == {'candidates': matches[:2], 'truncated': count > 2}
    assert read.call_args.kwargs == {'query': 'Oracle', 'limit': 3}
    assert 'LIMIT $limit' in read.call_args.args[0]
    assert client.get('/api/v1/cis/search?query=Oracle&limit=51', headers=HEADERS).status_code == 422
    assert client.get('/api/v1/cis/search?query=%20%20', headers=HEADERS).status_code == 422


def test_unknown_and_invalid_ci(client, monkeypatch):
    monkeypatch.setattr(impact_service, 'run_read', Mock(return_value=[]))
    for ci_id, status in [(STORAGE, 404), ('not-an-id', 422)]:
        assert client.post('/api/v1/impact', json={'ci_id': ci_id}, headers=HEADERS).status_code == status
        assert client.get(f'/api/v1/cis/{ci_id}/ownership', headers=HEADERS).status_code == status


def call(ci_id, name, contact, route):
    return {'sys_id': ci_id, 'ci_name': name, 'call': contact, 'route': route}


def test_ownership_inference(client, monkeypatch):
    monkeypatch.setattr(impact_service, 'lookup', Mock(return_value=ci(SERVER, 'Database server')))
    monkeypatch.setattr(impact_service, 'run', Mock(return_value=[call(SERVER, 'Database server', 'Ops', 'incident 1')]))
    response = client.get(f'/api/v1/cis/{SERVER}/ownership', headers=HEADERS)
    assert response.status_code == 200
    assert response.json()['contacts'][0]['status'] == 'inferred'


@pytest.mark.parametrize('seed, status, path_present', [(STORAGE, 'down', True), (SERVER, 'at risk', False)])
def test_search_id_can_be_used_for_impact_and_preserves_evidence(client, monkeypatch, seed, status, path_present):
    seed_name = 'Storage array' if seed == STORAGE else 'Database server'
    failed = ci(seed, seed_name)
    path = {
        'names': ['Bond Trading', seed_name], 'types': ['DEPENDS_ON'],
        'node_records': [['cmdb_ci_business_app', APPLICATION], ['cmdb_ci_server', seed]],
        'link_records': [['cmdb_rel_ci', 'd' * 32]],
    }
    def read(cypher, **params):
        if 'LIMIT $limit' in cypher:
            return [failed] if params['query'] == seed_name else []
        return [failed] if params['ci_id'] == seed else []

    monkeypatch.setattr(impact_service, 'run_read', read)

    def query(name, **params):
        return {
            'walk': [{'ids': [seed]}] if params.get('ids') else [{'ids': []}],
            'cluster': [],
            'business_apps': [{'sys_id': APPLICATION, 'name': 'Bond Trading', 'kind': 'business application', 'status': status}],
            'services': [],
            'who_to_call': [call(seed, seed_name, 'Hardware', 'support_group'),
                            call(APPLICATION, 'Bond Trading', 'UNKNOWN', 'none')],
            'path': [path] if path_present else [],
            'alerts': [],
        }[name]

    monkeypatch.setattr(outage, 'run', query)
    search = client.get('/api/v1/cis/search', params={'query': seed_name}, headers=HEADERS)
    assert search.status_code == 200
    returned_id = search.json()['candidates'][0]['sys_id']
    res = client.post('/api/v1/impact', json={'ci_id': returned_id}, headers=HEADERS)
    assert res.status_code == 200
    data = res.json()
    assert data['failed_ci'] == failed
    assert data['affected'][0]['status'] == status
    assert data['affected'][0]['path'] == (path if path_present else None)
    assert data['fix']['status'] == 'recorded'
    assert data['ownership_gap_ci_ids'] == [APPLICATION]
    assert data['human_review_required']
    assert any('No dependency path' in item for item in data['uncertainty']) != path_present
    outage.show(seed_name, outage.impact([seed]))


def test_read_runner_uses_read_routing_parameters_and_timeout(monkeypatch):
    driver = Mock()
    driver.execute_query.return_value.records = []
    monkeypatch.setattr(outage, 'driver', driver)
    impact_service.search("sample' text", 3)
    args, kwargs = driver.execute_query.call_args
    assert kwargs['routing_'] == RoutingControl.READ
    assert args[0].timeout == 5
    assert args[1] == {'query': "sample' text", 'limit': 3}
    assert '$query' in args[0].text
