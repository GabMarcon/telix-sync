from pydantic import BaseModel, Field
from typing import Dict, Any

class TelemetryPayload(BaseModel):
    ts: int = Field(..., description="Timestamp em milissegundos")
    values: Dict[str, Any] = Field(..., description="Chaves e valores de telemetria")