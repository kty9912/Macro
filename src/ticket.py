"""
ticket.py - 경기 선택 및 예매 진입 모듈

설정 파일 기반으로 경기 URL을 생성하고,
예매 버튼 클릭 → 팝업 창 전환 → 대기열 처리를 수행합니다.
"""

import time
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logger = logging.getLogger(__name__)

# 인터파크 스포츠 티켓 베이스 URL
SPORTS_BASE_URL = "https://ticket.interpark.com/Contents/Sports/GoodsInfo"


def build_game_url(settings: dict) -> str:
    """
    설정 기반으로 경기 페이지 URL을 생성합니다.

    Args:
        settings: 설정 딕셔너리

    Returns:
        경기 페이지 URL
    """
    team = settings.get("team", {})
    sports_code = team.get("sports_code", "07001")
    team_code = team.get("team_code", "PB003")

    url = f"{SPORTS_BASE_URL}?SportsCode={sports_code}&TeamCode={team_code}"
    logger.info(f"경기 URL 생성: {url} (팀: {team.get('name', '알 수 없음')})")
    return url


def navigate_to_game(driver, settings: dict):
    """
    경기 페이지로 이동합니다.

    Args:
        driver: WebDriver 인스턴스
        settings: 설정 딕셔너리
    """
    url = build_game_url(settings)
    wait_time = settings.get("timing", {}).get("page_load_wait", 2)

    driver.get(url)
    time.sleep(wait_time)
    logger.info("경기 페이지 로드 완료")


def find_game_by_date(driver, target_date: str) -> int | None:
    """
    경기 목록에서 특정 날짜의 경기를 찾아 인덱스를 반환합니다.

    Args:
        driver: WebDriver 인스턴스
        target_date: 찾을 날짜 문자열 (예: "06.15", "6/15", "06월 15일", "2026.06.15")

    Returns:
        경기 인덱스 (1-based) 또는 None
    """
    try:
        # 날짜에서 월/일 숫자만 추출
        import re
        date_numbers = re.findall(r'\d+', target_date)
        if len(date_numbers) >= 2:
            # 마지막 2개를 월/일로 사용 (2026.06.15 → [2026, 06, 15] → month=06, day=15)
            month = date_numbers[-2].lstrip('0') or '0'
            day = date_numbers[-1].lstrip('0') or '0'
        else:
            logger.error(f"날짜 형식을 인식할 수 없습니다: {target_date}")
            return None

        logger.info(f"날짜 검색: {month}월 {day}일")

        # 경기 목록의 모든 항목 가져오기
        schedules = driver.find_elements(By.CSS_SELECTOR, ".timeScheduleList .timeSchedule")
        if not schedules:
            # 대체 선택자
            schedules = driver.find_elements(By.CSS_SELECTOR, ".scheduleList li, .schedule-item, tr[class*='schedule']")

        logger.info(f"경기 목록 {len(schedules)}개 발견")

        for i, schedule in enumerate(schedules, 1):
            text = schedule.text
            # 다양한 날짜 형식 매칭
            # "06.15", "6.15", "06/15", "6월 15일", "06월15일" 등
            date_patterns = [
                f"{month}.{day}",
                f"{month.zfill(2)}.{day.zfill(2)}",
                f"{month}/{day}",
                f"{month.zfill(2)}/{day.zfill(2)}",
                f"{month}월 {day}일",
                f"{month}월{day}일",
                f"{month.zfill(2)}월 {day.zfill(2)}일",
                f"{month.zfill(2)}월{day.zfill(2)}일",
            ]

            for pattern in date_patterns:
                if pattern in text:
                    logger.info(f"[OK] 날짜 매칭: '{pattern}' (경기 #{i})")
                    logger.info(f"  경기 정보: {text[:100]}...")
                    return i

        logger.warning(f"날짜 '{target_date}'에 해당하는 경기를 찾지 못했습니다.")
        # 발견된 경기 목록 로깅
        for i, schedule in enumerate(schedules[:5], 1):
            logger.info(f"  경기 #{i}: {schedule.text[:80]}...")

        return None

    except Exception as e:
        logger.error(f"날짜 기반 경기 탐색 중 오류: {e}")
        return None


