"""
ticket.py - 경기 선택 및 예매 진입 모듈

NOL(야놀자/인터파크) 스포츠 개편 페이지 및 기존 인터파크 페이지를 모두 지원합니다.
설정 파일 기반으로 경기 URL을 생성하고,
예매 버튼 클릭 → 팝업 창 전환 → 대기열 처리 → 좌석 iframe 진입을 수행합니다.
"""

import time
import re
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logger = logging.getLogger(__name__)

# NOL 인터파크 스포츠 베이스 URL
NOL_SPORTS_BASE = "https://nol.yanolja.com/ticket/genre/sports"
LEGACY_SPORTS_BASE = "https://ticket.interpark.com/Contents/Sports/GoodsInfo"


def build_game_url(settings: dict) -> str:
    """
    설정 기반으로 경기 페이지 URL을 생성합니다.
    NOL의 team slug가 있으면 최신 NOL 주소를 사용합니다.
    """
    team = settings.get("team", {})
    slug = team.get("slug")

    if slug:
        url = f"{NOL_SPORTS_BASE}/{slug}"
        logger.info(f"NOL 경기 URL 생성: {url} (팀: {team.get('name', slug)})")
        return url

    # 구버전 인터파크 URL 폴백
    sports_code = team.get("sports_code", "07001")
    team_code = team.get("team_code", "PB003")
    url = f"{LEGACY_SPORTS_BASE}?SportsCode={sports_code}&TeamCode={team_code}"
    logger.info(f"레거시 경기 URL 생성: {url} (팀: {team.get('name', '알 수 없음')})")
    return url


def navigate_to_game(driver, settings: dict):
    """
    경기 페이지로 이동합니다.
    """
    url = build_game_url(settings)
    wait_time = settings.get("timing", {}).get("page_load_wait", 2)

    logger.info(f"경기 페이지로 이동: {url}")
    driver.get(url)
    time.sleep(wait_time)
    logger.info("경기 페이지 로드 완료")


def get_all_matches(driver):
    """
    현재 페이지의 모든 경기 카드 요소를 가져옵니다.
    """
    # 1. NOL 스포츠 최신 카드 선택자
    cards = driver.find_elements(By.CSS_SELECTOR, "section[id*='GOODS_RESERVATION'] div[class*='grid-tc_']")
    if not cards:
        cards = driver.find_elements(By.CSS_SELECTOR, "div[class*='grid-template-areas']")
    
    # 2. 레거시 인터파크 선택자
    if not cards:
        cards = driver.find_elements(By.CSS_SELECTOR, ".timeScheduleList .timeSchedule")
    if not cards:
        cards = driver.find_elements(By.CSS_SELECTOR, ".scheduleList li, .schedule-item, tr[class*='schedule']")

    return cards


def find_match_element(driver, target_date: str = "", game_index: int = 1):
    """
    지정한 날짜 또는 인덱스에 해당하는 경기 카드 요소를 찾습니다.
    """
    cards = get_all_matches(driver)
    if not cards:
        logger.warning("페이지에서 경기 목록 요소를 찾지 못했습니다.")
        return None, game_index

    logger.info(f"경기 목록 총 {len(cards)}개 발견")

    # 1. 날짜가 지정된 경우
    if target_date:
        numbers = re.findall(r'\d+', target_date)
        if len(numbers) >= 2:
            month = str(int(numbers[-2]))
            day = str(int(numbers[-1]))
            date_patterns = [
                f"{month}월 {day}일", f"{month}월{day}일",
                f"{month.zfill(2)}월 {day.zfill(2)}일", f"{month.zfill(2)}월{day.zfill(2)}일",
                f"{month}.{day}", f"{month.zfill(2)}.{day.zfill(2)}",
                f"{month}/{day}", f"{month.zfill(2)}/{day.zfill(2)}",
            ]
            logger.info(f"목표 날짜 검색: {month}월 {day}일")

            for i, card in enumerate(cards, 1):
                text = card.text
                for pattern in date_patterns:
                    if pattern in text:
                        logger.info(f"✅ 날짜 매칭 성공! 경기 #{i}: {text.splitlines()[0] if text else ''}")
                        return card, i

            logger.warning(f"날짜 '{target_date}'에 매칭되는 경기를 찾지 못했습니다. 기본 index={game_index} 사용")

    # 2. 인덱스 기반 선택
    if 1 <= game_index <= len(cards):
        return cards[game_index - 1], game_index
    elif cards:
        return cards[0], 1

    return None, game_index


def is_booking_button_enabled(button_el) -> bool:
    """
    예매하기 버튼이 활성화되어 있는지(클릭 가능한지) 확인합니다.
    """
    try:
        disabled_attr = button_el.get_attribute("disabled")
        aria_disabled = button_el.get_attribute("aria-disabled")
        classes = button_el.get_attribute("class") or ""
        
        if disabled_attr is not None:
            return False
        if aria_disabled == "true":
            return False
        if "disabled" in classes:
            return False
        return True
    except Exception:
        return False


