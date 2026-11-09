from dataclasses import dataclass, field
from typing import Literal, TypedDict


class geoLabelDict(TypedDict):
    region: str
    city: str
    district: str
    micro_district: str
    street: str
    house: str


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
    # Основная информация об объявлении
    # (порядок первых полей сохранён для обратной совместимости
    # с ранее сохранёнными данными avito_result.json)
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

    # Идентификатор объявления на сайте
    external_id: str = field(default_factory=str)

    # Цена и условия сделки
    price_per_meter: int = 0
    currency: str = "RUB"
    deal_type: str = "sale"
    deal_conditions: str = field(default_factory=str)
    mortgage_possible: bool | None = None
    sale_method: str = field(default_factory=str)          # «Способ продажи»
    participation_type: str = field(default_factory=str)   # «Тип участия»

    # Характеристики объекта
    living_area: float = 0.0
    kitchen_area: float = 0.0
    floors_count: int = 0
    ceiling_height: float = 0.0
    bathroom: str = field(default_factory=str)
    balcony: str = field(default_factory=str)
    window_view: str = field(default_factory=str)
    repairs: str = field(default_factory=str)
    finishing: str = field(default_factory=str)

    # Информация о доме
    housing_type: str = field(default_factory=str)         # новостройка / вторичка
    building_status: str = field(default_factory=str)
    year_building: int = 0
    building_material: str = field(default_factory=str)    # «Материал стен» / «Тип дома»
    building_section: str = field(default_factory=str)     # «Корпус, строение»
    completion_date: str = field(default_factory=str)      # «Срок сдачи»
    elevators: list[str] = field(default_factory=list)
    parking: str = field(default_factory=str)
    courtyard: list[str] = field(default_factory=list)     # «Двор»

    # Инженерия и участок (дома, участки, гаражи)
    heating: str = field(default_factory=str)
    water_supply: str = field(default_factory=str)
    sewerage: str = field(default_factory=str)
    gas: str = field(default_factory=str)
    electricity: str = field(default_factory=str)
    internet_tv: str = field(default_factory=str)
    land_category: str = field(default_factory=str)        # «Категория земель»
    land_area: float = 0.0                                 # «Площадь участка»
    land_area_unit: str = field(default_factory=str)       # сот. / га
    garage_type: str = field(default_factory=str)          # «Тип гаража»
    security: str = field(default_factory=str)             # «Охрана»
    recreation: str = field(default_factory=str)           # «Для отдыха»
    terrace: str = field(default_factory=str)              # «Терраса или веранда»

    # Информация о застройщике (блок «О застройщике»)
    developer: str = field(default_factory=str)
    developer_foundation_year: int = 0
    developer_completed_buildings: int = 0
    developer_buildings_under_construction: int = 0

    # Информация о продавце
    seller_name: str = field(default_factory=str)
    seller_type: str = field(default_factory=str)          # Частное лицо / Застройщик / Агентство
    seller_rating: float = 0.0
    seller_reviews_count: int = 0
    seller_registered_year: int = 0                        # «На Авито c 2022 года»
    seller_ads_count: int = 0                              # «N объявлений пользователя»
    contact_person: str = field(default_factory=str)
    seller_documents_verified: bool | None = None

    # Геолокация (координаты карты объявления)
    latitude: float = 0.0
    longitude: float = 0.0

    # Навигация и маркетинговые блоки
    breadcrumbs: list[str] = field(default_factory=list)
    badges: list[str] = field(default_factory=list)
    feature_chips: list[str] = field(default_factory=list)

    # Статистика и информация об объявлении
    publish_date: str = field(default_factory=str)         # «22 октября в 09:48»
    update_date: str = field(default_factory=str)          # дата последнего обновления
    views_count: int = 0
    views_today: int = 0
    photos_count: int = 0
    is_verified: bool | None = None

    # Полный словарь параметров объявления (сырые данные)
    parameters: dict[str, str] = field(default_factory=dict)