import os
import time
import glob
import re
import pandas as pd
import psycopg2
import boto3
from psycopg2.extras import execute_values
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from datetime import datetime

# ============ 설정 (환경변수에서) ============
DOWNLOAD_DIR = os.path.join(os.getcwd(), "hospital_downloads")

DB_HOST = "medipanda.cp6gkgc82mif.ap-northeast-2.rds.amazonaws.com"
DB_PORT = 5432
DB_NAME = os.environ.get("DB_NAME", "qa2")
DB_USER = "medipanda"
PARAM_STORE_KEY = os.environ.get("PARAM_STORE_KEY", "postgres-dev-password")

print(f"🔧 Environment: DB={DB_NAME}, ParamKey={PARAM_STORE_KEY}")


def get_db_password():
    profile = os.environ.get('AWS_PROFILE')
    if profile:
        session = boto3.Session(profile_name=profile)
        ssm = session.client('ssm', region_name='ap-northeast-2')
    else:
        ssm = boto3.client('ssm', region_name='ap-northeast-2')

    response = ssm.get_parameter(
        Name=PARAM_STORE_KEY,
        WithDecryption=True
    )
    return response['Parameter']['Value']


def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=get_db_password()
    )


# 시도 코드
SIDO_MAP = {
    "서울특별시": "6110000",
    "부산광역시": "6260000",
    "대구광역시": "6270000",
    "인천광역시": "6280000",
    "광주광역시": "6290000",
    "대전광역시": "6300000",
    "울산광역시": "6310000",
    "세종특별자치시": "5690000",
    "경기도": "6410000",
    "강원특별자치도": "6530000",
    "충청북도": "6430000",
    "충청남도": "6440000",
    "전북특별자치도": "6540000",
    "전라남도": "6460000",
    "경상북도": "6470000",
    "경상남도": "6480000",
    "제주특별자치도": "6500000",
}

CATEGORY_MAP = {
    "병원": "01_01_01_P",
    "의원": "01_01_02_P",
}


def normalize_sido(sido: str) -> str:
    """시도명 정규화"""
    if not sido:
        return ''
    sido = sido.strip()
    mapping = {
        # 특별자치도 → 기존 명칭
        '강원특별자치도': '강원도',
        '전북특별자치도': '전라북도',
        # 약칭 → 정식명칭
        '서울': '서울특별시',
        '부산': '부산광역시',
        '대구': '대구광역시',
        '인천': '인천광역시',
        '광주': '광주광역시',
        '대전': '대전광역시',
        '울산': '울산광역시',
        '세종': '세종특별자치시',
        '경기': '경기도',
        '강원': '강원도',
        '충북': '충청북도',
        '충남': '충청남도',
        '전북': '전라북도',
        '전남': '전라남도',
        '경북': '경상북도',
        '경남': '경상남도',
        '제주': '제주특별자치도',
        # 오타/구명칭
        '대구시': '대구광역시',
    }
    return mapping.get(sido, sido)


def normalize_sigungu(sido: str, sigungu: str) -> str:
    """시군구 정규화 (복합 시군구 분리)"""
    if not sigungu:
        return ''
    sigungu = sigungu.strip()

    # 복합 시군구 분리 (성남시분당구 → 성남시)
    compound_map = {
        '성남시분당구': '성남시',
        '성남시수정구': '성남시',
        '성남시중원구': '성남시',
        '고양시일산서구': '고양시',
        '고양시일산동구': '고양시',
        '고양시덕양구': '고양시',
        '수원시권선구': '수원시',
        '수원시팔달구': '수원시',
        '수원시영통구': '수원시',
        '수원시장안구': '수원시',
        '안산시상록구': '안산시',
        '안산시단원구': '안산시',
        '안양시만안구': '안양시',
        '안양시동안구': '안양시',
        '용인시수지구': '용인시',
        '용인시기흥구': '용인시',
        '용인시처인구': '용인시',
        '천안시서북구': '천안시',
        '천안시동남구': '천안시',
        '청주시상당구': '청주시',
        '청주시서원구': '청주시',
        '청주시흥덕구': '청주시',
        '청주시청원구': '청주시',
        '전주시완산구': '전주시',
        '전주시덕진구': '전주시',
        '포항시북구': '포항시',
        '포항시남구': '포항시',
        '창원시의창구': '창원시',
        '창원시성산구': '창원시',
        '창원시마산합포구': '창원시',
        '창원시마산회원구': '창원시',
        '창원시진해구': '창원시',
        # 당진군 → 당진시
        '당진군': '당진시',
    }

    if sigungu in compound_map:
        return compound_map[sigungu]

    # 울주군언양읍 → 울주군
    if sigungu.startswith('울주군'):
        return '울주군'

    # 대구 동구xxx → 동구
    if sido == '대구광역시' and sigungu.startswith('동구'):
        return '동구'

    # 예천군xxx → 예천군
    if sigungu.startswith('예천군'):
        return '예천군'

    # 나주시xxx → 나주시
    if sigungu.startswith('나주시'):
        return '나주시'

    return sigungu


