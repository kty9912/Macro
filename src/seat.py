"""
seat.py - 좌석 선택 모듈

취소표 잡기 플로우:
  1. 자리가 있는 구역 탐색 및 선택
  2. 좌석 선택 화면 진입
  3. 빈 좌석 빠르게 선택
  4. 예매 버튼 클릭
  5. "이미 선점된 좌석입니다" 감지 → PREEMPTED 반환
"""

import time
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import UnexpectedAlertPresentException, NoAlertPresentException

logger = logging.getLogger(__name__)

# 좌석 선택 결과 상수
SEAT_SUCCESS = "success"           # 좌석 선택 성공 → 결제로 진행
SEAT_PREEMPTED = "preempted"       # "이미 선점된 좌석" → 새로고침 필요
SEAT_NO_SEATS = "no_seats"         # 빈 좌석 없음
SEAT_ERROR = "error"               # 기타 오류


def select_available_zone(driver, settings: dict, ignore_zones: set = None) -> str | None:
    """
    구역 목록에서 '매진'이 아닌 구역을 찾아 클릭합니다.
    settings에 지정된 preferred_zones가 있으면 우선적으로 선택합니다.

    Args:
        driver: WebDriver 인스턴스
        settings: 설정 딕셔너리

    Returns:
        선택된 구역의 이름(문자열), 실패 시 None, 오류 시 "ERROR"
    """
    settings = settings or {}
    preferred_zones = settings.get("seat_preference", {}).get("preferred_zones", [])
    ignore_zones = ignore_zones or set()

    try:
        # 구역/등급 목록 가져오기 (다양한 선택자 시도 - 최신 SeatGradeLayer 최우선)
        zone_selectors = [
            "li[class*='SeatGradeLayer_item']",
            "div[class*='SeatGradeLayer_grade']",
            ".gradeList > li",
            ".blockList > li",
            "ul.seatList > li",
            "ul[class*='grade'] > li",
            "ul[class*='block'] > li",
            ".seatGroupList li",
            ".blockGroup li",
            ".section-list li",
            "div[class*='grade'] li",
            "div[class*='block'] li",
            "div[class*='block'] a",
            "area[title]", # SVG map area
            "//li[contains(text(), '석') or contains(text(), '구역')]",
            "//a[contains(text(), '석') or contains(text(), '구역')]",
            "//span[contains(text(), '석') or contains(text(), '구역')]/.."
        ]

        # 빠른 탐색을 위해 암묵적 대기 시간 임시 해제
        driver.implicitly_wait(0)
        
        # 2단계 선택(등급 -> 구역)을 위해 최대 2번 클릭을 시도합니다.
        click_count = 0
        first_pass_zones = set()

        for pass_idx in range(2):
            valid_zones = []

            for selector in zone_selectors:
                if selector.startswith("//"):
                    zones = driver.find_elements(By.XPATH, selector)
                else:
                    zones = driver.find_elements(By.CSS_SELECTOR, selector)
                
                if not zones:
                    continue

                for zone in zones:
                    # 요소가 화면에 보이지 않으면 패스
                    if not zone.is_displayed():
                        continue

                    # 최신 원스톱 등급명 추출 지원
                    name_els = zone.find_elements(By.CSS_SELECTOR, "div[class*='gradeName'], [class*='GradeName']")
                    if name_els and name_els[0].text:
                        zone_text = name_els[0].text
                    else:
                        zone_text = zone.text if zone.text else zone.get_attribute("title")
                    if not zone_text:
                        continue
                        
                    zone_desc = zone_text.replace(chr(10), ' ').strip()[:30]

                    # 휠체어석 제외
                    if "휠체어" in zone_text:
                        if pass_idx == 0: logger.info(f"[SKIP] 휠체어석 제외: {zone_desc}")
                        continue

                    # 연속 좌석 수보다 적은 잔여석 구역 패스
                    import re
                    seat_count_match = re.search(r'(\d+)\s*석', zone_text)
                    if seat_count_match:
                        available_seats_in_zone = int(seat_count_match.group(1))
                        consecutive_count = settings.get("seat_preference", {}).get("consecutive_count", 2)
                        if available_seats_in_zone < consecutive_count:
                            if pass_idx == 0: logger.info(f"[SKIP] 잔여석 부족 ({available_seats_in_zone}석 < 필요 {consecutive_count}석): {zone_desc}")
                            continue

                    # 매진/품절/선택불가/0석 상태 확인
                    is_soldout = any(keyword in zone_text for keyword in ["매진", "품절", "마감", "선택불가", "0석", "0 석"])
                    zone_class = zone.get_attribute("class") or ""
                    is_disabled = any(keyword in zone_class for keyword in ["disabled", "soldout", "sold-out", "off"])

                    if is_soldout or is_disabled:
                        if pass_idx == 0: logger.info(f"[SKIP] 매진/불가 구역: {zone_desc}")
                        continue

                    # 이미 탐색하여 실패한(빈자리 없는) 구역이면 패스
                    if zone_desc in ignore_zones:
                        if pass_idx == 0: logger.info(f"[SKIP] 이미 탐색한 구역 (눈밭): {zone_desc}")
                        continue

                    # 이미 선택된 상태(active/on/selected 등)면 패스
                    if any(k in zone_class for k in ["active", "on", "selected", "chk"]):
                        if pass_idx == 0: logger.info(f"[SKIP] 이미 선택됨: {zone_desc}")
                        continue

                    valid_zones.append((zone, zone_desc))
                
                # 하나라도 유효한 구역을 찾았으면 이 선택자 결과만 사용
                if valid_zones:
                    break

            if not valid_zones:
                break

            # preferred_zones 기준 정렬 로직
            def get_priority(item):
                z, desc = item
                for i, pref in enumerate(preferred_zones):
                    if pref in desc:
                        return i
                return 999  # 선호도 목록에 없으면 후순위

            valid_zones.sort(key=get_priority)

            # 첫 번째 패스에서 찾은 유효한 구역 목록 저장
            if pass_idx == 0:
                first_pass_zones = {desc for _, desc in valid_zones}

            best_zone, best_desc = valid_zones[0]

            # 두 번째 패스일 때: 새로 등장한 하위 구역(블록)이 아니면, 
            # 단순히 다음 등급을 클릭하는 것이므로 중단함.
            if pass_idx == 1 and best_desc in first_pass_zones:
                break

            # 클릭 시도
            try:
                best_zone.click()
                logger.info(f"[OK] 구역/등급 선택: {best_desc}")
                time.sleep(0.5)
                click_count += 1
            except Exception:
                try:
                    driver.execute_script("arguments[0].click();", best_zone)
                    logger.info(f"[OK] 구역/등급 선택 (JS): {best_desc}")
                    time.sleep(0.5)
                    click_count += 1
                except Exception:
                    logger.warning(f"[FAIL] 구역/등급 클릭 실패: {best_desc}")

        if click_count > 0:
            driver.implicitly_wait(2)
            return best_desc
        else:
            logger.warning("매진되지 않은 구역/등급을 찾지 못했거나 이미 모두 선택되어 있습니다.")
            try:
                html = driver.find_element(By.TAG_NAME, "body").get_attribute("innerHTML")
                import os, datetime
                os.makedirs("logs", exist_ok=True)
                dump_path = f"logs/seat_iframe_{datetime.datetime.now().strftime('%H%M%S')}.html"
                with open(dump_path, "w", encoding="utf-16") as f:
                    f.write(html)
                logger.debug(f"iframe HTML 덤프 저장 완료: {dump_path}")
            except Exception as e:
                logger.debug(f"HTML 덤프 실패: {e}")
            
            driver.implicitly_wait(2)
            return None

    except Exception as e:
        logger.error(f"구역 선택 중 오류: {e}")
        driver.implicitly_wait(2)
        return "ERROR"


