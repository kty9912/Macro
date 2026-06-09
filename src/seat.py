"""
seat.py - 좌석 선택 모듈

설정 기반으로 좌석을 필터링하고,
연속된 좌석을 자동으로 찾아 선택합니다.
"""

import time
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logger = logging.getLogger(__name__)


def parse_seat_info(seat_element) -> dict | None:
    """
    좌석 요소에서 열/번호 정보를 파싱합니다.

    Args:
        seat_element: 좌석 WebElement

    Returns:
        {'row': '1', 'number': 10, 'element': WebElement} 또는 None
    """
    try:
        title = seat_element.get_attribute("title")
        if not title or "-" not in title:
            return None

        parts = title.split("-")
        if len(parts) != 2:
            return None

        row = parts[0].strip().replace("열", "")
        number = int(parts[1].strip())

        return {
            "row": row,
            "number": number,
            "element": seat_element,
            "title": title,
        }
    except (ValueError, AttributeError) as e:
        logger.debug(f"좌석 파싱 실패: {e}")
        return None


def find_available_seats(driver) -> list[dict]:
    """
    현재 페이지에서 선택 가능한 좌석 목록을 가져옵니다.

    Args:
        driver: WebDriver 인스턴스

    Returns:
        파싱된 좌석 정보 리스트
    """
    seat_elements = driver.find_elements(By.CSS_SELECTOR, ".stySeat")
    seats = []

    for elem in seat_elements:
        seat_info = parse_seat_info(elem)
        if seat_info:
            seats.append(seat_info)

    logger.info(f"사용 가능한 좌석 수: {len(seats)}")
    return seats


def find_consecutive_seats(
    seats: list[dict],
    count: int = 2,
    min_number: int = 1,
    max_number: int = 999,
) -> list[dict] | None:
    """
    설정 조건에 맞는 연속 좌석을 찾습니다.

    Args:
        seats: 좌석 정보 리스트
        count: 필요한 연속 좌석 수
        min_number: 최소 좌석 번호
        max_number: 최대 좌석 번호

    Returns:
        연속 좌석 리스트 또는 None
    """
    # 범위 내 좌석만 필터링
    filtered = [
        s for s in seats
        if min_number <= s["number"] <= max_number
    ]

    if len(filtered) < count:
        logger.warning(f"범위 내 좌석이 부족합니다 ({len(filtered)}/{count})")
        return None

    # 행별로 좌석 그룹화
    rows = {}
    for seat in filtered:
        row_key = seat["row"]
        if row_key not in rows:
            rows[row_key] = []
        rows[row_key].append(seat)

    # 각 행에서 연속 좌석 찾기
    for row_key, row_seats in rows.items():
        # 좌석 번호 기준 정렬
        row_seats.sort(key=lambda s: s["number"])

        # 연속 좌석 탐색 (슬라이딩 윈도우)
        for i in range(len(row_seats) - count + 1):
            consecutive = True
            group = [row_seats[i]]

            for j in range(1, count):
                if row_seats[i + j]["number"] == row_seats[i]["number"] + j:
                    group.append(row_seats[i + j])
                else:
                    consecutive = False
                    break

            if consecutive:
                seat_desc = ", ".join(
                    f"{s['row']}열-{s['number']}번" for s in group
                )
                logger.info(f"연속 좌석 발견: {seat_desc}")
                return group

    logger.warning("조건에 맞는 연속 좌석을 찾지 못했습니다.")
    return None


def click_seats(seats: list[dict]) -> bool:
    """
    좌석 요소들을 클릭합니다.

    Args:
        seats: 클릭할 좌석 정보 리스트

    Returns:
        성공 여부
    """
    try:
        for seat in seats:
            seat["element"].click()
            logger.info(f"좌석 클릭: {seat['row']}열-{seat['number']}번")
            time.sleep(0.2)
        return True
    except Exception as e:
        logger.error(f"좌석 클릭 중 오류: {e}")
        return False


