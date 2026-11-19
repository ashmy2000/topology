"""Read-only CI lookup and response assembly around the existing outage rules."""

from kg.outage import impact, run, run_read


class UnknownCI(LookupError):
    """The requested ServiceNow CI identifier is absent from the graph."""


def search(query, limit):
    return run_read("""
        MATCH (c:CI)
        WITH c, toLower(coalesce(toString(c.name), '')) AS name,
             toLower(coalesce(toString(c.sys_class_name), '')) AS ci_type, toLower($query) AS term
        WHERE c.sys_id = $query OR name CONTAINS term OR ci_type CONTAINS term
        RETURN c.sys_id AS sys_id, toString(c.name) AS name, c.sys_class_name AS ci_type,
               c.src_table AS source_table
        ORDER BY CASE WHEN c.sys_id = $query OR name = term THEN 0
                      WHEN name STARTS WITH term THEN 1 ELSE 2 END, name, sys_id
        LIMIT $limit
        """, query=query, limit=limit)


def lookup(ci_id):
    rows = run_read("""
        MATCH (c:CI {sys_id: $ci_id})
        RETURN c.sys_id AS sys_id, toString(c.name) AS name, c.sys_class_name AS ci_type,
               c.src_table AS source_table
        """, ci_id=ci_id)
    if not rows:
        raise UnknownCI(ci_id)
    return rows[0]


def classify_owner(row):
    route = row['route']
    if route == 'none':
        status = 'missing'
    elif route in {'support_group', 'assignment_group', 'managed_by_group', 'managed_by'}:
        status = 'recorded'
    else:
        status = 'inferred'
    return {
        'contact': None if status == 'missing' else row['call'],
        'route': route,
        'status': status,
        'business_owner': row.get('business_owner'),
        'it_application_owner': row.get('it_application_owner'),
    }


def ownership(ci_id):
    ci = lookup(ci_id)
    routes = [classify_owner(row) for row in run('who_to_call', ids=[ci_id])]
    return {'ci': ci, 'contacts': routes}


def assess(ci_id):
    failed = lookup(ci_id)
    result = impact([ci_id])
    fix = classify_owner(result['fix'][0])
    affected = []
    gaps = [ci_id] if fix['status'] == 'missing' else []
    uncertainty = []
    for row in result['inform']:
        owner = classify_owner(row)
        affected.append({**row, 'ownership': owner})
        if owner['status'] == 'missing':
            gaps.append(row['sys_id'])
        if row['path'] is None:
            uncertainty.append(f"No dependency path found in the graph for CI {row['sys_id']}.")
    if gaps:
        uncertainty.append('Some CIs have no support contact in the available graph.')
    return {
        'failed_ci': failed,
        'fix': fix,
        'affected': affected,
        'down_ci_ids': [item for item in result['down'] if item != ci_id],
        'at_risk_ci_ids': result['at_risk'],
        'additional_cis_down': result['beyond_seeds'],
        'degraded_clusters': result['degraded_clusters'],
        'alerts': result['alerts'],
        'ownership_gap_ci_ids': gaps,
        'uncertainty': uncertainty,
        'human_review_required': True,
    }