def extract_dong_from_road_address(road_address: str) -> str:
    """도로명주소 괄호 안에서 동/읍/면 추출"""
    if not road_address:
        return ''
    # (아름동, xxx) 또는 (아름동) 패턴에서 동 추출
    match = re.search(r'\(([^,\)]+(?:동|읍|면))[,\)]', road_address)
    if match:
        return match.group(1).strip()
    return ''


def parse_address(row):
    """주소 파싱 - 도로명주소 우선, 세종시 특별 처리"""
    road_address = str(row.get('도로명전체주소', '') or '').strip()
    address = str(row.get('소재지전체주소', '') or '').strip()

    # nan 처리
    if road_address == 'nan':
        road_address = ''
    if address == 'nan':
        address = ''

    # 도로명주소 우선
    target_address = road_address if road_address else address

    if not target_address:
        return '', ''

    parts = target_address.split()
    if len(parts) < 2:
        return '', ''

    sido_raw = parts[0]
    sido = normalize_sido(sido_raw)

    # === 특수 케이스 처리 ===

    # 1. 세종시: 시군구 없이 바로 도로명
    if sido == '세종특별자치시':
        # 방법 1: 도로명주소 2번째가 읍/면/동이면 바로 사용
        if len(parts) >= 2:
            second = parts[1]
            if second.endswith(('동', '읍', '면')):
                return sido, second

        # 방법 2: 도로명주소 괄호에서 동 추출
        dong = extract_dong_from_road_address(road_address)
        if dong:
            return sido, dong

        # 방법 3: 소재지주소에서 추출
        if address:
            addr_parts = address.split()
            if len(addr_parts) >= 2:
                second = addr_parts[1]
                if second.endswith(('동', '읍', '면')):
                    return sido, second

        return sido, ''

    # 2. 시도 위치에 시군구가 온 경우 (논현동, 군위군 등)
    if sido_raw.endswith(('동', '읍', '면', '리')):
        return '', ''

    if sido_raw == '군위군':
        return '경상북도', '군위군'

    if sido_raw in ['포항시', '창원시', '거제시', '진주시', '구미시', '안동시', '영주시', '제천시']:
        sido_map = {
            '포항시': '경상북도',
            '창원시': '경상남도',
            '거제시': '경상남도',
            '진주시': '경상남도',
            '구미시': '경상북도',
            '안동시': '경상북도',
            '영주시': '경상북도',
            '제천시': '충청북도',
        }
        return sido_map.get(sido_raw, ''), sido_raw

    if sido_raw in ['성남시', '수원시', '안산시', '안양시', '용인시', '고양시']:
        return '경기도', sido_raw

    # 3. 일반 케이스
    sigungu = parts[1]

    # 시군구가 도로명인 경우 → 소재지주소에서 재파싱
    if not sigungu.endswith(('시', '군', '구')):
        if address:
            addr_parts = address.split()
            if len(addr_parts) >= 2:
                addr_sigungu = addr_parts[1]
                if addr_sigungu.endswith(('시', '군', '구')):
                    sigungu = addr_sigungu

    # 시군구 정규화
    sigungu = normalize_sigungu(sido, sigungu)

    # 4. 특수 케이스 추가 매핑
    if sido == '전라남도' and sigungu == '벌교상고길':
        sigungu = '보성군'

    if sido == '울산광역시' and sigungu == '새즈믄해거리':
        sigungu = '울주군'

    if sido == '대구광역시' and sigungu == '군위군':
        sido = '경상북도'

    return sido, sigungu


def setup_driver():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    prefs = {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
    }
    options.add_experimental_option("prefs", prefs)

    return webdriver.Chrome(options=options)


