"""
main.py - 인터파크(NOL) 티켓 매크로 메인 실행 스크립트

전체 흐름:
  1. 설정 로드
  2. 브라우저 시작 + 인터파크 접속
  3. 사용자 수동 로그인 대기
  4. 경기 페이지 이동 + 예매 진입
  5. 캡차 처리
  6. 좌석 선택
  7. 결제 알림

사용법:
  python src/main.py
  python src/main.py --dry-run    (브라우저 없이 설정만 검증)
  python src/main.py --team 두산   (팀 변경)
"""

import os
import sys
import io
import json
import time
import logging
import argparse
from datetime import datetime

# Windows cp949 인코딩 문제 방지: stdout/stderr를 UTF-8로 강제 설정
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 프로젝트 루트를 Python 경로에 추가
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.browser import create_driver, navigate_to, close_driver
from src.auth import wait_for_manual_login, navigate_to_login
from src.ticket import enter_booking, switch_to_seat_iframe, wait_for_queue
from src.captcha import solve_captcha
from src.seat import (
    attempt_seat_selection, SEAT_SUCCESS, SEAT_PREEMPTED, SEAT_NO_SEATS, SEAT_ERROR
)
from src.payment import proceed_to_payment, handle_payment, notify_user, play_alert_sound

# NOL 인터파크 메인 URL
INTERPARK_URL = "https://tickets.interpark.com/"


def setup_logging(log_level: str = "INFO"):
    """로깅을 설정합니다."""
    # 로그 디렉토리 생성
    log_dir = os.path.join(PROJECT_ROOT, "logs")
    os.makedirs(log_dir, exist_ok=True)

    # 로그 파일명 (타임스탬프 포함)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"macro_{timestamp}.log")

    # 로깅 포맷
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # 루트 로거 설정
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
        raise FileNotFoundError(
            f"설정 파일을 찾을 수 없습니다: {settings_path}\n"
            f"config/settings.json 파일을 확인해주세요."
        )

    with open(settings_path, "r", encoding="utf-8") as f:
        settings = json.load(f)

    return settings


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
        "sports_code": team_config["sports_code"],
        "team_code": team_config["team_code"],
    }


