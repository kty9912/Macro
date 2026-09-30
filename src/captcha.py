"""
captcha.py - 캡차(보안문자) 처리 모듈

NOL/인터파크 최신 원스톱(ModalCaptchaText) 및 기존 구형 캡차(ifrmSeat/imgCaptcha)를
모두 지원합니다.
EasyOCR + OpenCV 이미지 전처리를 통해 인식률을 극대화하고,
base64 이미지 직독 및 React State 자동 동기화를 수행합니다.
"""

import time
import base64
import logging
import numpy as np
from io import BytesIO

import cv2
import easyocr
from PIL import Image
from selenium.webdriver.common.by import By

logger = logging.getLogger(__name__)

# EasyOCR 싱글톤 리더
_reader = None


def _get_reader():
    """easyocr Reader를 싱글톤으로 생성합니다."""
    global _reader
    if _reader is None:
        logger.info("EasyOCR 모델 로딩 중... (최초 1회)")
        _reader = easyocr.Reader(["en"], gpu=False)
        logger.info("EasyOCR 모델 로딩 완료")
    return _reader


def preprocess_captcha_image(image_bytes: bytes) -> np.ndarray:
    """
    캡차 이미지를 전처리하여 OCR 인식률을 높입니다.
    """
    pil_image = Image.open(BytesIO(image_bytes))
    img = np.array(pil_image)

    # 그레이스케일 변환
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    else:
        gray = img

    # 가우시안 블러
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)

    # 이진화 (Otsu)
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # 모폴로지 연산 - 노이즈 점 제거
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    cleaned = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)

    # 반전 (밝은 배경에 어두운 텍스트)
    if np.mean(cleaned) < 128:
        cleaned = cv2.bitwise_not(cleaned)

    return cleaned


def recognize_captcha(image_bytes: bytes) -> str:
    """
    캡차 이미지에서 텍스트를 인식합니다 (영문 대문자 6자리 보정).
    """
    try:
        reader = _get_reader()

        # 1. 원본 인식 시도
        pil_image = Image.open(BytesIO(image_bytes))
        img_np = np.array(pil_image)
        results = reader.readtext(img_np, detail=0)

        # 2. 전처리 이미지로 재시도
        if not results:
            preprocessed = preprocess_captcha_image(image_bytes)
            results = reader.readtext(preprocessed, detail=0)

        raw_text = "".join(results).strip()
        logger.info(f"캡차 OCR 원본 결과: '{raw_text}'")

        # 3. 텍스트 보정 (영문 대문자만 추출 및 오인식 숫자 교정)
        text = _clean_captcha_text(raw_text)
        logger.info(f"캡차 보정 후 결과: '{text}'")

        return text

    except Exception as e:
        logger.error(f"캡차 OCR 인식 실패: {e}")
        return ""


def _clean_captcha_text(text: str) -> str:
    """
    인터파크 캡차 특성에 맞게 보정합니다 (대문자 6글자).
    """
    # 숫자 -> 알파벳 오인식 교정 맵
    replacements = {
        '0': 'O',
        '1': 'I',
        '2': 'Z',
        '5': 'S',
        '8': 'B',
        '6': 'G',
    }

    cleaned = ""
    for ch in text.upper():
        if ch in replacements:
            cleaned += replacements[ch]
        elif ch.isalpha():
            cleaned += ch

    return cleaned[:6]


def is_captcha_present(driver) -> bool:
    """
    화면에 캡차 모달 또는 이미지가 표시되고 있는지 확인합니다.
    """
    try:
        # 1. 최신 원스톱 모달 셀렉터
        new_modals = driver.find_elements(By.CSS_SELECTOR, "div[class*='ModalCaptchaText'], div[class*='modalCaptcha']")
        for m in new_modals:
            if m.is_displayed():
                return True

        # 2. 구형 캡차 셀렉터
        legacy_imgs = driver.find_elements(By.ID, "imgCaptcha")
        for img in legacy_imgs:
            if img.is_displayed():
                return True

        return False
    except Exception:
        return False


def get_captcha_image_bytes(driver) -> bytes | None:
    """
    현재 화면의 캡차 이미지 바이트를 추출합니다 (base64 직독 또는 스크린샷).
    """
    try:
        # 1. 최신 원스톱 캡차 이미지
        images = driver.find_elements(By.CSS_SELECTOR, "div[class*='captchaImage'] img, div[class*='ModalCaptchaText'] img")
        for img in images:
            if img.is_displayed():
                src = img.get_attribute("src") or ""
                if "base64," in src:
                    base64_data = src.split("base64,")[1]
                    return base64.b64decode(base64_data)
                return img.screenshot_as_png

        # 2. 구형 캡차 이미지
        legacy_imgs = driver.find_elements(By.ID, "imgCaptcha")
        for img in legacy_imgs:
            if img.is_displayed():
                return img.screenshot_as_png

        return None
    except Exception as e:
        logger.error(f"캡차 이미지 추출 중 오류: {e}")
        return None