def click_zone_select(driver) -> bool:
    """
    구역 선택 후 '좌석선택' 버튼을 클릭합니다.

    Args:
        driver: WebDriver 인스턴스

    Returns:
        성공 여부
    """
    try:
        select_btn = driver.find_element(
            By.XPATH, '//div[@class="twoBtn"]/a[2]'
        )
        select_btn.click()
        time.sleep(0.5)
        logger.info("✅ 좌석선택 버튼 클릭 완료")
        return True
    except Exception as e:
        logger.error(f"좌석선택 버튼 클릭 실패: {e}")
        return False


def handle_alert(driver) -> bool:
    """
    좌석 선택 시 발생할 수 있는 alert을 처리합니다.

    Args:
        driver: WebDriver 인스턴스

    Returns:
        alert이 있었으면 True
    """
    try:
        WebDriverWait(driver, 2).until(EC.alert_is_present())
        alert = driver.switch_to.alert
        alert_text = alert.text
        logger.warning(f"Alert 발생: {alert_text}")
        alert.accept()
        return True
    except Exception:
        return False


def switch_to_seat_detail_iframe(driver) -> bool:
    """
    좌석 상세 선택 iframe으로 전환합니다.

    Args:
        driver: WebDriver 인스턴스

    Returns:
        전환 성공 여부
    """
    try:
        driver.switch_to.default_content()
        iframe = driver.find_element(By.ID, "ifrmSeatDetail")
        driver.switch_to.frame(iframe)
        logger.info("✅ 좌석 상세 iframe 진입")
        return True
    except Exception as e:
        logger.error(f"좌석 상세 iframe 전환 실패: {e}")
        return False


def select_seats(driver, settings: dict, max_retries: int = 3) -> bool:
    """
    좌석 선택 전체 과정을 수행합니다.

    Args:
        driver: WebDriver 인스턴스
        settings: 설정 딕셔너리
        max_retries: 최대 재시도 횟수

    Returns:
        좌석 선택 성공 여부
    """
    seat_pref = settings.get("seat_preference", {})
    consecutive_count = seat_pref.get("consecutive_count", 2)
    min_number = seat_pref.get("min_number", 1)
    max_number = seat_pref.get("max_number", 999)

    # 구역 선택 → 좌석 선택 화면 진입
    click_zone_select(driver)

    for retry in range(max_retries):
        logger.info(f"좌석 선택 시도 {retry + 1}/{max_retries}")

        # 좌석 상세 iframe 전환이 필요할 수 있음
        try:
            # ifrmSeatDetail이 있으면 전환
            detail_iframes = driver.find_elements(By.ID, "ifrmSeatDetail")
            if detail_iframes:
                switch_to_seat_detail_iframe(driver)
        except Exception:
            pass

        # 사용 가능한 좌석 탐색
        available = find_available_seats(driver)
        if not available:
            logger.warning("사용 가능한 좌석이 없습니다.")
            time.sleep(1)
            continue

        # 연속 좌석 찾기
        consecutive = find_consecutive_seats(
            available, consecutive_count, min_number, max_number
        )

        if consecutive:
            # 연속 좌석 클릭
            if click_seats(consecutive):
                # Alert 처리
                if handle_alert(driver):
                    logger.warning("좌석 선택 후 alert 발생 - 재시도")
                    continue
                else:
                    logger.info("✅ 좌석 선택 완료!")
                    return True
        else:
            # 연속 좌석이 없으면 단일 좌석이라도 선택
            if len(available) >= consecutive_count:
                logger.info("연속 좌석 미발견, 조건 완화하여 재탐색...")
                # 전체 범위로 재시도
                consecutive = find_consecutive_seats(
                    available, consecutive_count, 1, 999
                )
                if consecutive and click_seats(consecutive):
                    if not handle_alert(driver):
                        logger.info("✅ 좌석 선택 완료! (확장 범위)")
                        return True

        time.sleep(1)

    logger.error("❌ 좌석 선택 실패")
    return False
