"""
payment.py - 결제 처리 모듈

결제 페이지 진입까지 자동화하고,
최종 결제는 사용자에게 맡깁니다 (보안상).
시스템 알림으로 사용자에게 통지합니다.
"""

import time
import logging
import platform
import subprocess

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logger = logging.getLogger(__name__)


def notify_user(title: str, message: str):
    """
    시스템 알림을 통해 사용자에게 통지합니다.
    Windows, macOS 모두 지원합니다.

    Args:
        title: 알림 제목
        message: 알림 메시지
    """
    system = platform.system()

    try:
        if system == "Windows":
            # Windows: PowerShell 알림
            ps_script = f"""
            [System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null
            $notify = New-Object System.Windows.Forms.NotifyIcon
            $notify.Icon = [System.Drawing.SystemIcons]::Information
            $notify.Visible = $true
            $notify.ShowBalloonTip(10000, '{title}', '{message}', 'Info')
            Start-Sleep -Seconds 5
            $notify.Dispose()
            """
            subprocess.Popen(
                ["powershell", "-Command", ps_script],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        elif system == "Darwin":
            # macOS: osascript
            subprocess.Popen([
                "osascript", "-e",
                f'display notification "{message}" with title "{title}"'
            ])
        else:
            # Linux: notify-send
            subprocess.Popen(["notify-send", title, message])

        logger.info(f"알림 전송: [{title}] {message}")

    except Exception as e:
        logger.warning(f"알림 전송 실패: {e}")
        # 알림이 실패해도 계속 진행


def play_alert_sound():
    """
    경고음을 재생합니다 (결제 시점 알림용).
    """
    system = platform.system()

    try:
        if system == "Windows":
            import winsound
            # 3회 비프음
            for _ in range(3):
                winsound.Beep(1000, 500)  # 1000Hz, 0.5초
                time.sleep(0.2)
        elif system == "Darwin":
            for _ in range(3):
                subprocess.Popen(["afplay", "/System/Library/Sounds/Glass.aiff"])
                time.sleep(0.7)
        else:
            # 터미널 벨
            print("\a" * 3)

    except Exception as e:
        logger.warning(f"경고음 재생 실패: {e}")
        print("\a")  # 터미널 벨 폴백


def proceed_to_payment(driver) -> bool:
    """
    좌석 선택 후 결제 페이지로 진행합니다.

    Args:
        driver: WebDriver 인스턴스

    Returns:
        결제 페이지 진입 성공 여부
    """
    try:
        # default content로 돌아가기
        driver.switch_to.default_content()
        time.sleep(0.5)

        # 좌석 선택 완료 / 다음 단계 버튼 찾기
        wait = WebDriverWait(driver, 10)

        # 다양한 선택자로 "다음" 또는 "결제" 버튼 시도
        next_selectors = [
            "//a[contains(text(), '좌석선택완료')]",
            "//a[contains(text(), '다음단계')]",
            "//a[contains(text(), '결제')]",
            "//button[contains(text(), '다음')]",
            "//a[contains(@class, 'btn_next')]",
            "//div[@class='twoBtn']/a[contains(@class, 'btn')]",
        ]

        for selector in next_selectors:
            try:
                btn = driver.find_element(By.XPATH, selector)
                if btn.is_displayed():
                    btn.click()
                    logger.info(f"✅ 다음 단계 버튼 클릭: {selector}")
                    time.sleep(2)
                    return True
            except Exception:
                continue

        logger.warning("다음 단계 버튼을 찾지 못했습니다.")
        return False

    except Exception as e:
        logger.error(f"결제 진행 중 오류: {e}")
        return False


def handle_payment(driver):
    """
    결제 페이지 진입 후 사용자에게 알림을 보냅니다.
    최종 결제는 사용자가 직접 수행합니다.

    Args:
        driver: WebDriver 인스턴스
    """
    logger.info("=" * 60)
    logger.info("🎉 좌석 선택 완료! 결제 페이지에 도달했습니다!")
    logger.info("   브라우저에서 직접 결제를 완료해주세요.")
    logger.info("=" * 60)

    # 시스템 알림
    notify_user(
        "🎫 티켓 매크로 알림",
        "좌석 선택 완료! 브라우저에서 결제를 진행해주세요."
    )

    # 경고음
    play_alert_sound()

    # 콘솔 출력
    print("\n" + "=" * 60)
    print("🎉🎉🎉  좌석 선택 완료!  🎉🎉🎉")
    print()
    print("  브라우저에서 직접 결제를 완료해주세요!")
    print("  브라우저 창을 확인하세요.")
    print()
    print("=" * 60)

    # 결제 페이지에서 대기 (브라우저가 닫히지 않도록)
    try:
        print("\n[!] 매크로를 완전히 종료하시려면 터미널 창에서 Ctrl + C 를 눌러주세요.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