def solve_captcha(driver, max_attempts: int = 5, manual_fallback: bool = True) -> bool:
    """
    캡차를 자동으로 감지하고 입력/통과합니다.
    """
    # 캡차가 아예 없으면 즉시 통과
    if not is_captcha_present(driver):
        logger.info("✅ 캡차가 없거나 이미 통과된 상태입니다.")
        return True

    print("\n🔐 [보안문자 감지] 캡차 자동 인식을 시작합니다...")

    for attempt in range(1, max_attempts + 1):
        logger.info(f"캡차 자동 시도 {attempt}/{max_attempts}")

        if not is_captcha_present(driver):
            logger.info("✅ 캡차가 사라졌습니다 (통과 완료).")
            return True

        # 1. 이미지 바이트 추출
        image_bytes = get_captcha_image_bytes(driver)
        if not image_bytes:
            logger.warning("캡차 이미지를 가져올 수 없습니다. 재시도...")
            time.sleep(0.5)
            continue

        # 2. OCR 인식
        captcha_text = recognize_captcha(image_bytes)
        if not captcha_text or len(captcha_text) < 4:
            logger.warning(f"인식 결과 불충분 ('{captcha_text}'). 새로고침 후 재시도...")
            _refresh_captcha(driver)
            time.sleep(0.6)
            continue

        # 3. 입력창 탐색 및 텍스트 주입 (React Event 트리거 포함)
        input_el = None
        input_selectors = [
            "input[class*='captchaInput']",
            "input.ModalCaptchaText_captchaInput__DC7Gz",
            "input#txtCaptcha",
            "input[placeholder*='문자']",
        ]
        for sel in input_selectors:
            found = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in found:
                if el.is_displayed():
                    input_el = el
                    break
            if input_el:
                break

        if not input_el:
            logger.error("캡차 입력 필드를 찾지 못했습니다.")
            continue

        try:
            input_el.clear()
            # React의 synthetic event 및 value setter를 호출하여 입력완료 버튼의 disabled 해제
            driver.execute_script("""
                const input = arguments[0];
                const value = arguments[1];
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
                nativeInputValueSetter.call(input, value);
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
            """, input_el, captcha_text)
            time.sleep(0.1)
        except Exception as e:
            logger.debug(f"JS 입력 중 오류, send_keys 폴백: {e}")
            input_el.send_keys(captcha_text)

        time.sleep(0.2)

        # 4. 제출/입력완료 버튼 클릭
        submit_btn = None
        submit_selectors = [
            "button.entButtonGlobal",
            "footer[class*='ModalLayout_footer'] button",
            "//button[contains(text(), '입력완료')]",
            "//button[contains(text(), '확인')]",
            "div.capchaBtns > a",
        ]
        for sel in submit_selectors:
            try:
                found = driver.find_elements(By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel)
                for btn in found:
                    if btn.is_displayed():
                        submit_btn = btn
                        break
                if submit_btn:
                    break
            except Exception:
                continue

        if submit_btn:
            try:
                driver.execute_script("arguments[0].click();", submit_btn)
            except Exception:
                submit_btn.click()
            logger.info("제출 버튼 클릭 완료")

        time.sleep(0.8)

        # 5. 모달이 닫혔는지 확인
        if not is_captcha_present(driver):
            logger.info(f"🎉 캡차 통과 성공! (시도 {attempt})")
            print("✅ 캡차 자동 통과 성공!\n")
            return True
        else:
            logger.warning(f"캡차 불일치 (시도 {attempt}). 새로고침 후 다시 시도합니다.")
            _refresh_captcha(driver)
            time.sleep(0.6)

    # 자동 실패 시 수동 입력 폴백
    if manual_fallback:
        return _manual_captcha_input(driver)

    logger.error("❌ 캡차 자동 통과 실패")
    return False


def _refresh_captcha(driver):
    """캡차 이미지를 새로고침합니다."""
    try:
        refresh_selectors = [
            "button[class*='buttonRefresh']",
            "button[aria-label*='새로고침']",
            "button[aria-label*='불러']",
            "//a[@class='refreshBtn']",
        ]
        for sel in refresh_selectors:
            found = driver.find_elements(By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel)
            for btn in found:
                if btn.is_displayed():
                    driver.execute_script("arguments[0].click();", btn)
                    logger.info("캡차 새로고침 클릭 완료")
                    return
    except Exception as e:
        logger.warning(f"캡차 새로고침 실패: {e}")


def _manual_captcha_input(driver) -> bool:
    """
    자동 인식 실패 시 사용자가 직접 브라우저에서 입력하도록 대기합니다.
    """
    print()
    print("=" * 60)
    print("  ⚠️ [캡차 수동 입력 안내]")
    print("  - 브라우저 화면의 캡차(보안문자)를 직접 입력하고 [입력완료]를 눌러주세요.")
    print("  - 완료 후 터미널에서 [Enter]를 누르면 즉시 좌석 선택으로 이어집니다.")
    print("=" * 60)
    print()

    input("👉 캡차 입력 완료 후 [Enter]를 누르세요... ")
    time.sleep(0.5)
    return True
