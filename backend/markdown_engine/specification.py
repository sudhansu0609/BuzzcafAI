
from dataclasses import dataclass

@dataclass
class Specification:
    name:str
    kind:str
    metadata:dict
    body:str
