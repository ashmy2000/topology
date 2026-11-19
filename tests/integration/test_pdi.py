import pytest
from dotenv import load_dotenv

from kg.pdi import ci_classes, fetch_table

load_dotenv()


# expected counts from the Aggregate API after the Bond Trading mock (mock): 36 classes, 2,788 CIs, 271 rows
def test_ci_classes_cover_every_ci():
    classes = ci_classes()
    assert 36 == len(classes)
    assert 2788 == sum(classes.values())


@pytest.mark.parametrize('table, query, expected', [
    ('cmdb_rel_ci', '', 271),
    ('cmdb_ci_win_server', 'sys_class_name=cmdb_ci_win_server', 8),
])
def test_fetch_table_returns_every_row_once(table, query, expected):
    rows, total = fetch_table(table, query)
    assert expected == total
    assert expected == len(rows)
    assert expected == len({row['sys_id']['value'] for row in rows})
    assert all({'value', 'display_value'} <= field.keys() for row in rows for field in row.values())


def test_class_table_returns_more_fields_than_cmdb_ci():
    base_rows, _ = fetch_table('cmdb_ci', 'sys_class_name=cmdb_ci_win_server')
    class_rows, _ = fetch_table('cmdb_ci_win_server', 'sys_class_name=cmdb_ci_win_server')
    assert 82 == len(base_rows[0])
    assert 113 == len(class_rows[0])