def parse_args():
    """CLI 인자를 파싱합니다."""
    parser = argparse.ArgumentParser(
        description="인터파크(NOL) 티켓 매크로",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python src/main.py                      기본 설정으로 실행
  python src/main.py --team 두산          두산 경기 예매
  python src/main.py --date 06.15         6월 15일 경기 예매
  python src/main.py --date 2026-06-15    날짜 지정 (다양한 형식 지원)
  python src/main.py --game 2             두 번째 경기 예매
  python src/main.py --dry-run            설정만 검증 (브라우저 미실행)
        """,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="브라우저 없이 설정만 검증합니다.",
    )
    parser.add_argument(
        "--team",
        type=str,
        help="팀 이름 (예: 키움, 두산, 서울이랜드)",
    )
    parser.add_argument(
        "--date",
        type=str,
        help="예매할 경기 날짜 (예: 06.15, 2026-06-15, 6/15)",
    )
    parser.add_argument(
        "--game",
        type=int,
        help="예매할 경기 순번 (1부터 시작, --date와 함께 사용 불가)",
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


def main():
    """메인 실행 함수"""
    args = parse_args()
    logger = setup_logging(args.log_level)

    print()
    print("=" * 60)
    print("  [TICKET] 인터파크(NOL) 티켓 매크로 v2.0")
    print("  [주의] 학습/연습 목적으로만 사용하세요.")
    print("=" * 60)
    print()

    driver = None

    try:
        # ========== 1. 설정 로드 ==========
        logger.info("[1/7] 설정 파일 로드 중...")
        settings = load_settings()

        # CLI 오버라이드 적용
        if args.team:
            apply_team_override(settings, args.team)
        if args.date:
            settings["game_date"] = args.date
        if args.game:
            settings["game_index"] = args.game

        team_name = settings.get("team", {}).get("name", "알 수 없음")
        game_index = settings.get("game_index", 1)
        game_date = settings.get("game_date", "")
        if game_date:
            logger.info(f"팀: {team_name}, 경기 날짜: {game_date}")
        else:
            logger.info(f"팀: {team_name}, 경기 순번: {game_index}")

        # ========== Dry Run 모드 ==========
        if args.dry_run:
            logger.info("[OK] Dry Run 완료 - 모든 설정이 정상입니다.")
            logger.info(f"  팀: {team_name}")
            if game_date:
                logger.info(f"  경기 날짜: {game_date}")
            else:
                logger.info(f"  경기 순번: {game_index}")
            logger.info(f"  좌석 범위: {settings.get('seat_preference', {})}")
            print("[OK] 설정 검증 완료!")
            return

        # ========== 2. 브라우저 시작 ==========
        logger.info("[2/7] 브라우저 시작 중...")
        driver = create_driver(settings)
        navigate_to(driver, INTERPARK_URL, settings.get("timing", {}).get("page_load_wait", 2))
        logger.info("인터파크 메인 페이지 로드 완료")

        # ========== 3. 사용자 수동 로그인 ==========
        logger.info("[3/7] 로그인 대기 중...")
        navigate_to_login(driver)

        if not wait_for_manual_login(driver, timeout=args.login_timeout):
            logger.error("로그인 시간 초과. 프로그램을 종료합니다.")
            notify_user("티켓 매크로", "[FAIL] 로그인 시간 초과!")
            return

        # ========== 4. 경기 선택 + 예매 진입 ==========
        logger.info(f"[4/7] {team_name} 경기 페이지로 이동 중...")
        if not enter_booking(driver, settings):
            logger.error("예매 진입에 실패했습니다.")
            notify_user("티켓 매크로", "[FAIL] 예매 페이지 진입 실패!")
            return

        # ========== 5~6. 캡차 + 좌석 선택 (취소표 잡기 루프) ==========
        manual_fallback = not args.no_captcha_manual
        max_captcha = settings.get("max_captcha_attempts", 5)
        max_rounds = settings.get("max_retry_rounds", 50)
        total_rounds_done = 0
        result = None

        while True:
            total_rounds_done += 1
            round_num = total_rounds_done
            
            if round_num > max_rounds:
                logger.error(f"[FAIL] {max_rounds}회 시도 후 좌석 확보 실패")
                notify_user("티켓 매크로", f"[FAIL] {max_rounds}회 시도 후 실패!")
                play_alert_sound()
                print(f"\n[FAIL] {max_rounds}회 시도 후 좌석을 확보하지 못했습니다.")
                
                try:
                    choice = input(f"\n[?] 추가로 {settings.get('max_retry_rounds', 50)}회 더 시도하시겠습니까? (Y/N): ").strip().upper()
                except (EOFError, KeyboardInterrupt):
                    choice = 'N'
                    
                if choice == 'Y':
                    added = settings.get("max_retry_rounds", 50)
                    max_rounds += added
                    print(f"\n-> {added}회 추가 탐색을 이어서 시작합니다...\n")
                    continue
                else:
                    print("\n[!] 탐색을 종료합니다. 매크로는 대기 상태로 전환됩니다.")
                    break

            logger.info(f"")
            logger.info(f"{'='*50}")
            logger.info(f"  [ROUND {round_num}/{max_rounds}] 캡차 + 좌석 선택 시도")
            logger.info(f"{'='*50}")

            # 5. 캡차 처리
            logger.info(f"[5/7] 캡차 처리 중... (Round {round_num})")
            if not solve_captcha(driver, max_attempts=max_captcha, manual_fallback=manual_fallback):
                logger.error("캡차를 통과하지 못했습니다.")
                notify_user("티켓 매크로", "[FAIL] 캡차 통과 실패!")
                return

            # 6. 좌석 선택
            logger.info(f"[6/7] 좌석 선택 중... (Round {round_num})")
            result = attempt_seat_selection(driver, settings)

            if result == SEAT_SUCCESS:
                # 성공! 결제로 진행
                logger.info(f"[OK] Round {round_num}에서 좌석 확보 성공!")
                break

            elif result == SEAT_PREEMPTED:
                # "이미 선점된 좌석" → 새로고침하고 캡차부터 다시
                logger.warning(f"[!] Round {round_num}: 선점된 좌석! 새로고침 후 재시도...")
                try:
                    driver.refresh()
                    time.sleep(1)
                    # 대기열 + iframe 재진입
                    if not wait_for_queue(driver, timeout=60):
                        logger.error("새로고침 후 대기열 통과 실패")
                        continue
                    if not switch_to_seat_iframe(driver):
                        logger.error("새로고침 후 iframe 진입 실패")
                        continue
                except Exception as refresh_err:
                    logger.error(f"새로고침 중 오류: {refresh_err}")
                continue  # 캕차부터 다시

            elif result == SEAT_NO_SEATS:
                # 빈 좌석 없음 → 새로고침 후 재시도
                logger.warning(f"[!] Round {round_num}: 빈 좌석 없음! 새로고침 후 재시도...")
                try:
                    driver.refresh()
                    time.sleep(1)
                    if not wait_for_queue(driver, timeout=60):
                        continue
                    if not switch_to_seat_iframe(driver):
                        continue
                except Exception:
                    pass
                continue

            else:
                # 기타 오류
                logger.error(f"[!] Round {round_num}: 좌석 선택 오류 ({result})")
                try:
                    driver.refresh()
                    time.sleep(1)
                    if not wait_for_queue(driver, timeout=60):
                        continue
                    if not switch_to_seat_iframe(driver):
                        continue
                except Exception:
                    pass
                continue

        # while 루프 종료 후 성공 여부 체크
        if result == SEAT_SUCCESS:
            # ========== 7. 결제 ==========
            logger.info("[7/7] 결제 페이지 도달!")
            handle_payment(driver)
            logger.info("[DONE] 매크로 실행 완료!")
        else:
            logger.info("[DONE] 좌석 확보 없이 매크로 루프가 종료되었습니다.")

    except FileNotFoundError as e:
        logger.error(f"파일 오류: {e}")
        print(f"\n[ERROR] {e}")

    except ValueError as e:
        logger.error(f"설정 오류: {e}")
        print(f"\n[ERROR] {e}")

    except KeyboardInterrupt:
        logger.info("사용자에 의해 중단되었습니다.")
        print("\n\n[!] 사용자에 의해 중단되었습니다.")

    except Exception as e:
        logger.error(f"예상치 못한 오류: {e}", exc_info=True)
        print(f"\n[ERROR] 예상치 못한 오류가 발생했습니다: {e}")
        notify_user("티켓 매크로", f"[FAIL] 오류 발생: {str(e)[:50]}")

    finally:
        if driver:
            # 브라우저는 닫지 않음 (detach 옵션으로 유지)
            logger.info("프로그램 종료 대기 상태.")
            print("\n" + "=" * 60)
            print("[!] 프로그램 실행이 종료되었습니다. (브라우저 열림 상태 유지)")
            print("[!] 이 창에서 Ctrl + C 를 한 번 더 누르거나 창을 닫으면 완전히 종료됩니다.")
            print("=" * 60 + "\n")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()
