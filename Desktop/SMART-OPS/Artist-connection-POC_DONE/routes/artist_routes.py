"""
routes/artist_routes.py

Thin entry point used by app.py (and tests). All real orchestration
logic lives in agents/supervisor_agent.py 
"""
from agents.supervisor_agent import SupervisorAgent
from utils.logger import logger


class ArtistRouter:

    def __init__(self):
        self.supervisor = SupervisorAgent()

    def process_query(self, query: str) -> dict:
        logger.info(f"Received query: {query}")
        result = self.supervisor.handle_query(query)
        logger.info(f"Response status: {result['status']}")
        return result