def click_seat_select_button(driver) -> bool:
    """
    '좌석선택' 버튼을 클릭합니다.

    Args:
        driver: WebDriver 인스턴스

    Returns:
        성공 여부
    """
    selectors = [
        '//div[@class="twoBtn"]/a[2]',
        '//a[contains(text(), "좌석선택")]',
        '//a[contains(text(), "좌석 선택")]',
        '//button[contains(text(), "좌석선택")]',
    ]

    for xpath in selectors:
        try:
            btn = driver.find_element(By.XPATH, xpath)
            if btn.is_displayed():
                btn.click()
                logger.info("[OK] 좌석선택 버튼 클릭")
                time.sleep(0.5)
                return True
        except Exception:
            continue

    # JS 폴백
    try:
        btn = driver.find_element(By.XPATH, '//div[@class="twoBtn"]/a[2]')
        driver.execute_script("arguments[0].click();", btn)
        logger.info("[OK] 좌석선택 버튼 클릭 (JS)")
        time.sleep(0.5)
        return True
    except Exception as e:
        logger.error(f"좌석선택 버튼 클릭 실패: {e}")
        return False


def parse_seat_info(seat_element) -> dict | None:
    """좌석 요소에서 열/번호 정보를 파싱합니다."""
    try:
        title = seat_element.get_attribute("title")
        if not title:
            # title이 없으면 text나 aria-label 등을 확인
            title = seat_element.text or seat_element.get_attribute("aria-label")
            
        if not title or not title.strip():
            return None  # 정보가 없는 빈 껍데기 요소는 좌석으로 취급하지 않음

        # 다양한 형식 파싱 대응
        row = "1"
        number = 1
        
        if "-" in title:
            parts = title.split("-")
            if len(parts) >= 2:
                row = parts[-2].strip().replace("열", "")
                # 숫자가 아닌 문자가 섞여있을 수 있으므로 예외 처리
                try:
                    import re
                    num_str = re.sub(r'[^0-9]', '', parts[-1])
                    number = int(num_str) if num_str else 1
                except:
                    number = 1
        else:
            # "3열 15번" 같은 형식 처리
            import re
            row_match = re.search(r'(\d+)열', title)
            if row_match:
                row = row_match.group(1)
            num_match = re.search(r'(\d+)번', title)
            if num_match:
                number = int(num_match.group(1))
            else:
                # 숫자만 추출 시도
                nums = re.findall(r'\d+', title)
                if nums:
                    number = int(nums[-1])

        return {
            "row": row,
            "number": number,
            "element": seat_element,
            "title": title,
        }
    except Exception as e:
        logger.debug(f"좌석 파싱 실패: {e}")
        return None

