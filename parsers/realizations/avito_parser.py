# req
import requests
# seleniub
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
# bs4
from bs4 import BeautifulSoup

# dependency
from interfaces.parser_interfaces import IParcer

from model.parser_config import ParserConfig
from model.site_parse_data_model import SiteParseData

options = Options()
# Отключает флаг enable-automation в настройках браузера
options.add_experimental_option("excludeSwitches", ["enable-automation"])
# Отключает автоматическое расширение Selenium
options.add_experimental_option('useAutomationExtension', False)
# Отключает специальный флаг Blink, помечающий браузер как управляемый
options.add_argument("--disable-blink-features=AutomationControlled")

refs = {
    "flat/studio": "https://www.avito.ru/vladivostok/kvartiry/prodam-ASgBAgICAUSSA8YQ?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6Ik1Hbms0NVdCYU1SeElremciO33Do1akJgAAAA&localPriority=0&p={page}", 
    "room": "https://www.avito.ru/vladivostok/komnaty/prodam-ASgBAgICAUSQA7wQ?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6Ims5ZkhvUUFwTGJicWR1cGEiO33Idg0EJgAAAA&localPriority=0&p={page}", 
    "house": "https://www.avito.ru/vladivostok/doma_dachi_kottedzhi/prodam-ASgBAgICAUSUA9AQ?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6ImdBbjNKTGlKeGxEWDVKbngiO3367d43JgAAAA&localPriority=0&p={page}",
    "land_plot": "https://www.avito.ru/vladivostok/zemelnye_uchastki/prodam-ASgBAgICAUSWA9oQ?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6InNhQTVsSjhmV1pTZEo1aE8iO300GHrYJgAAAA&localPriority=0&p={page}", 
    "garage": "https://www.avito.ru/vladivostok/garazhi_i_mashinomesta/prodam-ASgBAgICAUSYA~QQ?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6ImgyMXNNQ2VWQkxaNlQ0YkciO33mvNP-JgAAAA&localPriority=0&p={page}",
    "other": "https://www.avito.ru/vladivostok/kommercheskaya_nedvizhimost/prodam-ASgBAgICAUSwCNJW?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6Imo2SnJ2d0hOZElKdnNOMlkiO31-kt2FJgAAAA&f=ASgBAgICAkSwCNJW8hKg2gE&localPriority=0&p={page}"
}

class AvitoParser(IParcer):
    def __init__(self) -> None:
        super().__init__()

    def parse(self, parserConfig: ParserConfig) -> tuple[bool, list[SiteParseData] | None]:
        ...

    def _parseFlatPage(self, page: int) -> tuple[bool, list[SiteParseData] | None]:
        ref = refs["flat/studio"]

        # 1. Создаём Service с путём к chromedriver.exe
        service = Service(ref)

        # 2. Создаём WebDriver
        driver = webdriver.Chrome(service=service, options=options)

        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            'source': '''
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
            '''
        })   
        ...

    def _parseRoomPage(self, page: int) -> tuple[bool, list[SiteParseData] | None]:
        ref = refs["room"]

        # 1. Создаём Service с путём к chromedriver.exe
        service = Service(ref)

        # 2. Создаём WebDriver
        driver = webdriver.Chrome(service=service, options=options)

        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            'source': '''
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
            '''
        })   
        ...

    def _parseHousePage(self, page: int) -> tuple[bool, list[SiteParseData] | None]:
        ref = refs["house"]

        # 1. Создаём Service с путём к chromedriver.exe
        service = Service(ref)

        # 2. Создаём WebDriver
        driver = webdriver.Chrome(service=service, options=options)

        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            'source': '''
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
            '''
        })   
        ...

    def _parseLandPage(self, page: int) -> tuple[bool, list[SiteParseData] | None]:
        ref = refs["land_plot"]

        # 1. Создаём Service с путём к chromedriver.exe
        service = Service(ref)

        # 2. Создаём WebDriver
        driver = webdriver.Chrome(service=service, options=options)

        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            'source': '''
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
            '''
        })   
        ...

    def _parseGaragePage(self, page: int) -> tuple[bool, list[SiteParseData] | None]:
        ref = refs["garage"]

        # 1. Создаём Service с путём к chromedriver.exe
        service = Service(ref)

        # 2. Создаём WebDriver
        driver = webdriver.Chrome(service=service, options=options)

        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            'source': '''
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
            '''
        })   
        ...

        
    def _parseOtherPage(self, page: int) -> tuple[bool, list[SiteParseData] | None]:
        ref = refs["other"]

        # 1. Создаём Service с путём к chromedriver.exe
        service = Service(ref)

        # 2. Создаём WebDriver
        driver = webdriver.Chrome(service=service, options=options)

        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            'source': '''
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
            '''
        })   
        ...