from dataclasses import dataclass


@dataclass
class TokenEvent:
    tokens_in: int
    tokens_out: int
    cost_usd: float = 0.0
