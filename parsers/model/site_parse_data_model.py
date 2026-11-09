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


from dataclasses import dataclass, field
from typing import Literal


@dataclass
class CianSiteParseData:
    # Основная информация об объявлении
    site: str = field(default_factory=str)
    url: str = field(default_factory=str)
    external_id: str = field(default_factory=str)
    name: str = field(default_factory=str)
    subtitles: str = field(default_factory=str)
    description: str = field(default_factory=str)
    object_type: Literal["flat", "room", "studio", "house", "land_plot", "garage", "other"] = "other"
    housing_type: str = field(default_factory=str)

    # Цена и условия сделки
    price: int = 0
    price_per_meter: int = 0
    currency: str = "RUB"
    deal_type: str = "sale"
    deal_conditions: str = field(default_factory=str)
    mortgage_possible: bool | None = None

    # Основные характеристики квартиры
    area: float = 0.0
    living_area: float = 0.0
    kitchen_area: float = 0.0
    rooms_count: int | None = None
    floor: int = 0
    floors_count: int = 0
    ceiling_height: float = 0.0
    bathroom: str = field(default_factory=str)
    balcony: str = field(default_factory=str)
    window_view: str = field(default_factory=str)

    # Состояние и отделка квартиры
    repairs: str = field(default_factory=str)
    finishing: str = field(default_factory=str)
    sell_with_furniture: bool | None = None
    furniture: str = field(default_factory=str)

    # Информация о доме
    year_building: int = 0
    building_status: str = field(default_factory=str)
    building_material: str = field(default_factory=str)
    floors_material: str = field(default_factory=str)
    entrances_count: int = 0
    elevators: list[str] = field(default_factory=list)
    parking: str = field(default_factory=str)
    heating: str = field(default_factory=str)
    concierge: bool | None = None
    barrier: bool | None = None
    emergency: bool | None = None

    # Доступная среда
    ramp: bool | None = None
    entrance_door_width: str = field(default_factory=str)
    interior_doors_width: str = field(default_factory=str)

    # Информация о жилом комплексе
    residential_complex: str = field(default_factory=str)
    developer: str = field(default_factory=str)
    residential_complex_class: str = field(default_factory=str)
    residential_complex_type: str = field(default_factory=str)
    residential_complex_buildings_count: int = 0
    residential_complex_building_types: list[str] = field(default_factory=list)
    residential_complex_parking: list[str] = field(default_factory=list)
    residential_complex_finishing: list[str] = field(default_factory=list)
    residential_complex_completion: str = field(default_factory=str)
    residential_complex_promotions: list[str] = field(default_factory=list)

    # Информация о застройщике
    developer_foundation_year: int = 0
    developer_rating: float = 0.0
    developer_reviews_count: int = 0
    developer_completed_buildings: int = 0
    developer_buildings_under_construction: int = 0
    developer_residential_complexes: int = 0
    developer_description: str = field(default_factory=str)

    # Географическое расположение
    geo_label: dict = field(default_factory=lambda: {
        "region": "",
        "city": "",
        "district": "",
        "micro_district": "",
        "street": "",
        "house": ""
    })
    address: str = field(default_factory=str)

    # Инфраструктура
    nearby_infrastructure: list[str] = field(default_factory=list)

    # Юридическая информация
    rosreestr_verified: bool | None = None
    ownership_type: str = field(default_factory=str)
    owners_count: int | None = None
    cadastral_number: str = field(default_factory=str)
    encumbrances: str = field(default_factory=str)
    minors_owners: bool | None = None
    maternity_capital_used: bool | None = None

    # Информация о риелторе и продавце
    rieltor: str = field(default_factory=str)
    seller_type: str = field(default_factory=str)
    seller_documents_verified: bool | None = None
    seller_experience: str = field(default_factory=str)
    seller_ads_count: int = 0

    # Фотографии
    imgs: list[str] = field(default_factory=list)

    # Статистика и информация об объявлении
    update_date: str = field(default_factory=str)
    views_count: int = 0
    views_today: int = 0
    photos_count: int = 0
    is_verified: bool | None = None
    
@dataclass
class AvitoSiteParseData:
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
    rooms_count: str = field(default_factory=str)
    geo_label: geoLabelDict = field(default_factory=lambda: {
        "region": "",
        "city": "",
        "district": "",
        "micro_district": "",
        "street": "",
        "house": ""
    })