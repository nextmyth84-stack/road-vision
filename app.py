# app.py
import streamlit as st
from google.cloud import vision
from google.oauth2 import service_account
import re
import json
import os # 추가
from io import BytesIO # 추가

st.set_page_config(page_title="근무표 자동 배정 (한글 OCR 버전)", layout="wide")

st.title("🚦 근무표 자동 배정 (Google Vision OCR + 한글 텍스트 출력)")

########################################################################
# 1) Google Vision API 인증 설정
########################################################################
try:
    # st.secrets에서 JSON 문자열을 로드
    cred_data = json.loads(st.secrets["general"]["GOOGLE_APPLICATION_CREDENTIALS"])
    creds = service_account.Credentials.from_service_account_info(cred_data)
    client = vision.ImageAnnotatorClient(credentials=creds)
except Exception as e:
    st.error(f"⚠️ Google Vision API 인증 실패: {e}")
    st.error("Streamlit Secrets의 'GOOGLE_APPLICATION_CREDENTIALS' 키에 서비스 계정 JSON 파일의 '내용 전체'를 복사해 붙여넣었는지 확인하세요.")
    st.stop()

########################################################################
# 2) 순번표 및 차량 매핑 설정 (사이드바)
########################################################################

st.sidebar.header("초기 데이터 입력 (필요 시 수정)")

# 기본값 정의 (기존과 동일)
default_key_order = """권한솔
김남균
김면정
김성연
김지은
안유미
윤여헌
윤원실
이나래
이호석
조윤영
조정래"""
default_gyoyang_order = """권한솔
김남균
김면정
김병욱
김성연
김주현
김지은
안유미
이호석
조정래"""
default_sudong_order = """권한솔
김남균
김면정
김성연
김주현
김지은
안유미
이호석
조정래"""
default_cha1 = """2호 조정래
5호 권한솔
7호 김남균
8호 이호석
9호 김주현
10호 김성연"""
default_cha2 = """4호 김남균
5호 김병욱
6호 김지은
12호 안유미
14호 김면정
15호 이호석
17호 김성연
18호 권한솔
19호 김주현
22호 조정래"""

st.sidebar.markdown("**순번표 / 차량표 (필요 시 수정하세요)**")
key_order_text = st.sidebar.text_area("열쇠 순번 (위→아래 순환)", default_key_order, height=160)
gyoyang_order_text = st.sidebar.text_area("교양 순번 (위→아래 순환)", default_gyoyang_order, height=160)
sudong_order_text = st.sidebar.text_area("1종 수동 순번 (위→아래 순환)", default_sudong_order, height=160)

st.sidebar.markdown("**차량 매핑 (한 줄에 `호수 이름`)**")
cha1_text = st.sidebar.text_area("1종 수동 차량표", default_cha1, height=140)
cha2_text = st.sidebar.text_area("2종 자동 차량표", default_cha2, height=200)

def parse_list(text):
    return [line.strip() for line in text.splitlines() if line.strip()]

def parse_vehicle_map(text):
    m = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            car = parts[0]
            name = " ".join(parts[1:])
            m[name] = car
    return m

# 순번표 및 차량 맵 파싱
key_order = parse_list(key_order_text)
gyoyang_order = parse_list(gyoyang_order_text)
sudong_order = parse_list(sudong_order_text)
veh1 = parse_vehicle_map(cha1_text)
veh2 = parse_vehicle_map(cha2_text)

########################################################################
# 3) [수정됨] Vision API OCR 함수 (고급 - document_text_detection)
########################################################################

def get_text_bounds(all_texts, text_description):
    """특정 텍스트의 경계 상자(bounding box)를 찾는 헬퍼 함수"""
    for text in all_texts[1:]:  # [0]은 전체 텍스트라 건너뜁니다.
        if text.description == text_description:
            return text.bounding_poly
    return None

