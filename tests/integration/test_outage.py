from kg.outage import find_ci, impact, run

# Expected values come from out/model_v1/merged.py, a separate Python model of the same rules run over the
# files in out/pdi/ without Neo4j: python3 -I out/model_v1/merged.py


def rows(result):
    return {(row['kind'], row['name']): (row['status'], row['call']) for row in result['inform']}


def test_storage_failure_takes_down_bond_trading_and_names_who_to_call(graph):
    result = impact([find_ci('nyc rac nas200')])
    assert 21 == result['beyond_seeds']
    assert [('nyc rac nas200', 'Hardware')] == [(row['ci_name'], row['call']) for row in result['fix']]
    assert {('business application', 'Bond Trading'): ('down', 'IT Securities'),
            ('service', 'Bond Trading'): ('down', 'IT Securities'),
            ('service', 'IT Services'): ('down', 'UNKNOWN'),
            ('service', 'Retail'): ('down', 'UNKNOWN'),
            ('service', 'Retail Adding Points'): ('down', 'UNKNOWN'),
            ('service', 'Retail POS (Point of Sale)'): ('down', 'UNKNOWN')} == rows(result)
    app = result['inform'][0]
    # the London standby receives its data from bond_trade_ny, which is down
    assert ('Bond Trading - DR', 'up, data current only to the failure') == (app['dr_copy'], app['dr_status'])
    assert ['Alert0010110', 'Alert0010111'] == [a['alert'] for a in result['alerts'] if not a['on_trace']]
    # acceptance criterion: every item and link on the chain names the ServiceNow record it came from
    assert ['cmdb_ci_business_app', 'cmdb_ci_service', 'cmdb_ci_database', 'cmdb_ci_database', 'cmdb_ci_cluster',
            'cmdb_ci_unix_server', 'cmdb_ci_msd'] == [table for table, _ in app['path']['node_records']]
    assert 6 * ['cmdb_rel_ci'] == [table for table, _ in app['path']['link_records']]
    assert all(32 == len(sys_id) for row in result['inform']
               for _, sys_id in row['path']['node_records'] + row['path']['link_records'])


def test_one_cluster_host_degrades_the_cluster_and_puts_bond_trading_at_risk(graph):
    result = impact([find_ci('dbaix900nyc')])
    # only its cluster node goes down with it
    assert 1 == result['beyond_seeds']
    assert [('nyc oracle rac cluster', 1, 3)] == [
        (c['name'], c['hosts_down'], c['hosts_total']) for c in result['degraded_clusters']]
    assert {('business application', 'Bond Trading'): ('at risk', 'IT Securities'),
            ('service', 'Bond Trading'): ('at risk', 'IT Securities'),
            ('service', 'IT Services'): ('at risk', 'UNKNOWN')} == rows(result)


def test_losing_the_dr_copy_puts_bond_trading_at_risk_not_down(graph):
    result = impact([find_ci('lnxldn100')])
    assert {('business application', 'Bond Trading'): ('at risk: DR copy lost', 'IT Securities'),
            ('service', 'Bond Trading - DR'): ('down', 'IT Securities')} == rows(result)


def test_site_outage_starts_at_its_physical_cis_and_lists_what_it_cannot_reach(graph):
    site = run('site', site='450 Lexington Avenue, New York,NY')[0]
    result = impact(site['seeds'])
    assert (21, 35) == (len(site['seeds']), result['beyond_seeds'])
    assert ('down', 'IT Securities') == rows(result)[('business application', 'Bond Trading')]
    assert 7 == len([row for row in result['inform'] if 'service' == row['kind']])
    not_reached = set(site['located']) - set(result['down']) - set(result['at_risk'])
    assert [find_ci('EXCHANGE-NY-02')] == list(not_reached)
