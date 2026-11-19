import re
from unittest.mock import Mock

import pytest

from kg import synthetic_fixture
from kg.synthetic_fixture import APPROVED_SHA256, load_fixture


def test_fixture_materializes_stable_ids_and_synthetic_provenance():
    nodes, relationships, checksum = load_fixture()
    assert (nodes, relationships, checksum) == load_fixture()
    assert checksum == APPROVED_SHA256
    assert (len(nodes), len(relationships)) == (13, 19)
    assert sum('CI' in node['labels'] for node in nodes) == 8
    node_ids = {node['props']['sys_id'] for node in nodes}
    edge_ids = {edge['props']['src_sys_id'] for edge in relationships}
    assert len(node_ids | edge_ids) == 32
    assert all(re.fullmatch(r'[0-9a-f]{32}', value) for value in node_ids | edge_ids)
    assert all({edge['start'], edge['end']} <= node_ids for edge in relationships)
    for entry in nodes + relationships:
        assert entry['props']['src_system'] == 'synthetic'
        assert entry['props']['src_instance'] == 'vesperloom-v1'
        assert entry['props']['src_table'].startswith('synthetic_')


def test_aura_import_is_pinned_to_the_approved_target(monkeypatch, tmp_path):
    monkeypatch.setattr('sys.argv', ['synthetic_fixture', 'import-aura', '--confirm-instance', '99908d7e'])
    settings = tmp_path / '.env'
    settings.write_text(
        'SYNTHETIC_AURA_URI=neo4j+s://99908d7e.databases.neo4j.io\n'
        'SYNTHETIC_AURA_DATABASE=99908d7e\n'
        'SYNTHETIC_AURA_USER=fixture-user\n'
        'SYNTHETIC_AURA_PASSWORD=fixture-password\n'
        'NEO4J_URI=bolt://127.0.0.1:7687\n'
    )
    monkeypatch.setattr(synthetic_fixture, 'ENV_FILE', settings)
    monkeypatch.setenv('NEO4J_URI', 'bolt://127.0.0.1:7687')
    seed = Mock()
    monkeypatch.setattr(synthetic_fixture, 'seed_database', seed)
    synthetic_fixture.main()
    nodes, links, _ = load_fixture()
    seed.assert_called_once_with(
        'neo4j+s://99908d7e.databases.neo4j.io', '99908d7e', ('fixture-user', 'fixture-password'), nodes, links,
    )


@pytest.mark.parametrize('instance', ['99908d7e', 'wrong-id'])
def test_aura_import_refuses_modified_fixture_or_wrong_instance(monkeypatch, tmp_path, capsys, instance):
    fixture = tmp_path / 'fixture.json'
    fixture.write_bytes(synthetic_fixture.FIXTURE.read_bytes() + b'\n')
    monkeypatch.setattr(synthetic_fixture, 'FIXTURE', fixture)
    monkeypatch.setattr('sys.argv', ['synthetic_fixture', 'import-aura', '--confirm-instance', instance])
    seed = Mock()
    monkeypatch.setattr(synthetic_fixture, 'seed_database', seed)
    with pytest.raises(SystemExit):
        synthetic_fixture.main()
    assert ('SHA-256' if instance == '99908d7e' else 'requires --confirm-instance') in capsys.readouterr().err
    seed.assert_not_called()


def test_import_stops_before_writing_to_nonempty_database():
    transaction = Mock()
    transaction.run.return_value.single.side_effect = [{'total': 1}, {'total': 0}]
    with pytest.raises(ValueError, match='Target must be empty'):
        synthetic_fixture.create_fixture(transaction, [], [])
    assert [call.args[0] for call in transaction.run.call_args_list] == [
        'MATCH (n) RETURN count(n) AS total',
        'MATCH ()-[r]->() RETURN count(r) AS total',
    ]