def extract_doro_juhaeng_workers(file_content):
    """
    [새 함수] Google Cloud Vision API (DOCUMENT_TEXT_DETECTION)를 사용해
    이미지에서 '도로주행' 근무자 목록만 정확히 추출합니다.
    """
    if not file_content:
        return [], ""

    try:
        image = vision.Image(content=file_content)
        # [수정] text_detection -> document_text_detection로 변경 (표 분석에 강력함)
        response = client.document_text_detection(image=image)
        
        if response.error.message:
            st.error(f"Vision API 오류: {response.error.message}")
            return [], ""

        all_texts = response.text_annotations
        if not all_texts:
            st.warning("이미지에서 텍스트를 감지할 수 없습니다.")
            return [], ""

        full_text = all_texts[0].description
        page = response.full_text_annotation.pages[0]

        # 4. 기준점(Anchor)이 될 텍스트의 경계 상자 찾기
        # [수정] '도로주행'과 '성명' 헤더를 기준으로 삼습니다.
        doro_box = get_text_bounds(all_texts, "도로주행")
        name_header_box = get_text_bounds(all_texts, "성명")

        if not doro_box or not name_header_box:
            st.error("오류: 이미지에서 '도로주행' 또는 '성명' 헤더 텍스트를 찾지 못했습니다. OCR이 정확히 동작하지 않을 수 있습니다.")
            # 실패 시 기존 정규식 방식(부정확)으로 대체할 수 있으나, 여기서는 빈 리스트 반환
            return [], full_text

        # 5. '도로주행' 근무자 이름이 위치할 영역(Zone) 정의
        doro_y_start = doro_box.vertices[0].y
        doro_y_end = doro_box.vertices[3].y
        name_col_x_start = name_header_box.vertices[0].x - 10 # X축 여유분
        name_col_x_end = name_header_box.vertices[1].x + 10 # X축 여유분

        workers = []

        # 6. 감지된 모든 '단락(Paragraph)'을 순회하며 영역(Zone) 내 텍스트 추출
        for block in page.blocks:
            for paragraph in block.paragraphs:
                para_box = paragraph.bounding_box
                
                # 단락의 세로 중심점이 '도로주행' 셀 범위 안에 있는지 확인
                para_y_center = (para_box.vertices[0].y + para_box.vertices[3].y) / 2
                is_in_doro_rows = (para_y_center > doro_y_start) and (para_y_center < doro_y_end)
                
                # 단락의 가로 중심점이 '성명' 컬럼 범위 안에 있는지 확인
                para_x_center = (para_box.vertices[0].x + para_box.vertices[1].x) / 2
                is_in_name_column = (para_x_center > name_col_x_start) and (para_x_center < name_col_x_end)

                # 7. 두 조건을 모두 만족하면 근무자 목록에 추가
                if is_in_doro_rows and is_in_name_column:
                    para_text = "".join(
                        [symbol.text for word in paragraph.words for symbol in word.symbols]
                    )
                    # "성명" 헤더 자체는 제외
                    if para_text != "성명":
                        workers.append(para_text)

        return workers, full_text

    except Exception as e:
        st.error(f"OCR 처리 중 예외 발생: {e}")
        return [], ""

########################################################################
# 4) [신규] 유틸리티 함수: 순번 계산, JSON 로드
########################################################################

def next_in_cycle(current_item, item_list):
    """ [신규] 리스트에서 다음 순번 아이템을 찾습니다. (순환) """
    if not item_list:
        return None
    try:
        idx = item_list.index(current_item)
        return item_list[(idx + 1) % len(item_list)]
    except ValueError:
        # 현재 아이템이 리스트에 없으면 첫 번째 아이템 반환
        return item_list[0]

def next_valid_after(start_item, item_list, valid_set):
    """ [신규] 리스트에서 start_item 다음이면서 valid_set에 포함된 첫 아이템을 찾습니다. """
    if not item_list or not valid_set:
        return None
    
    start_idx = 0
    if start_item in item_list:
        start_idx = item_list.index(start_item)
    
    # 다음 인덱스부터 순회 시작
    for i in range(1, len(item_list) + 1):
        next_item = item_list[(start_idx + i) % len(item_list)]
        if next_item in valid_set:
            return next_item
    return None # 유효한 다음 근무자 없음

PREV_DAY_FILE = "전일근무.json"

