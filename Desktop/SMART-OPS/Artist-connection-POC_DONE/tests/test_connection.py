# test_connection.py

from neo4j import GraphDatabase
from dotenv import load_dotenv
import os

load_dotenv()

uri = os.getenv("NEO4J_URI")
user = os.getenv("NEO4J_USER")
password = os.getenv("NEO4J_PASSWORD")

driver = GraphDatabase.driver(
    uri,
    auth=(user, password)
)

try:
    with driver.session() as session:
        result = session.run("""
MATCH (a:Artist)
RETURN count(a) as total
""")

        print(result.single()["total"])

except Exception as e:
    print("Connection Error:", e)

finally:
    driver.close()
