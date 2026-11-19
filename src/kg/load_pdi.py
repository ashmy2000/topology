"""Load the ServiceNow extract in out/pdi/ into Neo4j as the graph model in kg/mapping.py.

The graph is rebuilt from scratch on every run. Run kg/pdi.py first.
"""
import json
import re
from collections import Counter
from datetime import UTC, datetime

from kg.db import DB, driver
from kg.mapping import (
    NODE_FIELDS,
    NODE_TABLES,
    PLACE_RANK,
    REFERENCES,
    RELATIONSHIP_TABLES,
    graph_type,
)
from kg.pdi import OUT_DIR

DATETIME = re.compile(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')
# no leading zero, so codes such as a zip '02134' stay strings
NUMBER = re.compile(r'-?(0|[1-9]\d*)(\.\d+)?')


def read(table):
    return json.loads((OUT_DIR / f'{table}.json').read_text())


def class_labels(tables, names):
    """Class name -> one label per class level, e.g. cmdb_ci_linux_server -> [LinuxServer, Server, Computer, Hardware, CI].

    Only for the classes in `names`: other cmdb* tables in the catalogue extend tables outside the extract.
    """
    by_sys_id = {t['sys_id']['value']: t for t in tables}
    by_name = {t['name']['value']: t for t in tables}
    labels = {}
    for name in names:
        chain, table = [], by_name[name]
        # the root class cmdb has no parent and no label of its own
        while table['super_class']['value']:
            label = table['label']['value']
            chain.append('CI' if 'Configuration Item' == label else re.sub(r'\W', '', label))
            table = by_sys_id[table['super_class']['value']]
        labels[name] = chain
    return labels


def properties(record, fields=None):
    """Every filled field, typed. Reference fields keep the name they point to."""
    props = {}
    for name, field in record.items():
        value, label = field['value'], field['display_value']
        if not value or (fields and name not in fields):
            continue
        if 'link' in field:
            props[name] = label
        elif DATETIME.fullmatch(value):
            props[name] = datetime.fromisoformat(value).replace(tzinfo=UTC)
        elif value in ('true', 'false'):
            props[name] = 'true' == value
        elif NUMBER.fullmatch(value) and label.replace(',', '') == value:
            props[name] = float(value) if '.' in value else int(value)
        else:
            props[name] = value
            if label != value:
                props[f'{name}_label'] = label
    return props


def link_rows(table, record, known, source):
    """The mapped reference fields of one record: relationship rows, plus the fields whose target is not loaded."""
    rows, dangling = [], []
    for field, (rel, target) in REFERENCES[table].items():
        value = record.get(field, {'value': ''})['value']
        if not value:
            continue
        if value in known[target]:
            rows.append({'start': record['sys_id']['value'], 'end': value, 'type': rel,
                         'props': {**source, 'src_sys_id': record['sys_id']['value'], 'src_field': field}})
        else:
            dangling.append(field)
    return rows, dangling


def relationship_row(table, row, labels, provenance):
    """One row of cmdb_rel_ci / cmdb_rel_person / cmdb_rel_group as a relationship from the parent's view."""
    parent_field, child_field, _ = RELATIONSHIP_TABLES[table]
    parent, child = row[parent_field]['value'], row[child_field]['value']
    sn_type = row['type']['display_value']
    props = {**provenance, 'src_table': table, 'src_sys_id': row['sys_id']['value'], 'sn_type': sn_type}
    rel = graph_type(sn_type)
    if 'LOCATED_IN' == rel and rank(labels[parent]) > rank(labels[child]):
        parent, child = child, parent
        props['reversed'] = True
    return {'start': parent, 'end': child, 'type': rel, 'props': props}


def rank(labels):
    return max(PLACE_RANK.get(label, 0) for label in labels)


def merge_nodes(label, rows):
    # label comes from the mapping config, never from the data
    driver.execute_query(f"""
        UNWIND $rows AS row
        MERGE (n:{label} {{sys_id: row.sys_id}})
        SET n = row.props, n:$(row.labels)
        """, rows=rows, database_=DB)


def create_relationships(start, end, rows):
    summary = driver.execute_query(f"""
        UNWIND $rows AS row
        MATCH (a:{start} {{sys_id: row.start}}), (b:{end} {{sys_id: row.end}})
        CREATE (a)-[r:$(row.type)]->(b)
        SET r = row.props
        """, rows=rows, database_=DB).summary
    assert len(rows) == summary.counters.relationships_created, (start, end)


def load():
    provenance = {**json.loads((OUT_DIR / 'manifest.json').read_text()),
                  'load_run': datetime.now(UTC).isoformat(timespec='seconds')}
    records = {table: read(table) for table in NODE_TABLES}
    records['cmdb_ci'] = [ci for path in sorted((OUT_DIR / 'ci').glob('*.json')) for ci in json.loads(path.read_text())]
    labels = class_labels(read('sys_db_object'), {ci['sys_class_name']['value'] for ci in records['cmdb_ci']})
    node_label = {**NODE_TABLES, 'cmdb_ci': 'CI'}
    known = {node_label[table]: {r['sys_id']['value'] for r in rows} for table, rows in records.items()}
    ci_labels = {ci['sys_id']['value']: labels[ci['sys_class_name']['value']] for ci in records['cmdb_ci']}

    # nodes: every field except the mapped references, which become relationships below
    links = []
    nodes = {}
    for table, rows in records.items():
        nodes[table] = []
        for record in rows:
            # a CI comes from the table of its own class
            source = {**provenance, 'src_table': record['sys_class_name']['value'] if 'cmdb_ci' == table else table}
            rows_out, dangling = link_rows(table, record, known, source) if table in REFERENCES else ([], [])
            links += rows_out
            props = properties({k: v for k, v in record.items() if k not in REFERENCES.get(table, {})},
                               NODE_FIELDS.get(table))
            props |= {f'{field}_sys_id': record[field]['value'] for field in dangling}
            if dangling:
                props['dangling_refs'] = dangling
            props |= source
            sys_id = record['sys_id']['value']
            nodes[table].append({'sys_id': sys_id, 'labels': ci_labels.get(sys_id, []), 'props': props})

    relationships = [relationship_row(table, row, ci_labels, provenance)
                     for table in RELATIONSHIP_TABLES for row in read(table)]
    # a reference field may repeat a relationship row (cluster node -> server): keep the row, skip the field
    recorded = {(r['start'], r['end'], r['type']) for r in relationships}
    links = [link for link in links if (link['start'], link['end'], link['type']) not in recorded]

    driver.execute_query('MATCH (n) DETACH DELETE n', database_=DB)
    for label in node_label.values():
        driver.execute_query(f'CREATE CONSTRAINT {label.lower()}_sys_id IF NOT EXISTS '
                             f'FOR (n:{label}) REQUIRE n.sys_id IS UNIQUE', database_=DB)
    for table, rows in nodes.items():
        merge_nodes(node_label[table], rows)

    label_of = {sys_id: label for label, ids in known.items() for sys_id in ids}
    by_labels = {}
    for rel in relationships + links:
        by_labels.setdefault((label_of[rel['start']], label_of[rel['end']]), []).append(rel)
    for (start, end), rows in by_labels.items():
        create_relationships(start, end, rows)
    return Counter(rel['type'] for rel in relationships + links)


def counts():
    """Nodes per kind and relationships per type, as Neo4j holds them."""
    nodes = {r['label']: r['n'] for r in driver.execute_query("""
        UNWIND ['CI', 'Server', 'Group', 'Person', 'Location', 'Incident', 'Alert'] AS label
        MATCH (n:$(label))
        RETURN label, count(n) AS n
        """, database_=DB).records}
    relationships = {r['type']: r['n'] for r in driver.execute_query(
        'MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS n', database_=DB).records}
    return nodes, relationships


def main():
    load()
    nodes, relationships = counts()
    print(f'nodes: {nodes}')
    print(f'relationships ({sum(relationships.values())}): {dict(sorted(relationships.items()))}')
    driver.close()


if '__main__' == __name__:
    main()
