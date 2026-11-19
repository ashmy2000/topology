        // Neo4j Browser demo: one straight line, bottom-up, from the storage array to the business application.
        // One line per level. Each arrow points from the item that needs something to the item it needs, as ServiceNow
        // records it, so a failure travels against the arrows. Click a node or link to see its properties.
        // It is the "via" path kg/outage.py prints when this storage array fails.
        MATCH line = (storage:MassStorageDevice {name: 'nyc rac nas200'})
          <-[:DEPENDS_ON]-(:Server {name: 'dbaix902nyc'})
          <-[:MEMBERS]-(:Cluster {name: 'nyc oracle rac cluster'})
          <-[:DEPENDS_ON]-(:Database {name: 'NY RAC'})
          <-[:HOSTED_ON]-(:Database {name: 'bond_trade_uk'})
          <-[:DEPENDS_ON]-(:Service {name: 'Bond Trading'})
          <-[:CONSUMES]-(:BusinessApplication {name: 'Bond Trading'})
        RETURN line;
