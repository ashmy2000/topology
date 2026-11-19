from kg.db import DB, driver


def test_neo4j_is_2026_10_community():
    records = driver.execute_query(
        "CALL dbms.components() YIELD name, versions, edition RETURN versions, edition", database_=DB).records
    assert records[0]["versions"][0].startswith("2026.10")
    assert records[0]["edition"] == "community"
