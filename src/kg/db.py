import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase, NotificationDisabledClassification

load_dotenv(Path(__file__).resolve().parents[2] / '.env')
URI = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
AUTH = (os.getenv('NEO4J_USER', 'neo4j'), os.getenv('NEO4J_PASSWORD', 'password'))
DB = os.getenv('NEO4J_DATABASE', 'neo4j')
# queries name relationship types an extract may lack (no PDI CI fills managed_by_group); don't warn about them
driver = GraphDatabase.driver(URI, auth=AUTH, connection_timeout=5,
                              connection_acquisition_timeout=10, max_transaction_retry_time=3,
                              notifications_disabled_classifications=[NotificationDisabledClassification.UNRECOGNIZED])

if __name__ == "__main__":
    driver.verify_connectivity()
    recs = driver.execute_query(
        "CALL dbms.components() YIELD name, versions, edition RETURN *", database_=DB).records
    print(recs)
    driver.close()