def find_available_seats(driver) -> list[dict]:
    """현재 페이지에서 선택 가능한 좌석 목록을 가져옵니다."""
    selectors = [
        ".stySeat",
        "rect[class*='seat']:not([class*='soldout']):not([class*='disabled'])",
        "rect.seat",
        "circle.seat",
        "[class*='Seat']:not([class*='List']):not([class*='Group'])",
        "a.seat",
        "div.seat",
        ".seat_area > a",
        "area[title]"
    ]
    
    combined_selector = ", ".join(selectors)
    
    # 1. 명시적 대기: 빈 좌석이 하나라도 나타날 때까지 대기 (최대 3초)
    try:
        WebDriverWait(driver, 3).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, combined_selector))
        )
    except:
        pass  # 로딩이 안 되거나 진짜 없으면 넘어감

    # 2. 암묵적 대기 끄기 (빠른 탐색)
    driver.implicitly_wait(0)
    
    seat_elements = []
    for selector in selectors:
        elements = driver.find_elements(By.CSS_SELECTOR, selector)
        if elements:
            seat_elements = elements
            logger.info(f"좌석 요소 발견: {len(elements)}개 (선택자: {selector})")
            break
            
    # 암묵적 대기 복구
    driver.implicitly_wait(2)

    seats = []
    for elem in seat_elements:
        seat_info = parse_seat_info(elem)
        if seat_info:
            seats.append(seat_info)

    logger.info(f"사용 가능한 좌석 수: {len(seats)}")
    
    if not seats:
        try:
            html = driver.find_element(By.TAG_NAME, "body").get_attribute("innerHTML")
            import os, datetime
            os.makedirs("logs", exist_ok=True)
            dump_path = f"logs/seat_map_{datetime.datetime.now().strftime('%H%M%S')}.html"
            with open(dump_path, "w", encoding="utf-16") as f:
                f.write(html)
            logger.debug(f"좌석맵 HTML 덤프 저장 완료: {dump_path}")
        except Exception as e:
            logger.debug(f"좌석맵 HTML 덤프 실패: {e}")

    return seats


