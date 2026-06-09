"""
browser.py - 브라우저 초기화 및 관리 모듈

undetected-chromedriver를 사용하여 봇 탐지를 최소화하고,
설정 파일 기반으로 브라우저를 구성합니다.
"""

import logging

logger = logging.getLogger(__name__)


def create_driver(settings: dict):
    """
    설정 기반으로 Chrome 드라이버를 생성합니다.

    undetected-chromedriver가 설치되어 있으면 우선 사용하고,
    없거나 실패하면 일반 Selenium으로 폴백합니다.

    Args:
        settings: config/settings.json에서 로드한 설정 딕셔너리

    Returns:
        Chrome WebDriver 인스턴스
    """
    browser_config = settings.get("browser", {})

    # undetected-chromedriver 시도
    try:
        import undetected_chromedriver as uc

        options = uc.ChromeOptions()
        options.add_experimental_option("detach", True)

        if browser_config.get("headless", False):
            options.add_argument("--headless=new")

        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-first-run")
        options.add_argument("--no-service-autorun")
        options.add_argument("--password-store=basic")

        logger.info("undetected-chromedriver로 Chrome 생성 중...")
        driver = uc.Chrome(options=options)

    except Exception as e:
        logger.warning(f"undetected-chromedriver 사용 불가: {e}")
        logger.info("일반 Selenium Chrome 드라이버로 폴백합니다.")

        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        chrome_options = Options()
        chrome_options.add_experimental_option("detach", True)

        if browser_config.get("headless", False):
            chrome_options.add_argument("--headless=new")

        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        driver = webdriver.Chrome(options=chrome_options)

    # 창 크기 설정
    width = browser_config.get("window_width", 1900)
    height = browser_config.get("window_height", 1000)
    driver.set_window_size(width, height)

    # 암묵적 대기 설정
    implicit_wait = browser_config.get("implicit_wait", 2)
    driver.implicitly_wait(implicit_wait)

    logger.info(f"브라우저 준비 완료 (창 크기: {width}x{height})")
    return driver


def navigate_to(driver, url: str, wait_time: float = 2):
    """
    지정한 URL로 이동합니다.

    Args:
        driver: WebDriver 인스턴스
        url: 이동할 URL
        wait_time: 페이지 로드 후 대기 시간 (초)
    """
    import time
    logger.info(f"페이지 이동: {url}")
    driver.get(url)
    time.sleep(wait_time)


def close_driver(driver):
    """드라이버를 안전하게 종료합니다."""
    try:
        if driver:
            driver.quit()
            logger.info("브라우저가 종료되었습니다.")
    except Exception as e:
        logger.warning(f"브라우저 종료 중 오류: {e}")
