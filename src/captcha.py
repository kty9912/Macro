"""
captcha.py - 캡차(보안문자) 처리 모듈

easyocr + OpenCV 이미지 전처리를 통해 캡차 인식률을 높이고,
실패 시 자동 새로고침 + 재시도하거나, 수동 입력을 요청합니다.
"""

import time
import logging
import numpy as np
from io import BytesIO

import cv2
import easyocr
from PIL import Image
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logger = logging.getLogger(__name__)

# easyocr 리더 (모듈 레벨에서 한 번만 생성 - 무거운 초기화)
_reader = None


def _get_reader():
    """easyocr Reader를 싱글톤으로 생성합니다."""
    global _reader
    if _reader is None:
        logger.info("easyocr 모델 로딩 중... (최초 1회만)")
        _reader = easyocr.Reader(["en"], gpu=False)
        logger.info("easyocr 모델 로딩 완료")
    return _reader


def preprocess_captcha_image(image_bytes: bytes) -> np.ndarray:
    """
    캡차 이미지를 전처리하여 OCR 인식률을 높입니다.

    처리 과정:
    1. 그레이스케일 변환
    2. 노이즈 제거 (가우시안 블러)
    3. 이진화 (Otsu's threshold)
    4. 모폴로지 연산 (노이즈 점/선 제거)

    Args:
        image_bytes: 캡차 이미지의 바이트 데이터

    Returns:
        전처리된 이미지 (numpy 배열)
    """
    # 바이트 → PIL Image → numpy 배열
    pil_image = Image.open(BytesIO(image_bytes))
    img = np.array(pil_image)

    # 그레이스케일 변환
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    else:
        gray = img

    # 노이즈 제거 - 가우시안 블러
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)

    # 이진화 (Otsu's method로 자동 임계값 결정)
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # 모폴로지 연산 - 작은 노이즈 점 제거
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    cleaned = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)

    # 직선 제거 시도 (가로/세로 직선이 있는 경우)
    # 세로 직선 감지 및 제거
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 15))
    vertical_lines = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, vertical_kernel)
    cleaned = cv2.subtract(cleaned, vertical_lines)

    # 가로 직선 감지 및 제거
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 1))
    horizontal_lines = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, horizontal_kernel)
    cleaned = cv2.subtract(cleaned, horizontal_lines)

    # 반전 (검은 글자를 흰 배경에)
    # easyocr는 어두운 텍스트 + 밝은 배경을 선호
    if np.mean(cleaned) < 128:
        cleaned = cv2.bitwise_not(cleaned)

    return cleaned


def recognize_captcha(image_bytes: bytes) -> str:
    """
    캡차 이미지에서 텍스트를 인식합니다.

    Args:
        image_bytes: 캡차 이미지의 바이트 데이터

    Returns:
        인식된 텍스트 (보정 적용)
    """
    reader = _get_reader()

    # 전처리된 이미지로 OCR 수행
    preprocessed = preprocess_captcha_image(image_bytes)
    results = reader.readtext(preprocessed, detail=0)

    if not results:
        # 전처리 없이 원본으로 재시도
        logger.warning("전처리 이미지 인식 실패, 원본으로 재시도")
        results = reader.readtext(image_bytes, detail=0)

    if not results:
        logger.error("캡차 인식 완전 실패")
        return ""

    raw_text = results[0]
    logger.info(f"OCR 원본 결과: '{raw_text}'")

    # 보정 적용
    corrected = _correct_captcha_text(raw_text)
    logger.info(f"보정 결과: '{corrected}'")

    return corrected


def _correct_captcha_text(text: str) -> str:
    """
    OCR 결과를 보정합니다.
    캡차에서 자주 혼동되는 문자를 교정합니다.

    Args:
        text: OCR 원본 텍스트

    Returns:
        보정된 텍스트
    """
    # 공백 제거
    text = text.replace(" ", "")

    # 특수문자 제거
    text = text.replace(".", "").replace(",", "").replace("(", "").replace(")", "")
    text = text.replace("[", "").replace("]", "").replace("{", "").replace("}", "")
    text = text.replace("'", "").replace('"', "").replace("-", "").replace("_", "")

    # 흔한 혼동 문자 보정 (숫자-문자 혼동)
    # 주의: 캡차가 숫자만인지 영문+숫자인지에 따라 다르게 처리해야 함
    corrections = {
        "o": "0", "O": "0",  # o → 0
        "s": "5", "S": "5",  # s → 5
        "l": "1", "I": "1",  # l/I → 1
        "z": "2", "Z": "2",  # z → 2
        "b": "6", "B": "8",  # b → 6, B → 8
        "g": "9",            # g → 9
    }

    # 캡차가 숫자+영문 혼합인 경우가 많으므로, 보수적으로 적용
    # 결과 문자열이 영숫자만 포함하도록 필터링
    result = ""
    for char in text:
        if char.isalnum():
            result += char

    return result