def load_previous_day_data():
    """ [신규] 전일근무.json 파일이 있으면 데이터를 로드합니다. """
    if os.path.exists(PREV_DAY_FILE):
        try:
            with open(PREV_DAY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            st.sidebar.error(f"{PREV_DAY_FILE} 로드 실패: {e}")
    return {}

########################################################################
# 5) [수정] 사용자 입력: 전일 근무자, 정비차량 등 (사이드바)
########################################################################

# [수정] 앱 시작 시 전일 데이터 로드
prev_data = load_previous_day_data()

st.sidebar.markdown("---")
st.sidebar.header("날짜 및 옵션")
selected_date = st.sidebar.date_input("근무 날짜 선택")
# 날짜 포맷팅 (예: 2025/10/17(금))
st.session_state.date_str = selected_date.strftime("%Y/%m/%d") + f"({['월','화','수','목','금','토','일'][selected_date.weekday()]})"


st.sidebar.markdown("---")
st.sidebar.header("전일(기준) 입력 — (자동 로드됨)")
# [수정] value에 로드한 데이터 사용
prev_key = st.sidebar.text_input("전일 열쇠", value=prev_data.get("열쇠", ""))
prev_gyoyang5 = st.sidebar.text_input("전일 5교시 교양", value=prev_data.get("교양_5교시", ""))
prev_sudong = st.sidebar.text_input("전일 1종수동", value=prev_data.get("1종수동", ""))

st.sidebar.markdown("---")
st.sidebar.header("옵션")
sudong_count = st.sidebar.radio("1종 수동 인원수", [1, 2], index=0)
repair_cars = st.sidebar.text_input("정비중 차량 (쉼표로 구분)", value="")

# [수정] 전산병행 입력을 사이드바로 이동
computer_names_input = st.sidebar.text_input("전산병행자 이름 (쉼표로 구분)", value="")
computer_names = [n.strip() for n in computer_names_input.split(",") if n.strip()]


########################################################################
# 6) [수정] 메인 UI: 2단계 (분석 -> 확인 및 배정)
########################################################################

st.markdown("## ① 오전/오후 근무표 이미지 업로드")
st.info("이미지 업로드 후 **[① 이미지 분석]** 버튼을 누르세요. OCR이 '도로주행' 근무자만 추출합니다.")

col1, col2 = st.columns(2)
with col1:
    morning_file = st.file_uploader("오전 근무표 이미지 업로드", type=["png","jpg","jpeg"], key="morning")
with col2:
    afternoon_file = st.file_uploader("오후 근무표 이미지 업로드", type=["png","jpg","jpeg"], key="afternoon")

# --- 1단계: OCR 분석 ---
if st.button("① 이미지 분석 및 근무자 추출", type="primary"):
    with st.spinner("Google Vision API로 이미지를 분석 중입니다..."):
        if morning_file:
            morning_content = morning_file.getvalue()
            m_workers, m_text = extract_doro_juhaeng_workers(morning_content)
            st.session_state.morning_workers = m_workers
            st.session_state.morning_raw_text = m_text
        else:
            st.session_state.morning_workers = []
            st.session_state.morning_raw_text = "(오전 이미지 없음)"

        if afternoon_file:
            afternoon_content = afternoon_file.getvalue()
            a_workers, a_text = extract_doro_juhaeng_workers(afternoon_content)
            st.session_state.afternoon_workers = a_workers
            st.session_state.afternoon_raw_text = a_text
        else:
            st.session_state.afternoon_workers = []
            st.session_state.afternoon_raw_text = "(오후 이미지 없음)"
    
    st.success("✅ OCR 분석 완료. 아래 '② 근무자 목록 확인'에서 추출된 이름을 확인/수정하세요.")

st.markdown("---")

# --- 2단계: 근무자 확인 및 배정 생성 ---
if 'morning_workers' in st.session_state:
    st.markdown("## ② 근무자 목록 확인 및 최종 배정")
    st.warning("OCR 결과가 100% 정확하지 않을 수 있습니다. '도로주행' 근무자만 포함되도록 아래 목록을 직접 수정/확인해주세요.")

    col3, col4 = st.columns(2)
    with col3:
        st.markdown("#### ❮오전❯ 근무자 (확정)")
        morning_list_str = st.text_area(
            "오전 근무자 (한 줄에 하나씩)", 
            value="\n".join(st.session_state.morning_workers), 
            height=250,
            key="morning_list_final"
        )
        with st.expander("오전 OCR 원문 보기 (참고용)"):
            st.text_area("오전 OCR 원문", st.session_state.morning_raw_text, height=180)

    with col4:
        st.markdown("#### ❮오후❯ 근무자 (확정)")
        afternoon_list_str = st.text_area(
            "오후 근무자 (한 줄에 하나씩)", 
            value="\n".join(st.session_state.afternoon_workers), 
            height=250,
            key="afternoon_list_final"
        )
        with st.expander("오후 OCR 원문 보기 (참고용)"):
            st.text_area("오후 OCR 원문",