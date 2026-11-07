from abc import ABC, abstractmethod
from typing import Any, Dict
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

class BaseAgent(ABC):
    """Clase base abstracta para todos los agentes del SAT-FUMC."""
    
    def __init__(self, name: str, role: str):
        self.name = name
        self.role = role
        self.logger = logging.getLogger(self.name)
        self.metrics: Dict[str, Any] = {}

    @abstractmethod
    def run(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Ejecuta la responsabilidad principal del agente."""
        pass

    def get_status(self) -> Dict[str, Any]:
        return {
            "agent_name": self.name,
            "role": self.role,
            "metrics": self.metrics
        }
