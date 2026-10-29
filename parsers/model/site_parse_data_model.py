from dataclasses import dataclass, field
from typing import TypedDict
from typing import Literal


class geoLabelDict(TypedDict):
    region: str
    city: str
    district: str
    micro_district: str
    street: str
    house: str


@dataclass
class SiteParseData:
    site: str = field(default_factory=str)
    url: str = field(default_factory=str)
    name: str = field(default_factory=str)
    subtitles: str = field(default_factory=str)
    description: str = field(default_factory=str)
    price: int = field(default_factory=int)
    object_type: Literal["flat", "room", "studio", "house", "land_plot", "garage", "other"] = field(default="other")
    imgs: list[str] = field(default_factory=list)
    residential_complex: str = field(default_factory=str)
    floor: int = field(default_factory=int)
    area: float = field(default_factory=float)
    rooms_count: int = field(default_factory=int)
    geo_label: geoLabelDict = field(default_factory=lambda: {
        "region": "",
        "city": "",
        "district": "",
        "micro_district": "",
        "street": "",
        "house": ""
    })