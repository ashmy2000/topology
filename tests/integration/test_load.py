from kg.db import DB, driver
from kg.load_pdi import counts


# Expected values from the files in out/pdi/ (2,788 CI rows, 271 cmdb_rel_ci rows, 19 server/db_server
# fields not already recorded as a relationship row) and out/model_v1/merged.py ("Server 42").
def test_graph_holds_every_record_with_class_labels(graph):
    nodes, _ = counts()
    assert {'CI': 2788, 'Server': 42, 'Group': 54, 'Person': 643, 'Location': 427, 'Incident': 67, 'Alert': 11} == nodes


def test_ci_links_come_from_relationship_rows_and_hosting_fields(graph):
    rows = driver.execute_query("""
        MATCH (:CI)-[r]->(:CI)
        RETURN r.src_table = 'cmdb_rel_ci' AS from_rel_table, count(r) AS n
        """, database_=DB).records
    assert {True: 271, False: 19} == {r['from_rel_table']: r['n'] for r in rows}


def test_every_node_and_relationship_carries_provenance(graph):
    missing = driver.execute_query("""
        MATCH (n) WHERE n.src_system IS NULL OR n.src_table IS NULL OR n.extracted_at IS NULL OR n.load_run IS NULL
        RETURN count(n) AS n
        UNION ALL
        MATCH ()-[r]->() WHERE r.src_system IS NULL OR r.src_sys_id IS NULL OR r.load_run IS NULL
        RETURN count(r) AS n
        """, database_=DB).records
    assert [0, 0] == [r['n'] for r in missing]


def test_backwards_location_rows_point_from_room_to_data_centre(graph):
    rows = driver.execute_query("""
        MATCH (room)-[:LOCATED_IN {reversed: true}]->(dc) RETURN room.name AS room, dc.name AS dc ORDER BY room
        """, database_=DB).records
    assert [('NY Floor 1', 'New York'), ('NY Floor 2', 'New York')] == [(r['room'], r['dc']) for r in rows]
