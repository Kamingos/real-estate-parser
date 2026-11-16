"""Интеграционные и регрессионные тесты фабрики, main и старых парсеров."""

import json
from dataclasses import asdict, fields

import pytest
from conftest import OFFER_ID, OFFER_URL, make_config

import main as main_module
from interfaces.parser_interfaces import IParcer
from model.parser_config import ParserConfig
from model.site_parse_data_model import (
    AvitoSiteParseData,
    CianSiteParseData,
    YandexSiteParseData,
)
from realizations.avito_parser import AvitoParser
from realizations.cian_parser import CianParser
from realizations.parser_factory import (
    available_sites,
    create_parser,
    normalize_site_name,
)
from realizations.yandex_parser import YandexParser


class FakeParser(IParcer):
    """Парсер-заглушка для проверки точки запуска."""

    def __init__(self, result):
        self.result = result
        self.configs = []

    def parse(self, parserConfig):
        self.configs.append(parserConfig)
        return self.result


# ------------------------------------------------------------------------------
# Фабрика парсеров
# ------------------------------------------------------------------------------

def test_factory_returns_parsers():
    assert isinstance(create_parser("avito"), AvitoParser)
    assert isinstance(create_parser("cian"), CianParser)
    assert isinstance(create_parser("yandex"), YandexParser)


@pytest.mark.parametrize(
    "alias",
    ["Yandex", "яндекс", "yandex_realty", "realty.yandex.ru", " yandex "],
)
def test_factory_normalizes_aliases(alias):
    assert normalize_site_name(alias) == "yandex"
    assert isinstance(create_parser(alias), YandexParser)


def test_factory_available_sites():
    assert available_sites() == ["avito", "cian", "yandex"]


def test_factory_unknown_site_raises():
    with pytest.raises(ValueError):
        create_parser("unknown")


# ------------------------------------------------------------------------------
# Точка запуска main
# ------------------------------------------------------------------------------

def _yandex_item() -> YandexSiteParseData:
    return YandexSiteParseData(
        site="Yandex",
        url=OFFER_URL,
        external_id=OFFER_ID,
        name="Квартира",
        price=1000,
        parameters={"Ремонт": "евро"},
    )


def test_do_yandex_writes_json(monkeypatch, tmp_path):
    fake_parser = FakeParser((True, [_yandex_item()]))
    monkeypatch.setattr(main_module, "create_parser", lambda _site: fake_parser)

    path = main_module.DoYandex(tmp_path)

    assert path == tmp_path / "yandex_result.json"
    assert path.exists()

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload) == 1
    assert payload[0]["site"] == "Yandex"
    assert payload[0]["external_id"] == OFFER_ID
    assert payload[0]["parameters"] == {"Ремонт": "евро"}
    assert fake_parser.configs == [main_module.yandexConfig]


def test_run_parser_failure_exits(monkeypatch, tmp_path):
    fake_parser = FakeParser((False, None))
    monkeypatch.setattr(main_module, "create_parser", lambda _site: fake_parser)

    with pytest.raises(SystemExit):
        main_module.DoYandex(tmp_path)


def test_main_cli_defaults_to_avito():
    args = main_module._build_parser().parse_args([])

    assert args.site == "avito"
    assert args.pages is None
    assert args.headless is False


def test_main_cli_all_runs_every_parser(monkeypatch, tmp_path):
    created = []

    def fake_create(site):
        created.append(site)
        return FakeParser((True, []))

    monkeypatch.setattr(main_module, "create_parser", fake_create)

    exit_code = main_module.main(
        ["--site", "all", "--pages", "2", "--headless", "--output-dir", str(tmp_path)]
    )

    assert exit_code == 0
    assert created == ["avito", "cian", "yandex"]
    assert (tmp_path / "yandex_result.json").exists()


def test_config_overrides_do_not_mutate_defaults():
    args = main_module._build_parser().parse_args(
        ["--pages", "7", "--min-delay", "1.5", "--max-delay", "2.5", "--headless"]
    )

    config = main_module._config_with_overrides(main_module.yandexConfig, args)

    assert config.max_page_iteration == 7
    assert config.min_iteration_time_span == 1.5
    assert config.max_iteration_time_span == 2.5
    assert config.headless is True
    # Исходная конфигурация не изменилась
    assert main_module.yandexConfig.max_page_iteration == 1
    assert main_module.yandexConfig.headless is False


# ------------------------------------------------------------------------------
# Регрессия: Avito и Cian не сломаны
# ------------------------------------------------------------------------------

def test_parser_config_backward_compatible():
    config = ParserConfig(
        max_page_iteration=1,
        min_iteration_time_span=0,
        max_iteration_time_span=0,
        cities={"vladivostok": 4701},
        min_cost=0,
        max_cost=10_000_000,
        area_min=0,
        area_max=100,
        rooms_count_min=0,
        rooms_count_max=10,
        floor_min=0,
        floor_max=100,
    )

    assert config.max_page_iteration == 1
    # Новые поля доступны со значениями по умолчанию
    assert config.max_retries == 3
    assert config.page_wait_time == 10
    assert config.headless is False


def test_models_keep_fields():
    cian_fields = {item.name for item in fields(CianSiteParseData)}
    avito_fields = {item.name for item in fields(AvitoSiteParseData)}
    yandex_fields = {item.name for item in fields(YandexSiteParseData)}

    assert {"site", "url", "external_id", "price", "geo_label"} <= cian_fields
    assert {"site", "url", "external_id", "price", "geo_label"} <= avito_fields
    assert {"site", "url", "external_id", "price", "geo_label"} <= yandex_fields
    assert "parameters" in yandex_fields

    # asdict работает для всех моделей
    assert asdict(CianSiteParseData())["site"] == ""
    assert asdict(AvitoSiteParseData())["currency"] == "RUB"
    assert asdict(YandexSiteParseData())["parameters"] == {}


def test_avito_and_cian_parsers_are_parsers():
    assert isinstance(AvitoParser(), IParcer)
    assert isinstance(CianParser(), IParcer)
    assert isinstance(YandexParser(), IParcer)


def test_main_configs_exist():
    assert isinstance(main_module.cianConfig, ParserConfig)
    assert isinstance(main_module.avitoCofig, ParserConfig)
    assert isinstance(main_module.yandexConfig, ParserConfig)
    assert main_module.yandexConfig.cities == {"vladivostok": 585430}


def test_yandex_parser_uses_config_delays():
    parser = YandexParser()

    assert parser._resolve_delays(make_config()) == (2.0, 5.0)
    assert parser._resolve_delays(
        make_config(min_iteration_time_span=1.0, max_iteration_time_span=4.0)
    ) == (1.0, 4.0)
    # Перепутанные границы меняются местами
    assert parser._resolve_delays(
        make_config(min_iteration_time_span=5.0, max_iteration_time_span=2.0)
    ) == (2.0, 5.0)
