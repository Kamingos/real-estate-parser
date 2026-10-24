from abc import ABC, abstractmethod

class IParcer(ABC):
    @abstractmethod
    def parse(self) -> str:
        pass