def wait_for_download(before_files, timeout=180):
    """다운로드 완료 대기 (최대 3분)"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        current_files = set(glob.glob(os.path.join(DOWNLOAD_DIR, "*.xlsx")))
        new_files = current_files - before_files
        crdownload = glob.glob(os.path.join(DOWNLOAD_DIR, "*.crdownload"))

        if new_files and not crdownload:
            time.sleep(2)
            return list(new_files)[0]
        time.sleep(1)
    return None


def scrape_category(driver, category_name: str, opn_svc_id: str):
    """특정 업종의 모든 시도 데이터 다운로드"""
    downloaded_files = []

    for sido_name, sido_code in SIDO_MAP.items():
        try:
            print(f"\n🔄 수집 중: {category_name} - {sido_name}")

            url = f"https://www.localdata.go.kr/data/dataView.do?opnSvcId={opn_svc_id}"
            driver.get(url)
            time.sleep(3)

            wait = WebDriverWait(driver, 20)

            # 시도 선택
            sido_select = Select(wait.until(
                EC.presence_of_element_located((By.ID, "sidoCodeLabel"))
            ))
            sido_select.select_by_value(sido_code)
            time.sleep(2)

            # 상태: 영업/정상
            status_select = Select(wait.until(
                EC.presence_of_element_located((By.ID, "srhStatus"))
            ))
            status_select.select_by_value("01")
            time.sleep(1)

            # 검색
            search_btn = wait.until(
                EC.element_to_be_clickable((By.ID, "searchBtn"))
            )
            search_btn.click()
            time.sleep(5)

            # 총 건수 (콤마 제거)
            total_count_elem = driver.find_element(By.ID, "totalCount")
            total_count = int((total_count_elem.get_attribute("value") or "0").replace(",", ""))
            print(f"   총 {total_count:,}건")

            if total_count == 0:
                print(f"   ⏭️ 스킵")
                continue

            if total_count >= 100000:
                print(f"   ⚠️ 10만건 이상, 별도 처리 필요")
                continue

            before_files = set(glob.glob(os.path.join(DOWNLOAD_DIR, "*.xlsx")))

            # 엑셀 다운로드
            excel_btn = wait.until(
                EC.element_to_be_clickable((By.ID, "downBtn_xlsx"))
            )
            excel_btn.click()

            downloaded_file = wait_for_download(before_files)
            if downloaded_file:
                new_filename = os.path.join(
                    DOWNLOAD_DIR,
                    f"{category_name}_{sido_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
                )
                os.rename(downloaded_file, new_filename)
                downloaded_files.append(new_filename)
                print(f"   ✅ 완료")
            else:
                print(f"   ❌ 실패 (타임아웃)")

            time.sleep(2)

        except Exception as e:
            print(f"   ❌ 에러: {e}")
            continue

    return downloaded_files


def parse_excel_files():
    """다운로드된 엑셀 파일 파싱"""
    all_data = []
    files = glob.glob(os.path.join(DOWNLOAD_DIR, "*.xlsx"))

    for file_path in files:
        try:
            df = pd.read_excel(file_path, dtype=str)
            print(f"📄 {os.path.basename(file_path)} ({len(df)}건)")

            for _, row in df.iterrows():
                # 주소 파싱 (도로명주소 우선, 예외처리 포함)
                sido, sigungu = parse_address(row)

                def parse_date(val):
                    if not val or str(val) == 'nan':
                        return None
                    try:
                        return datetime.strptime(str(val)[:10], '%Y-%m-%d').date()
                    except:
                        return None

                def parse_datetime(val):
                    if not val or str(val) == 'nan':
                        return None
                    try:
                        return datetime.strptime(str(val)[:19], '%Y-%m-%d %H:%M:%S')
                    except:
                        return None

                def parse_int(val):
                    try:
                        return int(float(str(val))) if val and str(val) != 'nan' else None
                    except:
                        return None

                def clean_str(val):
                    s = str(val or '').strip()
                    return s if s and s != 'nan' else None

                record = {
                    'management_number': clean_str(row.get('관리번호')),
                    'name': clean_str(row.get('사업장명')),
                    'business_status': clean_str(row.get('영업상태명')),
                    'detail_status': clean_str(row.get('상세영업상태명')),
                    'license_date': parse_date(row.get('인허가일자')),
                    'close_date': parse_date(row.get('폐업일자')),
                    'phone': clean_str(row.get('소재지전화')),
                    'address': clean_str(row.get('소재지전체주소')),
                    'road_address': clean_str(row.get('도로명전체주소')),
                    'zipcode': clean_str(row.get('도로명우편번호')),
                    'sido': sido,
                    'sigungu': sigungu,
                    'hospital_type': clean_str(row.get('의료기관종별명')),
                    'doctor_count': parse_int(row.get('의료인수')),
                    'room_count': parse_int(row.get('입원실수')),
                    'bed_count': parse_int(row.get('병상수')),
                    'department_codes': clean_str(row.get('진료과목내용')),
                    'department_names': clean_str(row.get('진료과목내용명')),
                    'coord_x': clean_str(row.get('좌표정보X(EPSG5174)')),
                    'coord_y': clean_str(row.get('좌표정보Y(EPSG5174)')),
                    'last_modified': parse_datetime(row.get('최종수정시점')),
                }

                if record['management_number'] and record['name']:
                    all_data.append(record)

        except Exception as e:
            print(f"❌ 파싱 에러: {file_path}: {e}")

    # 중복 제거 (관리번호 기준)
    unique_data = {d['management_number']: d for d in all_data}
    print(f"\n📊 총 {len(unique_data):,}건 (중복 제거 후)")

    return list(unique_data.values())


def insert_to_db(data: list):
    """DB에 데이터 삽입"""
    if not data:
        print("삽입할 데이터 없음")
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # TRUNCATE (ID 리셋)
        cursor.execute("TRUNCATE TABLE hospital RESTART IDENTITY")
        print("✅ TRUNCATE 완료")

        # 데이터 삽입
        columns = [
            'management_number', 'name', 'business_status', 'detail_status',
            'license_date', 'close_date', 'phone', 'address', 'road_address',
            'zipcode', 'sido', 'sigungu', 'hospital_type', 'doctor_count',
            'room_count', 'bed_count', 'department_codes', 'department_names',
            'coord_x', 'coord_y', 'last_modified'
        ]

        values = [tuple(d.get(col) for col in columns) for d in data]

        insert_sql = f"INSERT INTO hospital ({', '.join(columns)}) VALUES %s"
        execute_values(cursor, insert_sql, values, page_size=1000)
        print(f"✅ {len(data):,}건 삽입 완료")

        # region_category_id 매핑
        cursor.execute("""
            UPDATE hospital ht
            SET region_category_id = rc.id
            FROM region_category rc
            WHERE rc.depth = 2
              AND rc.deleted = false
              AND rc.name = ht.sigungu
              AND EXISTS (
                  SELECT 1 FROM region_category parent
                  WHERE parent.id = rc.parent_id
                    AND parent.name = ht.sido
              )
        """)
        mapped_count = cursor.rowcount
        print(f"✅ region_category_id 매핑 완료 ({mapped_count:,}건)")

        # 매핑 결과 통계
        cursor.execute("""
            SELECT COUNT(*) as total,
                   COUNT(region_category_id) as mapped,
                   COUNT(*) - COUNT(region_category_id) as unmapped
            FROM hospital
        """)
        stats = cursor.fetchone()
        mapping_rate = round(stats[1] / stats[0] * 100, 2) if stats[0] > 0 else 0
        print(f"📊 매핑 통계: 전체 {stats[0]:,} / 매핑 {stats[1]:,} / 미매핑 {stats[2]:,} ({mapping_rate}%)")

        # 미매핑 데이터 경고
        if stats[2] > 0:
            cursor.execute("""
                SELECT sido, sigungu, COUNT(*)
                FROM hospital
                WHERE region_category_id IS NULL
                  AND sido IS NOT NULL AND sido != ''
                GROUP BY sido, sigungu
                ORDER BY COUNT(*) DESC
                LIMIT 10
            """)
            unmapped = cursor.fetchall()
            if unmapped:
                print(f"⚠️ 미매핑 상위 10개:")
                for row in unmapped:
                    print(f"   {row[0]} / {row[1]}: {row[2]}건")

        conn.commit()

    except Exception as e:
        conn.rollback()
        print(f"❌ DB 에러: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


def main():
    print("=" * 60)
    print(f"🏥 병원/의원 스크래핑 (DB: {DB_NAME})")
    print("=" * 60)

    # 기존 다운로드 파일 정리
    if os.path.exists(DOWNLOAD_DIR):
        for f in glob.glob(os.path.join(DOWNLOAD_DIR, "*.xlsx")):
            os.remove(f)
        print(f"📁 다운로드 폴더 정리: {DOWNLOAD_DIR}")

    # 스크래핑
    driver = setup_driver()
    all_downloaded = []

    try:
        for category_name, opn_svc_id in CATEGORY_MAP.items():
            print(f"\n{'=' * 60}")
            print(f"📋 {category_name} 수집 시작")
            print("=" * 60)
            files = scrape_category(driver, category_name, opn_svc_id)
            all_downloaded.extend(files)
    finally:
        driver.quit()

    print(f"\n📥 다운로드 완료: {len(all_downloaded)}개 파일")

    # 엑셀 파싱
    print("\n" + "=" * 60)
    print("📄 엑셀 파싱 중...")
    print("=" * 60)
    all_data = parse_excel_files()

    # DB 삽입
    print("\n" + "=" * 60)
    print("💾 DB 삽입 중...")
    print("=" * 60)
    insert_to_db(all_data)

    print("\n" + "=" * 60)
    print("✅ 완료!")
    print("=" * 60)


if __name__ == "__main__":
    main()