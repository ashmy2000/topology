from datetime import UTC, datetime
from pathlib import Path

from kg.load_pdi import class_labels, link_rows, properties, relationship_row
from kg.mapping import WALKED, graph_type

QUERIES = Path(__file__).resolve().parents[2] / 'queries'


def field(value, display_value=None, link=None):
    f = {'value': value, 'display_value': value if display_value is None else display_value}
    if link:
        f['link'] = link
    return f


def table(sys_id, name, label, super_class=''):
    return {'sys_id': field(sys_id), 'name': field(name), 'label': field(label), 'super_class': field(super_class)}


def test_class_labels_give_one_label_per_level_without_the_root():
    tables = [table('1', 'cmdb', 'Base Configuration Item'), table('2', 'cmdb_ci', 'Configuration Item', '1'),
              table('3', 'cmdb_ci_server', 'Server', '2'), table('4', 'cmdb_ci_unix_server', 'UNIX Server', '3'),
              # extends a table outside the extract: never asked for, so never followed
              table('5', 'cmdb_ire_partial_payloads', 'Partial Payloads', '99')]
    assert {'cmdb_ci_unix_server': ['UNIXServer', 'Server', 'CI']} == class_labels(tables, {'cmdb_ci_unix_server'})


def test_properties_are_typed_from_the_table_api_strings():
    record = {
        'sys_updated_on': field('2026-09-14 21:41:12', '2026-09-14 22:41:12'),
        'virtual': field('false'),
        'cpu_speed': field('1993', '1,993'),
        'cost': field('1799.99', '1,799.99'),
        'zip': field('02134'),
        'install_status': field('1', 'Installed'),
        'manufacturer': field('b7e7', 'IBM', link='.../core_company/b7e7'),
        'ip_address': field(''),
    }
    props = properties(record)
    assert datetime(2026, 9, 14, 21, 41, 12, tzinfo=UTC) == props['sys_updated_on']
    assert props['virtual'] is False
    assert (1993, 1799.99) == (props['cpu_speed'], props['cost'])
    assert '02134' == props['zip']
    assert ('1', 'Installed') == (props['install_status'], props['install_status_label'])
    assert 'IBM' == props['manufacturer']
    assert 'ip_address' not in props


def test_properties_keep_only_allowed_fields():
    record = {'sys_id': field('u1'), 'name': field('A Person'), 'user_password': field('secret', '********')}
    assert {'sys_id': 'u1', 'name': 'A Person'} == properties(record, ['sys_id', 'name'])


def test_reference_to_a_record_not_in_the_extract_is_flagged_not_linked():
    record = {'sys_id': field('c1'), 'support_group': field('g1', 'Hardware'), 'location': field('gone', 'Old site')}
    rows, dangling = link_rows('cmdb_ci', record, {'Group': {'g1'}, 'Location': set()}, {'src_table': 't'})
    assert [('c1', 'g1', 'SUPPORT_GROUP', 'support_group')] == [
        (r['start'], r['end'], r['type'], r['props']['src_field']) for r in rows]
    assert ['location'] == dangling


def test_relationship_takes_the_parent_view_and_flips_a_backwards_location_row():
    rel = {'sys_id': field('r1'), 'parent': field('dc'), 'child': field('room'),
           'type': field('t1', 'Located In::Contains Room')}
    labels = {'dc': ['DataCenter', 'CI'], 'room': ['ComputerRoom', 'CI']}
    row = relationship_row('cmdb_rel_ci', rel, labels, {})
    # recorded data centre -> room; the room is located in the data centre
    assert ('room', 'dc', 'LOCATED_IN', True) == (row['start'], row['end'], row['type'], row['props']['reversed'])
    assert 'DEPENDS_ON' == graph_type('Depends on::Used by')
    assert 'LOG_REVIEWED_BY' == graph_type('Log reviewed by::Reviews logs for')


def test_walk_query_follows_exactly_the_walked_types_of_the_mapping():
    assert f"[:{'|'.join(WALKED)}]" in (QUERIES / 'walk.cypher').read_text()