def find_consecutive_seats(
    seats: list[dict],
    count: int = 2,
    min_number: int = 1,
    max_number: int = 999,
) -> list[dict] | None:
    """설정 조건에 맞는 연속 좌석을 찾습니다."""
    filtered = [
        s for s in seats
        if min_number <= s["number"] <= max_number
    ]

    if len(filtered) < count:
        return None

    # 행별로 좌석 그룹화
    rows = {}
    for seat in filtered:
        row_key = seat["row"]
        if row_key not in rows:
            rows[row_key] = []
        rows[row_key].append(seat)

    # 각 행에서 연속 좌석 찾기 (슬라이딩 윈도우)
    for row_key, row_seats in rows.items():
        row_seats.sort(key=lambda s: s["number"])

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

    return None


def click_seats(driver, seats: list[dict]) -> bool:
    """좌석 요소들을 클릭합니다."""
    try:
        for seat in seats:
            try:
                seat["element"].click()
            except Exception:
                driver.execute_script("arguments[0].click();", seat["element"])
            logger.info(f"좌석 클릭: {seat['row']}열-{seat['number']}번")
            time.sleep(0.1)
        return True
    except Exception as e:
        logger.error(f"좌석 클릭 중 오류: {e}")
        return False


def check_alert_text(driver, timeout: float = 2) -> str | None:
    """
    Alert이 있으면 텍스트를 반환하고 닫습니다.

    Returns:
        Alert 텍스트 또는 None
    """
    try:
        WebDriverWait(driver, timeout).until(EC.alert_is_present())
        alert = driver.switch_to.alert
        alert_text = alert.text
        logger.warning(f"Alert 발생: {alert_text}")
        alert.accept()
        return alert_text
    except Exception:
        return None