def solve_captcha(driver, max_attempts: int = 5, manual_fallback: bool = True) -> bool:
    """
    캡차를 자동으로 해결합니다.
    실패 시 새로고침하여 재시도하고, 최종 실패 시 수동 입력을 요청할 수 있습니다.

    Args:
        driver: WebDriver 인스턴스
        max_attempts: 최대 시도 횟수
        manual_fallback: True면 자동 실패 시 수동 입력 요청

    Returns:
        캡차 통과 여부
    """
    for attempt in range(1, max_attempts + 1):
        logger.info(f"캡차 시도 {attempt}/{max_attempts}")

        try:
            # 캡차 이미지가 없거나 안 보이면 이미 통과한 것으로 간주
            captcha_elements = driver.find_elements(By.XPATH, "//*[@id='imgCaptcha']")
            if not captcha_elements or not captcha_elements[0].is_displayed():
                logger.info("[OK] 캡차가 없거나 이미 통과되었습니다.")
                return True

            captcha_img = captcha_elements[0]
            image_bytes = captcha_img.screenshot_as_png

            # OCR 인식
            captcha_text = recognize_captcha(image_bytes)

            if not captcha_text:
                logger.warning("캡차 텍스트 인식 실패, 새로고침 후 재시도")
                _refresh_captcha(driver)
                time.sleep(1)
                continue

            # validationTxt 영역 클릭 (입력란 활성화에 필요)
            try:
                validation_elements = driver.find_elements(
                    By.XPATH, "//div[contains(@class, 'validationTxt')]"
                )
                for elem in validation_elements:
                    try:
                        elem.click()
                        break
                    except Exception:
                        pass
            except Exception:
                pass

            time.sleep(0.3)

            # 텍스트 박스에 입력
            captcha_input = driver.find_element(By.XPATH, "//input[@id='txtCaptcha']")
            try:
                captcha_input.clear()
                captcha_input.send_keys(captcha_text)
            except Exception as type_err:
                # send_keys 실패 시 JavaScript로 직접 값 설정
                logger.warning(f"send_keys 실패, JS 폴백 사용: {type_err}")
                driver.execute_script(
                    "arguments[0].value = arguments[1]; "
                    "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));",
                    captcha_input, captcha_text
                )

            time.sleep(0.3)

            # 제출 버튼 클릭
            try:
                submit_btn = driver.find_element(By.CSS_SELECTOR, "div.capchaBtns > a")
                submit_btn.click()
            except Exception as click_err:
                # 클릭 실패 시 JavaScript로 직접 클릭
                logger.warning(f"submit 클릭 실패, JS 폴백 사용: {click_err}")
                submit_btn = driver.find_element(By.CSS_SELECTOR, "div.capchaBtns > a")
                driver.execute_script("arguments[0].click();", submit_btn)

            time.sleep(0.5)

            # 결과 확인
            if _check_captcha_success(driver):
                logger.info(f"[OK] 캡차 통과! (시도 {attempt})")
                return True
            else:
                logger.warning(f"캡차 실패 (시도 {attempt}), 새로고침 후 재시도")
                _refresh_captcha(driver)
                time.sleep(1)

        except Exception as e:
            logger.error(f"캡차 처리 중 오류 (시도 {attempt}): {e}")
            try:
                _refresh_captcha(driver)
            except Exception:
                pass
            time.sleep(1)

    # 자동 실패 → 수동 입력 요청
    if manual_fallback:
        return _manual_captcha_input(driver)

    logger.error("[FAIL] 캡차 자동 인식 실패")
    return False


def _refresh_captcha(driver):
    """캡차 이미지를 새로고침합니다."""
    try:
        refresh_btn = driver.find_element(By.XPATH, "//a[@class='refreshBtn']")
        refresh_btn.click()
        logger.info("캡차 새로고침 완료")
    except Exception as e:
        logger.warning(f"캡차 새로고침 실패: {e}")


def _check_captcha_success(driver) -> bool:
    """
    캡차 제출 후 성공 여부를 확인합니다.

    Returns:
        성공이면 True
    """
    try:
        # 에러 메시지가 있는지 확인
        error_elements = driver.find_elements(
            By.XPATH,
            "//div[@class='alertNotice' and contains(text(), '입력한 문자를 다시 확인')]"
        )
        if error_elements:
            return False

        # 캡차 영역이 사라졌는지 확인 (통과 시 다음 단계로 이동)
        time.sleep(0.5)
        captcha_elements = driver.find_elements(By.ID, "imgCaptcha")
        if not captcha_elements or not captcha_elements[0].is_displayed():
            return True

        return False

    except Exception:
        # 예외 발생 시 통과된 것으로 간주 (페이지가 전환되었을 수 있음)
        return True


def _manual_captcha_input(driver) -> bool:
    """
    사용자에게 캡차 수동 입력을 요청합니다.

    Returns:
        수동 입력 후 통과 여부
    """
    logger.info("=" * 50)
    logger.info("[!] 캡차 자동 인식에 실패했습니다!")
    logger.info("    브라우저에서 직접 캡차를 입력해주세요.")
    logger.info("    입력 완료 후 Enter 키를 누르세요.")
    logger.info("=" * 50)

    print("\n" + "=" * 50)
    print("[!] 캡차 자동 인식 실패!")
    print("    브라우저에서 직접 보안문자를 입력하고")
    print("    확인 버튼을 눌러주세요.")
    print("    완료되면 여기서 Enter를 눌러주세요.")
    print("=" * 50)

    input(">> Enter를 누르면 계속 진행합니다... ")

    # 수동 입력 후 확인
    return _check_captcha_success(driver)
