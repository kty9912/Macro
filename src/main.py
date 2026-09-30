"""
main.py - NOL(인터파크/야놀자) 티켓 매크로 메인 실행 스크립트

모드 구성:
  1. 정시 오픈 모드 (open): 티켓 오픈 시간(예: 11:00:00, 14:00:00)에 맞춰 새로고침 후 초고속 예매 진입
  2. 취소표 잠복 모드 (cancel): 이미 열린 경기에서 새로고침을 반복하며 취소표/잔여석 발생 시 즉시 선점

사용법:
  python src/main.py --mode open --date 10.07 --open-time 14:00:00
  python src/main.py --mode cancel --date 10.07
  python src/main.py --dry-run
"""

import os
import sys
import io
import json
import time
import logging
import argparse
from datetime import datetime, timedelta

# Windows 콘솔 인코딩 대응
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.browser import create_driver, navigate_to, close_driver
from src.auth import wait_for_manual_login, navigate_to_login
from src.ticket import (
    navigate_to_game, click_booking_button, switch_to_booking_popup,
    wait_for_queue, switch_to_seat_iframe, find_match_element, is_booking_button_enabled
)
from src.captcha import solve_captcha
from src.seat import (
    attempt_seat_selection, SEAT_SUCCESS, SEAT_PREEMPTED, SEAT_NO_SEATS, SEAT_ERROR
)
from src.payment import handle_payment, notify_user, play_alert_sound

DEFAULT_NOL_URL = "https://nol.yanolja.com"


def setup_logging(log_level: str = "INFO"):
    """로깅을 설정합니다."""
    log_dir = os.path.join(PROJECT_ROOT, "logs")
    os.makedirs(log_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"macro_{timestamp}.log")

    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    logger = logging.getLogger(__name__)
    logger.info(f"로그 파일: {log_file}")
    return logger


def load_settings(settings_path: str = None) -> dict:
    """설정 파일을 로드합니다."""
    if settings_path is None:
        settings_path = os.path.join(PROJECT_ROOT, "config", "settings.json")

    if not os.path.exists(settings_path):
        raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {settings_path}")

    with open(settings_path, "r", encoding="utf-8") as f:
        return json.load(f)


def apply_team_override(settings: dict, team_name: str):
    """CLI에서 지정한 팀으로 설정을 오버라이드합니다."""
    available_teams = settings.get("available_teams", {})

    if team_name not in available_teams:
        available = ", ".join(available_teams.keys())
        raise ValueError(
            f"팀 '{team_name}'을 찾을 수 없습니다.\n"
            f"사용 가능한 팀: {available}"
        )

    team_config = available_teams[team_name]
    settings["team"] = {
        "name": team_name,
        "slug": team_config.get("slug", ""),
        "sports_code": team_config.get("sports_code", ""),
        "team_code": team_config.get("team_code", ""),
    }


