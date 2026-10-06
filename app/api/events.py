from dataclasses import dataclass
import json


@dataclass
class SSEEvent:
    event: str
    data: dict
    event_id: int | None = None

    def to_sse(self) -> str:
        lines = []

        if self.event_id is not None:
            lines.append(f"id: {self.event_id}")

        lines.append(f"event: {self.event}")
        lines.append(f"data: {json.dumps(self.data)}")

        return "\n".join(lines) + "\n\n"