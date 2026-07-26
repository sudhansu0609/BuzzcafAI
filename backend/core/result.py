
from dataclasses import dataclass

@dataclass
class Result:
    success: bool
    output: object = None
    message: str = ""
