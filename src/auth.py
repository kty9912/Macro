"""
auth.py - 로그인 대기 모듈

NOL(야놀자/인터파크)은 소셜 로그인(네이버/카카오/애플 등)을 주로 사용하므로,
사용자가 직접 브라우저에서 로그인을 완료할 때까지 대기합니다.
자동 감지(DOM/쿠키/URL)와 함께, 사용자가 콘솔에서 [Enter]를 누르면
즉시 진행할 수 있는 수동 확인(Fallback)을 함께 제공합니다.
"""

import time
import logging
import threading
from selenium.webdriver.common.by import By

logger = logging.getLogger(__name__)


def wait_for_manual_login(driver, timeout: int = 300) -> bool:
    """
    사용자가 브라우저에서 로그인을 완료할 때까지 대기합니다.
    자동 감지와 터미널 Enter 입력을 동시에 대기합니다.

    Args:
        driver: WebDriver 인스턴스
        timeout: 최대 대기 시간 (초, 기본 5분)

    Returns:
        로그인 확인 여부 (True: 완료, False: 시간초과)
    """
    print()
    print("=" * 65)
    print("  🔐 [로그인 안내] 브라우저에서 로그인을 완료해주세요.")
    print("  - 네이버 / 카카오 / 구글 / 이메일 등 편하신 방식으로 로그인하세요.")
    print("  - 로그인이 완료되면 자동으로 감지하여 다음 단계로 넘어갑니다.")
    print("  - 만약 자동 감지가 안 되면 터미널에서 [Enter]를 누르시면 즉시 진행됩니다!")
    print(f"  - 최대 대기 시간: {timeout}초")
    print("=" * 65)
    print()

    login_done_event = threading.Event()

    def listen_for_enter():
        try:
            input("\n👉 로그인을 완료하셨다면 [Enter] 키를 누르세요...\n")
            login_done_event.set()
        except Exception:
            pass

    # Enter 입력 감지 백그라운드 스레드 시작
    enter_thread = threading.Thread(target=listen_for_enter, daemon=True)
    enter_thread.start()

    logger.info(f"사용자 로그인 대기 중... (최대 {timeout}초, 자동 감지 및 Enter 입력 대기)")

    start_time = time.time()
    check_interval = 1.0

    while time.time() - start_time < timeout:
        # 사용자가 엔터를 눌렀는지 확인
        if login_done_event.is_set():
            logger.info("✅ 사용자 엔터 입력으로 로그인 완료 확인")
            print("✅ 사용자 확인 완료! 다음 단계로 즉시 진행합니다...\n")
            return True

        # 자동 감지 확인
        if _is_logged_in(driver):
            elapsed = int(time.time() - start_time)
            logger.info(f"✅ 로그인 자동 감지 성공! ({elapsed}초 소요)")
            print("\n✅ 로그인이 자동으로 감지되었습니다! 진행합니다...\n")
            login_done_event.set()
            return True

        time.sleep(check_interval)

    logger.error(f"❌ 로그인 대기 시간 초과 ({timeout}초)")
    print("❌ 로그인 대기 시간이 초과되었습니다.")
    return False


def _is_logged_in(driver) -> bool:
    """
    현재 페이지 및 쿠키에서 로그인 여부를 확인합니다.
    """
    try:
        current_url = driver.current_url.lower()

        # 로그인 진행 중인 URL(로그인 페이지)이면 아직 미완료
        if "member/login" in current_url or "accounts." in current_url or "nid.naver.com" in current_url or "kauth.kakao.com" in current_url:
            return False

        # 1. 쿠키 기반 확인 (NOL/야놀자/인터파크 인증 쿠키)
        cookies = driver.get_cookies()
        auth_cookie_prefixes = [
            "accesstoken", "refreshtoken", "_y_at", "_y_rt",
            "nol_sso", "ssotoken", "ssologin", "islogin", "c_user"
        ]
        for cookie in cookies:
            name = cookie.get("name", "").lower()
            val = cookie.get("value", "")
            for prefix in auth_cookie_prefixes:
                if prefix in name and len(val) > 5:
                    return True

        # 2. DOM 요소 확인 (로그아웃 버튼, 사용자 정보, 마이페이지)
        login_indicators = [
            "//a[contains(@href, 'logout')]",
            "//button[contains(text(), '로그아웃')]",
            "//*[contains(text(), '로그아웃')]",
            "//*[contains(@class, 'logout')]",
            "//*[contains(@class, 'user-name')]",
            "//*[contains(@class, 'userName')]",
            "//a[contains(@href, '/mypage') and not(contains(@href, 'login'))]",
            "//span[contains(text(), '님')]",
        ]

        for xpath in login_indicators:
            elements = driver.find_elements(By.XPATH, xpath)
            for elem in elements:
                try:
                    if elem.is_displayed():
                        return True
                except Exception:
                    continue

        return False

    except Exception as e:
        logger.debug(f"로그인 감지 체크 중 예외: {e}")
        return False


def navigate_to_login(driver, base_url: str = "https://nol.yanolja.com"):
    """
    로그인 페이지로 이동합니다.
    """
    login_url = f"{base_url.rstrip('/')}/member/login"
    try:
        logger.info(f"로그인 페이지로 이동: {login_url}")
        driver.get(login_url)
    except Exception as e:
        logger.error(f"로그인 페이지 이동 실패: {e}")