def click_booking_button(driver, game_index: int = 1, game_date: str = "", require_enabled: bool = False) -> bool:
    """
    예매하기 버튼을 찾아 클릭합니다.

    Args:
        driver: WebDriver 인스턴스
        game_index: 경기 인덱스 (1-based)
        game_date: 경기 날짜 (예: "10.07", "10월 7일")
        require_enabled: True이면 버튼이 활성화(클릭 가능) 상태여야만 클릭

    Returns:
        성공 여부
    """
    card, matched_index = find_match_element(driver, target_date=game_date, game_index=game_index)
    if not card:
        logger.error("경기 카드 요소를 찾지 못했습니다.")
        return False

    btn_selectors = [
        ".//button[contains(@class, 'grid-area_cta')]",
        ".//button[contains(text(), '예매')]",
        ".//a[contains(text(), '예매')]",
        ".//button",
        ".BtnColor_Y.btn1",
        ".btn_book",
    ]

    booking_btn = None
    for sel in btn_selectors:
        try:
            found = card.find_elements(By.XPATH if sel.startswith(".") else By.CSS_SELECTOR, sel)
            for b in found:
                text = b.text.strip()
                if "예매" in text or "예매하기" in text or "구매" in text:
                    booking_btn = b
                    break
            if booking_btn:
                break
        except Exception:
            continue

    if not booking_btn:
        logger.error(f"경기 #{matched_index}에서 예매 버튼을 찾지 못했습니다.")
        return False

    enabled = is_booking_button_enabled(booking_btn)
    if not enabled:
        if require_enabled:
            logger.info(f"⏳ 경기 #{matched_index} 예매 버튼이 아직 비활성화 상태입니다 (오픈 대기 필요)")
            return False
        else:
            logger.warning(f"⚠️ 경기 #{matched_index} 예매 버튼이 비활성화 상태이지만 클릭을 시도합니다.")

    try:
        # 화면에 보이도록 스크롤
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", booking_btn)
        time.sleep(0.1)

        # 클릭 시도 (Selenium 일반 클릭 -> JS 클릭 순)
        try:
            booking_btn.click()
        except Exception:
            driver.execute_script("arguments[0].click();", booking_btn)

        logger.info(f"✅ 경기 #{matched_index} 예매하기 버튼 클릭 완료")
        return True

    except Exception as e:
        logger.error(f"예매 버튼 클릭 실패: {e}")
        return False


def switch_to_booking_popup(driver, original_window_count: int = 1, timeout: int = 15) -> bool:
    """
    예매 화면(새 창/새 탭 또는 https://tickets.interpark.com/onestop/seat)으로 전환합니다.
    새 탭으로 열리든, 현재 창에서 이동하든 모두 감지합니다.
    """
    try:
        logger.info("예매 화면(onestop/seat) 진입 대기 중...")
        start_t = time.time()
        while time.time() - start_t < timeout:
            # 1. 새 창 또는 새 탭이 열린 경우 -> 최신 창으로 전환
            if len(driver.window_handles) > original_window_count:
                driver.switch_to.window(driver.window_handles[-1])
                logger.info(f"✅ 새 탭/창 전환 완료 (총 {len(driver.window_handles)}개 창) -> {driver.current_url}")
                time.sleep(0.5)
                return True

            # 2. 현재 창 자체가 onestop/seat 또는 tickets.interpark.com으로 이동한 경우
            current_url = driver.current_url.lower()
            if "onestop" in current_url or "seat" in current_url or "tickets.interpark.com" in current_url:
                logger.info(f"✅ 원스톱 좌석 페이지 이동 감지: {driver.current_url}")
                time.sleep(0.5)
                return True

            time.sleep(0.3)

        logger.warning(f"창 전환/이동 대기 타임아웃 ({timeout}초). 현재 페이지에서 계속 진행합니다: {driver.current_url}")
        return True

    except Exception as e:
        logger.error(f"예매 화면 전환 중 오류: {e}")
        return True


def wait_for_queue(driver, timeout: int = 300) -> bool:
    """
    대기열(순번)을 통과하여 좌석 화면이 나타날 때까지 기다립니다.
    """
    logger.info("대기열 및 좌석 화면(onestop/seat) 로드 확인 중...")
    try:
        wait = WebDriverWait(driver, timeout)
        wait.until(
            lambda d: "onestop" in d.current_url.lower() or
                      "seat" in d.current_url.lower() or
                      len(d.find_elements(By.ID, "ifrmSeat")) > 0 or
                      len(d.find_elements(By.CSS_SELECTOR, "iframe#ifrmSeat")) > 0 or
                      len(d.find_elements(By.CSS_SELECTOR, ".gradeList, .blockList, #divSeat, [class*='seat']")) > 0
        )
        logger.info("✅ 대기열 통과 및 좌석 화면 로드 확인 완료")
        return True

    except Exception as e:
        logger.error(f"대기열 대기 실패 ({timeout}초): {e}")
        return False


def switch_to_seat_iframe(driver) -> bool:
    """
    좌석 선택 iframe(ifrmSeat)으로 전환합니다.
    iframe이 없는 단일 페이지 구조인 경우 바로 성공으로 처리합니다.
    """
    try:
        iframes = driver.find_elements(By.ID, "ifrmSeat")
        if iframes:
            driver.switch_to.frame(iframes[0])
            time.sleep(0.3)
            logger.info("✅ 좌석 선택 iframe(ifrmSeat) 진입 완료")
            return True

        # iframe이 없는 신규 뷰 구조 확인
        time.sleep(0.3)
        return True

    except Exception as e:
        logger.error(f"좌석 iframe 전환 중 오류: {e}")
        return False


def enter_booking(driver, settings: dict) -> bool:
    """
    경기 진입부터 좌석 선택 iframe 진입까지 전체 과정을 수행합니다.
    """
    game_index = settings.get("game_index", 1)
    game_date = settings.get("game_date", "")

    # 1. 경기 페이지 이동
    navigate_to_game(driver, settings)

    original_count = len(driver.window_handles)

    # 2. 예매 버튼 클릭
    if not click_booking_button(driver, game_index=game_index, game_date=game_date):
        return False

    # 3. 팝업 전환
    if not switch_to_booking_popup(driver, original_window_count=original_count):
        return False

    # 4. 대기열 통과 대기
    if not wait_for_queue(driver):
        return False

    # 5. 좌석 iframe 전환
    if not switch_to_seat_iframe(driver):
        return False

    return True
