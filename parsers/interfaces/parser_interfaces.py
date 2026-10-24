from abc import ABC, abstractmethod

class IParcer(ABC):
    # return json|null with elements all pages
    @abstractmethod
    def parse(self, city_id: int) -> bool|str:
        pass

    # return json|null with elements one page
    @abstractmethod
    def _parsePage(self, city_id: int, page: int) -> bool|str:
        pass


    