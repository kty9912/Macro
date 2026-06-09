"""
auth.py - 로그인 대기 모듈

NOL 인터파크는 네이버/카카오/구글 등 소셜 로그인으로 변경되어
자동 로그인이 어렵습니다. 사용자가 직접 로그인을 완료할 때까지
대기하는 방식으로 동작합니다.
"""

import time
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logger = logging.getLogger(__name__)


def wait_for_manual_login(driver, timeout: int = 300) -> bool:
    """
    사용자가 브라우저에서 직접 로그인을 완료할 때까지 대기합니다.

    NOL 인터파크는 네이버/카카오 등 소셜 로그인을 사용하므로,
    CAPTCHA, 2FA 등의 이유로 자동화가 매우 어렵습니다.
    따라서 로그인은 사용자에게 위임합니다.

    Args:
        driver: WebDriver 인스턴스
        timeout: 최대 대기 시간 (초, 기본 5분)

    Returns:
        로그인 성공 여부
    """
    print()
    print("=" * 60)
    print("  🔐 로그인이 필요합니다!")
    print()
    print("  브라우저에서 직접 로그인을 해주세요.")
    print("  (네이버/카카오/구글 등 소셜 로그인)")
    print()
    print(f"  최대 {timeout // 60}분 동안 대기합니다.")
    print("=" * 60)
    print()

    logger.info(f"사용자 로그인 대기 중... (최대 {timeout}초)")

    # 로그인 상태를 주기적으로 확인
    start_time = time.time()
    check_interval = 2  # 2초마다 확인

    while time.time() - start_time < timeout:
        if _is_logged_in(driver):
            elapsed = int(time.time() - start_time)
            logger.info(f"✅ 로그인 감지! ({elapsed}초 경과)")
            print("✅ 로그인이 감지되었습니다! 진행합니다...")
            return True
        time.sleep(check_interval)

    logger.error(f"로그인 대기 시간 초과 ({timeout}초)")
    print("❌ 로그인 대기 시간이 초과되었습니다.")
    return False


def _is_logged_in(driver) -> bool:
    """
    현재 페이지에서 로그인 여부를 확인합니다.

    다양한 방법으로 로그인 상태를 감지합니다:
    1. '로그아웃' 텍스트 존재 여부
    2. '마이페이지' 텍스트 존재 여부
    3. 사용자 이름('님') 표시 여부
    4. 로그인 버튼의 부재

    Returns:
        로그인 상태이면 True
    """
    try:
        # 방법 1: 로그아웃/마이페이지/님 텍스트 확인
        login_indicators = [
            "//*[contains(text(), '로그아웃')]",
            "//*[contains(text(), '마이페이지')]",
            "//*[contains(text(), '마이티켓')]",
            "//*[contains(@class, 'mypage')]",
            "//*[contains(@class, 'logout')]",
            "//*[contains(@class, 'user-name')]",
            "//*[contains(@class, 'my-menu')]",
        ]

        for xpath in login_indicators:
            elements = driver.find_elements(By.XPATH, xpath)
            for elem in elements:
                if elem.is_displayed():
                    return True

        # 방법 2: 쿠키 기반 확인 (로그인 시 특정 쿠키가 설정됨)
        cookies = driver.get_cookies()
        login_cookie_names = ["SSOTOKEN", "SSOLOGIN", "NID_SES", "NID_AUT"]
        for cookie in cookies:
            if cookie.get("name") in login_cookie_names:
                return True

        return False

    except Exception:
        return False


def navigate_to_login(driver):
    """
    로그인 페이지로 이동합니다.

    Args:
        driver: WebDriver 인스턴스
    """
    try:
        # 로그인 버튼/링크 클릭 시도
        login_selectors = [
            (By.LINK_TEXT, "로그인"),
            (By.CSS_SELECTOR, "a[href*='login']"),
            (By.CSS_SELECTOR, ".login-btn"),
            (By.CSS_SELECTOR, "#loginBtn"),
            (By.XPATH, "//*[contains(text(), '로그인') and (self::a or self::button)]"),
        ]

        for by, selector in login_selectors:
            try:
                elem = driver.find_element(by, selector)
                if elem.is_displayed():
                    elem.click()
                    logger.info(f"로그인 페이지로 이동 (선택자: {selector})")
                    time.sleep(1)
                    return
            except Exception:
                continue

        logger.warning("로그인 버튼을 찾을 수 없습니다. 메인 페이지에서 직접 로그인해주세요.")

    except Exception as e:
        logger.error(f"로그인 페이지 이동 실패: {e}")