def click_proceed_button(driver) -> bool:
    """
    좌석 선택 완료 후 '예매하기'/'다음단계'/'좌석선택완료' 버튼을 클릭합니다.

    Returns:
        성공 여부
    """
    proceed_selectors = [
        '//a[contains(text(), "좌석선택완료")]',
        '//a[contains(text(), "다음단계")]',
        '//a[contains(text(), "예매하기")]',
        '//a[contains(text(), "결제")]',
        '//button[contains(text(), "다음")]',
        '//a[contains(@class, "btn_next")]',
        '//div[@class="twoBtn"]/a[contains(@class, "btn")]',
        '//img[@alt="좌석선택완료"]/..',
        '//img[contains(@src, "btn_seat_com")]/..'
    ]
    
    combined_xpath = " | ".join(proceed_selectors)

    # 딜레이를 없애기 위해 암묵적 대기 끄기
    driver.implicitly_wait(0)

    def _try_click_proceed() -> bool:
        try:
            btns = driver.find_elements(By.XPATH, combined_xpath)
            for btn in btns:
                if btn.is_displayed():
                    # 버튼 클릭 시 JS fallback까지 시도
                    try:
                        btn.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", btn)
                    return True
        except Exception:
            pass
        return False

    success = False

    # 1. 현재 컨텍스트(보통 ifrmSeatDetail)에서 탐색
    if _try_click_proceed():
        logger.info("[OK] 진행 버튼 클릭 (현재 프레임)")
        success = True
    else:
        # 2. ifrmSeat(부모 프레임)에서 탐색
        try:
            driver.switch_to.default_content()
            iframe = driver.find_element(By.ID, "ifrmSeat")
            driver.switch_to.frame(iframe)
            if _try_click_proceed():
                logger.info("[OK] 진행 버튼 클릭 (ifrmSeat 프레임)")
                success = True
        except Exception:
            pass

        # 3. 최상위(default_content)에서 탐색
        if not success:
            try:
                driver.switch_to.default_content()
                if _try_click_proceed():
                    logger.info("[OK] 진행 버튼 클릭 (최상위 프레임)")
                    success = True
            except Exception:
                pass

    # 암묵적 대기 복구
    driver.implicitly_wait(2)

    if success:
        return True
        
    logger.warning("진행 버튼을 찾지 못했습니다.")
    return False


def switch_to_seat_detail_iframe(driver) -> bool:
    """좌석 상세 선택 iframe으로 전환합니다."""
    try:
        # 먼저 현재 컨텍스트(ifrmSeat) 내부에서 탐색
        iframe = driver.find_element(By.ID, "ifrmSeatDetail")
        driver.switch_to.frame(iframe)
        logger.info("[OK] 좌석 상세 iframe 진입 (현재 프레임 내부)")
        return True
    except Exception:
        # 없으면 default_content로 가서 찾아보기
        try:
            driver.switch_to.default_content()
            iframe = driver.find_element(By.ID, "ifrmSeatDetail")
            driver.switch_to.frame(iframe)
            logger.info("[OK] 좌석 상세 iframe 진입 (최상위)")
            return True
        except Exception as e:
            # 그래도 없으면 다시 ifrmSeat으로 복귀 (보통 여기에 좌석들이 있음)
            try:
                iframe = driver.find_element(By.ID, "ifrmSeat")
                driver.switch_to.frame(iframe)
            except:
                pass
            logger.debug(f"좌석 상세 iframe 없음: {e}")
            return False