def click_booking_button(driver, game_index: int = 1, game_date: str = "") -> bool:
    """
    예매하기 버튼을 클릭합니다.
    날짜가 지정되면 해당 날짜 경기를 찾아 클릭합니다.

    Args:
        driver: WebDriver 인스턴스
        game_index: 몇 번째 경기를 예매할지 (1부터 시작, game_date가 없을 때)
        game_date: 예매할 경기 날짜 (예: "06.15", "2026-06-15")

    Returns:
        클릭 성공 여부
    """
    # 날짜가 지정되면 날짜 기반으로 game_index 탐색
    if game_date:
        found_index = find_game_by_date(driver, game_date)
        if found_index is not None:
            game_index = found_index
        else:
            logger.warning(f"날짜 '{game_date}' 경기를 찾지 못했습니다. game_index={game_index} 사용")

    try:
        wait = WebDriverWait(driver, 10)

        # 경기 목록에서 n번째 예매하기 버튼 클릭
        selector = (
            f".timeScheduleList .timeSchedule:nth-of-type({game_index}) "
            f".BtnColor_Y.btn1"
        )

        booking_btn = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
        )
        booking_btn.click()
        logger.info(f"[OK] {game_index}번째 경기 예매 버튼 클릭 완료")
        return True

    except Exception as e:
        logger.error(f"예매 버튼 클릭 실패: {e}")

        # 대체 선택자 시도
        try:
            buttons = driver.find_elements(By.CSS_SELECTOR, ".BtnColor_Y.btn1, .btn_book, a[class*='book']")
            if buttons and game_index <= len(buttons):
                buttons[game_index - 1].click()
                logger.info(f"[OK] 대체 선택자로 {game_index}번째 경기 예매 버튼 클릭 성공")
                return True
        except Exception as e2:
            logger.error(f"대체 선택자도 실패: {e2}")

        return False


def switch_to_booking_popup(driver) -> bool:
    """
    예매 팝업 창으로 포커스를 이동합니다.

    Args:
        driver: WebDriver 인스턴스

    Returns:
        전환 성공 여부
    """
    try:
        time.sleep(1)

        # 새 창이 열릴 때까지 대기
        WebDriverWait(driver, 10).until(
            lambda d: len(d.window_handles) > 1
        )

        # 팝업 창으로 전환 (마지막에 열린 창)
        driver.switch_to.window(driver.window_handles[-1])
        logger.info(f"✅ 팝업 창 전환 완료 (총 {len(driver.window_handles)}개 창)")
        time.sleep(0.5)
        return True

    except Exception as e:
        logger.error(f"팝업 전환 실패: {e}")
        return False


def wait_for_queue(driver, timeout: int = 300) -> bool:
    """
    대기열을 통과할 때까지 기다립니다.
    대기열이 없으면 바로 통과합니다.

    Args:
        driver: WebDriver 인스턴스
        timeout: 최대 대기 시간 (초, 기본 5분)

    Returns:
        대기열 통과 여부
    """
    logger.info("대기열 확인 중...")

    try:
        # 좌석 선택 iframe이 나타나면 대기열을 통과한 것
        wait = WebDriverWait(driver, timeout)
        wait.until(
            EC.presence_of_element_located((By.ID, "ifrmSeat"))
        )
        logger.info("✅ 대기열 통과 - 좌석 선택 화면 진입")
        return True

    except Exception as e:
        logger.error(f"대기열 대기 시간 초과 ({timeout}초): {e}")
        return False


def switch_to_seat_iframe(driver) -> bool:
    """
    좌석 선택 iframe으로 전환합니다.

    Args:
        driver: WebDriver 인스턴스

    Returns:
        전환 성공 여부
    """
    try:
        iframe = driver.find_element(By.XPATH, '//iframe[@id="ifrmSeat"]')
        driver.switch_to.frame(iframe)
        time.sleep(0.5)
        logger.info("✅ 좌석 선택 iframe 진입 완료")
        return True

    except Exception as e:
        logger.error(f"iframe 전환 실패: {e}")
        return False


def enter_booking(driver, settings: dict) -> bool:
    """
    경기 선택부터 좌석 선택 iframe 진입까지 전체 과정을 수행합니다.

    Args:
        driver: WebDriver 인스턴스
        settings: 설정 딕셔너리

    Returns:
        성공 여부
    """
    game_index = settings.get("game_index", 1)
    game_date = settings.get("game_date", "")

    # 1. 경기 페이지로 이동
    navigate_to_game(driver, settings)

    # 2. 예매 버튼 클릭 (날짜 지정 시 날짜 기반 탐색)
    if not click_booking_button(driver, game_index, game_date):
        return False

    # 3. 팝업 창 전환
    if not switch_to_booking_popup(driver):
        return False

    # 4. 대기열 통과 대기
    if not wait_for_queue(driver):
        return False

    # 5. 좌석 iframe 진입
    if not switch_to_seat_iframe(driver):
        return False

    return True
