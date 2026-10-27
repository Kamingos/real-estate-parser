from dataclasses import dataclass, field

from typedict import TypeDict

class geoLabelDict(TypeDict):
    region: str # округ
    city: str # город
    district: str # район
    micro_district: str #микрорайон, если есть
    street: str # улица
    house: str # номер дома

@dataclass
class SiteParseData:
    url: str = field(default_factory=str)
    name: str = field(default_factory=str)
    description: str = field(default_factory=str)
    price: int = field(default_factory=int)
    imgs: list[str] = field(default_factory=list)
    residential_complex: str = field(default_factory=str) # жилой комплекс, если прописан
    geo_label: geoLabelDict = field(default_factory=geoLabelDict)