def attempt_seat_selection(driver, settings: dict) -> str:
    """
    좌석 선택 1회 시도를 수행합니다.
    
    전체 흐름:
      구역 선택 -> 좌석선택 버튼 -> 빈 좌석 탐색/클릭 -> 예매 진행 버튼
      
    Returns:
        SEAT_SUCCESS: 좌석 선택 성공
        SEAT_PREEMPTED: "이미 선점된 좌석" -> 재시도 필요
        SEAT_NO_SEATS: 빈 좌석 없음
        SEAT_ERROR: 기타 오류
    """
    try:
        seat_pref = settings.get("seat_preference", {})
        consecutive_count = seat_pref.get("consecutive_count", 2)
        min_number = seat_pref.get("min_number", 1)
        max_number = seat_pref.get("max_number", 999)

        ignore_zones = set()

        while True:
            # 1. 구역 선택
            selected_zone = select_available_zone(driver, settings, ignore_zones)
            if selected_zone == "ERROR":
                return SEAT_ERROR
            elif not selected_zone:
                if not ignore_zones:
                    logger.warning("매진되지 않은 구역/등급을 찾지 못했거나 이미 모두 선택되어 있습니다.")
                else:
                    logger.warning("남아있는 모든 유효 구역을 탐색했으나 자리가 없습니다.")
                return SEAT_NO_SEATS

            # 2. 좌석선택 버튼 클릭
            click_seat_select_button(driver)

            # 3. 좌석 상세 iframe 전환
            if not switch_to_seat_detail_iframe(driver):
                # 프레임 전환 실패 시 무시하고 다음 구역 탐색
                ignore_zones.add(selected_zone)
                driver.switch_to.default_content()
                try: driver.switch_to.frame(driver.find_element(By.ID, "ifrmSeat"))
                except: pass
                continue

            # 4. 빈 좌석 탐색
            available = find_available_seats(driver)
            if not available:
                logger.info(f"[{selected_zone}] 구역에 실제 빈 좌석(눈밭)이 없어 다음 구역으로 넘어갑니다.")
                ignore_zones.add(selected_zone)
                driver.switch_to.default_content()
                try: driver.switch_to.frame(driver.find_element(By.ID, "ifrmSeat"))
                except: pass
                continue

            # 5. 연속 좌석 찾기 (범위 내 -> 전체 범위 순서)
            consecutive = find_consecutive_seats(
                available, consecutive_count, min_number, max_number
            )
            if not consecutive:
                logger.info("선호 범위에 연속 좌석 없음, 전체 범위로 재탐색...")
                consecutive = find_consecutive_seats(available, consecutive_count, 1, 999)

            if not consecutive:
                # 연속 좌석이 없으면 단일 좌석 선택 시도
                logger.info("연속 좌석 없음, 단일 좌석이라도 선택합니다.")
                consecutive = available[:consecutive_count] if len(available) >= consecutive_count else available[:1]

            if not consecutive:
                logger.info(f"[{selected_zone}] 구역에 유효한 좌석이 없어 다음 구역으로 넘어갑니다.")
                ignore_zones.add(selected_zone)
                driver.switch_to.default_content()
                try: driver.switch_to.frame(driver.find_element(By.ID, "ifrmSeat"))
                except: pass
                continue

            # 6. 좌석 클릭
            if not click_seats(driver, consecutive):
                return SEAT_ERROR

            time.sleep(0.3)
            break

        # 7. Alert 확인 (좌석 클릭 직후)
        alert_text = check_alert_text(driver, timeout=1)
        if alert_text:
            if "선점" in alert_text or "이미" in alert_text:
                logger.warning(f"[!] 선점된 좌석: {alert_text}")
                return SEAT_PREEMPTED
            else:
                logger.warning(f"[!] 기타 Alert: {alert_text}")
                return SEAT_ERROR

        # 8. 예매 진행 버튼 클릭
        if not click_proceed_button(driver):
            # 버튼을 찾지 못하면 성공으로 간주할 수 없음
            return SEAT_ERROR

        # 9. 진행 후 Alert 확인 (예매 버튼 클릭 후에도 나올 수 있음)
        alert_text = check_alert_text(driver, timeout=2)
        if alert_text:
            if "선점" in alert_text or "이미" in alert_text:
                logger.warning(f"[!] 선점된 좌석 (진행 후): {alert_text}")
                return SEAT_PREEMPTED
            else:
                logger.warning(f"[!] 기타 Alert (진행 후): {alert_text}")
                return SEAT_ERROR

        logger.info("[OK] 좌석 선택 성공!")
        return SEAT_SUCCESS

    except UnexpectedAlertPresentException as e:
        logger.error(f"예상치 못한 Alert 창 발생: {e.alert_text}")
        try:
            alert = driver.switch_to.alert
            alert.accept()
        except Exception:
            pass
        return SEAT_ERROR
    except Exception as e:
        logger.error(f"좌석 선택 중 예상치 못한 오류: {e}")
        return SEAT_ERROR

# 하위 호환성을 위한 래퍼 (기존 main.py에서 호출)
def select_seats(driver, settings: dict, max_retries: int = 3) -> bool:
    """
    좌석 선택 (단일 시도용 래퍼).
    취소표 잡기 루프는 main.py에서 처리합니다.
    """
    result = attempt_seat_selection(driver, settings)
    return result == SEAT_SUCCESS