def parse_args():
    """CLI 인자를 파싱합니다."""
    parser = argparse.ArgumentParser(
        description="NOL(야놀자/인터파크) 티켓 매크로 v2.1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  [모드 1: 정시 오픈 예매]
  python src/main.py --mode open --date 10.07 --open-time 14:00:00
  python src/main.py --mode open --date 10.07 (오픈 시간 없이 바로 진입)

  [모드 2: 취소표/잔여석 잠복]
  python src/main.py --mode cancel --date 10.07
        """,
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="open",
        choices=["open", "cancel"],
        help="실행 모드: 'open' (정시 오픈 예매) 또는 'cancel' (취소표 잠복 탐색). 기본값: open",
    )
    parser.add_argument(
        "--open-time",
        type=str,
        default="",
        help="오픈 목표 시각 (HH:MM:SS 형식, 예: 14:00:00). 지정 시 정시까지 카운트다운 후 진입합니다.",
    )
    parser.add_argument(
        "--date",
        type=str,
        default="",
        help="예매할 경기 날짜 (예: 10.07, 10/7, 10월 7일)",
    )
    parser.add_argument(
        "--team",
        type=str,
        help="팀 이름 (예: 키움, 두산, 수원삼성, LCK 등)",
    )
    parser.add_argument(
        "--game",
        type=int,
        help="예매할 경기 순번 (1부터 시작, --date 미지정 시 사용)",
    )
    parser.add_argument(
        "--skip-login",
        action="store_true",
        help="로그인 대기 단계를 건너뜁니다.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="브라우저 없이 설정만 검증합니다.",
    )
    parser.add_argument(
        "--no-captcha-manual",
        action="store_true",
        help="캡차 수동 입력 폴백을 비활성화합니다.",
    )
    parser.add_argument(
        "--login-timeout",
        type=int,
        default=300,
        help="로그인 대기 시간 (초, 기본: 300)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="로그 레벨 (기본: INFO)",
    )
    return parser.parse_args()


def wait_until_target_time(target_time_str: str, logger):
    """
    지정한 목표 시각(HH:MM:SS)까지 카운트다운 대기합니다.
    """
    now = datetime.now()
    try:
        target_t = datetime.strptime(target_time_str, "%H:%M:%S").time()
    except ValueError:
        try:
            target_t = datetime.strptime(target_time_str, "%H:%M").time()
        except ValueError:
            logger.error(f"시간 형식 오류: {target_time_str}. HH:MM:SS 형식이어야 합니다.")
            return

    target_dt = datetime.combine(now.date(), target_t)
    # 이미 지난 시각이면 건너뜀
    if target_dt < now:
        logger.info(f"지정한 오픈 시각({target_time_str})이 이미 지났으므로 즉시 진행합니다.")
        return

    logger.info(f"⏳ [오픈 대기] 목표 시각: {target_time_str} 까지 대기합니다.")
    print(f"\n⏳ 목표 시각: {target_time_str} (현재 시각: {now.strftime('%H:%M:%S')})")

    while True:
        curr = datetime.now()
        diff = (target_dt - curr).total_seconds()

        if diff <= 0.8:
            logger.info("⚡ [정시 도달] 오픈 타이밍 진입!")
            break
        elif diff <= 5:
            print(f"🔥 오픈 임박! 남은 시간: {diff:.1f}초...", end="\r")
            time.sleep(0.1)
        elif diff <= 60:
            print(f"⏳ 오픈 대기 중... 남은 시간: {int(diff)}초   ", end="\r")
            time.sleep(0.5)
        else:
            print(f"⏳ 오픈 대기 중... 남은 시간: {int(diff)}초 ({int(diff//60)}분 전)   ", end="\r")
            time.sleep(1.0)

    print("\n🚀 [정시 오픈] 예매 버튼 감지 및 진입 시작!")


def run_open_sniper(driver, settings: dict, open_time: str, logger, manual_fallback: bool) -> bool:
    """
    [모드 1] 정시 오픈 스나이퍼 모드:
    오픈 시간에 맞춰 새로고침 ➔ 활성화 감지 즉시 클릭 ➔ 캡차 ➔ 좌석 선점
    """
    game_date = settings.get("game_date", "")
    game_index = settings.get("game_index", 1)

    # 1. 경기 페이지로 이동하여 사전 대기
    logger.info("🏟️ 경기 페이지 사전 접속 완료")
    navigate_to_game(driver, settings)

    # 2. 목표 오픈 시간이 지정된 경우 카운트다운
    if open_time:
        wait_until_target_time(open_time, logger)
        # 정시 직후 새로고침으로 최신 버튼 상태 로드
        logger.info("🔄 정시 도달 - 경기 페이지 새로고침")
        driver.refresh()
        time.sleep(0.5)

    # 3. 예매하기 버튼이 활성화될 때까지 고속 탐색 (최대 15초)
    logger.info("🎯 예매하기 버튼 활성화 대기 및 초고속 클릭 시도...")
    start_wait = time.time()
    clicked = False
    original_window_count = len(driver.window_handles)

    while time.time() - start_wait < 15:
        # 클릭 시도 (활성화 요구)
        if click_booking_button(driver, game_index=game_index, game_date=game_date, require_enabled=True):
            clicked = True
            break
        time.sleep(0.08)

    if not clicked:
        logger.warning("⚠️ 정시 활성화 감지 실패 - 강제 클릭 시도")
        clicked = click_booking_button(driver, game_index=game_index, game_date=game_date, require_enabled=False)

    if not clicked:
        logger.error("❌ 예매 버튼 클릭 실패")
        return False

    # 4. 팝업 창 전환
    if not switch_to_booking_popup(driver, original_window_count=original_window_count, timeout=20):
        logger.error("❌ 예매 팝업창 열기 실패")
        return False

    # 5. 대기열 통과 대기
    if not wait_for_queue(driver, timeout=300):
        logger.error("❌ 대기열 통과 실패")
        return False

    # 6. 좌석 iframe 전환
    switch_to_seat_iframe(driver)

    # 7. 캡차 통과
    logger.info("🔐 캡차 자동 처리 시작...")
    max_captcha = settings.get("max_captcha_attempts", 3)
    if not solve_captcha(driver, max_attempts=max_captcha, manual_fallback=manual_fallback):
        logger.error("❌ 캡차 통과 실패")
        return False

    # 8. 좌석 자동 선점 (1순위 좌석 즉시 클릭)
    logger.info("💺 좌석 자동 선택 시작...")
    result = attempt_seat_selection(driver, settings)
    if result == SEAT_SUCCESS:
        logger.info("🎉 [SUCCESS] 정시 오픈 좌석 선점 성공!")
        play_alert_sound()
        notify_user("티켓 매크로", "[성공] 좌석 선점 완료! 결제를 진행하세요.")
        handle_payment(driver)
        return True
    else:
        logger.warning(f"⚠️ 정시 좌석 선점 결과: {result}")
        print("\n[!] 정시 오픈 첫 시도에서 선점하지 못했습니다. 취소표 잠복 모드로 이어서 진행할 수 있습니다.")
        return False


def run_cancel_hunter(driver, settings: dict, logger, manual_fallback: bool) -> bool:
    """
    [모드 2] 취소표 / 잔여석 잠복 헌터 모드:
    좌석 화면에서 지속적으로 새로고침 루프를 돌며 자리가 나는 즉시 낚아챕니다.
    """
    max_rounds = settings.get("max_retry_rounds", 500)
    max_captcha = settings.get("max_captcha_attempts", 3)
    round_num = 0

    print()
    print("=" * 60)
    print("  🎣 [취소표 잠복 모드 시작]")
    print("  - 좌석이 풀리는 순간 즉시 클릭하여 선점합니다.")
    print("  - 선점 충돌(이선좌) 시 자동으로 다음 시도로 넘어갑니다.")
    print("=" * 60)
    print()

    while True:
        round_num += 1
        if round_num > max_rounds:
            print(f"\n[!] 지정한 {max_rounds}회 시도를 완료했습니다.")
            try:
                choice = input(f"추가로 {max_rounds}회 더 잠복하시겠습니까? (Y/N): ").strip().upper()
            except (EOFError, KeyboardInterrupt):
                choice = 'N'
            if choice == 'Y':
                max_rounds += 500
                continue
            else:
                break

        logger.info(f"🔄 [잠복 Round {round_num}/{max_rounds}] 잔여석 탐색 중...")

        # 1. 캡차가 떠 있으면 처리
        solve_captcha(driver, max_attempts=max_captcha, manual_fallback=manual_fallback)

        # 2. 좌석 선택 시도
        result = attempt_seat_selection(driver, settings)

        if result == SEAT_SUCCESS:
            logger.info(f"🎉 [SUCCESS] Round {round_num}에서 취소표 선점 성공!")
            play_alert_sound()
            notify_user("티켓 매크로", "[성공] 취소표 확보 완료! 결제를 진행하세요.")
            handle_payment(driver)
            return True

        elif result == SEAT_PREEMPTED:
            logger.info("⚡ [이선좌] 이미 선택된 좌석입니다. 즉시 다음 좌석/새로고침 시도...")
            time.sleep(0.1)

        elif result == SEAT_NO_SEATS:
            # 잔여석 없음 -> 잠시 대기 후 새로고침
            time.sleep(settings.get("timing", {}).get("seat_select_wait", 0.3))

        else:
            time.sleep(0.5)

    return False


def main():
    """메인 실행 진입점"""
    args = parse_args()
    logger = setup_logging(args.log_level)

    print()
    print("=" * 65)
    print("  🎫 NOL(야놀자/인터파크) 티켓 매크로 v2.1")
    print(f"  실행 모드: [{'정시 오픈 예매 (open)' if args.mode == 'open' else '취소표 잠복 탐색 (cancel)'}]")
    print("  [주의] 개인 연구/학습 목적으로만 사용하세요.")
    print("=" * 65)
    print()

    driver = None

    try:
        # 1. 설정 로드
        settings = load_settings()
        if args.team:
            apply_team_override(settings, args.team)
        if args.date:
            settings["game_date"] = args.date
        if args.game:
            settings["game_index"] = args.game
        if args.mode:
            settings["mode"] = args.mode

        team_name = settings.get("team", {}).get("name", "키움")
        game_date = settings.get("game_date", "")

        # Dry Run
        if args.dry_run:
            logger.info("[OK] Dry Run 완료 - 설정 검증 성공")
            print(f"[OK] 팀: {team_name}, 날짜: {game_date or '기본 1차전'}, 모드: {args.mode}")
            return

        # 2. 브라우저 시작
        logger.info("브라우저 생성 중...")
        driver = create_driver(settings)
        base_url = settings.get("base_url", DEFAULT_NOL_URL)
        navigate_to(driver, base_url, 1.5)

        # 3. 로그인 대기
        if not args.skip_login:
            navigate_to_login(driver, base_url)
            if not wait_for_manual_login(driver, timeout=args.login_timeout):
                logger.error("로그인 대기 시간 초과")
                return
        else:
            logger.info("로그인 단계를 건너뜁니다 (--skip-login).")

        # 4. 모드별 실행
        manual_fallback = not args.no_captcha_manual

        if args.mode == "open":
            open_time = args.open_time or settings.get("open_time", "")
            success = run_open_sniper(driver, settings, open_time=open_time, logger=logger, manual_fallback=manual_fallback)
            if not success:
                print("\n[안내] 취소표 잠복 모드로 전환하시겠습니까? (Y/N): ", end="")
                try:
                    c = input().strip().upper()
                except Exception:
                    c = 'N'
                if c == 'Y':
                    run_cancel_hunter(driver, settings, logger=logger, manual_fallback=manual_fallback)

        elif args.mode == "cancel":
            # 경기 페이지 진입 후 팝업 띄우기
            logger.info(f"{team_name} 경기 페이지 진입 중...")
            if not enter_booking(driver, settings):
                logger.error("경기 예매창 진입 실패")
                return
            run_cancel_hunter(driver, settings, logger=logger, manual_fallback=manual_fallback)

    except KeyboardInterrupt:
        print("\n[!] 사용자에 의해 중단되었습니다.")
    except Exception as e:
        logger.error(f"실행 중 오류 발생: {e}", exc_info=True)
        print(f"\n[ERROR] {e}")
    finally:
        if driver:
            print("\n" + "=" * 60)
            print("[!] 프로그램이 대기 상태입니다. (브라우저 창은 유지됩니다)")
            print("[!] 창을 닫거나 콘솔에서 Ctrl + C를 누르면 완전히 종료됩니다.")
            print("=" * 60 + "\n")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()
