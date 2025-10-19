import streamlit as st
from PIL import Image
import re
import json
from io import BytesIO
from google.cloud import vision
from google.oauth2 import service_account

# --- Google Vision 인증 ---
service_account_info = json.loads(st.secrets["general"]["GOOGLE_APPLICATION_CREDENTIALS"])
credentials = service_account.Credentials.from_service_account_info(service_account_info)
client = vision.ImageAnnotatorClient(credentials=credentials)


st.set_page_config(page_title="근무표 자동 배정 (Google Vision OCR 버전)", layout="wide")
st.title("🚦 근무표 자동 배정 — (Google Vision OCR 기반 한글 텍스트 출력)")

########################################################################
# 1) 설정: 기본 순번표 / 차량 매핑
########################################################################
st.sidebar.header("초기 데이터 입력 (필요 시 수정)")

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
key_order_text = st.sidebar.text_area("열쇠 순번", default_key_order, height=160)
gyoyang_order_text = st.sidebar.text_area("교양 순번", default_gyoyang_order, height=160)
sudong_order_text = st.sidebar.text_area("1종 수동 순번", default_sudong_order, height=160)

st.sidebar.markdown("**차량 매핑 (한 줄에 `호수 이름`)**")
cha1_text = st.sidebar.text_area("1종 수동 차량표", default_cha1, height=140)
cha2_text = st.sidebar.text_area("2종 자동 차량표", default_cha2, height=200)

def parse_list(text):
    return [line.strip() for line in text.splitlines() if line.strip()]

def parse_vehicle_map(text):
    m = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            m[" ".join(parts[1:])] = parts[0]
    return m

key_order = parse_list(key_order_text)
gyoyang_order = parse_list(gyoyang_order_text)
sudong_order = parse_list(sudong_order_text)
veh1 = parse_vehicle_map(cha1_text)
veh2 = parse_vehicle_map(cha2_text)

########################################################################
# 2) 유틸리티: OCR, 이름 추출, 순번 계산
########################################################################
st.sidebar.markdown("---")
st.sidebar.header("전일(기준) 입력 — 꼭 채워주세요")
prev_key = st.sidebar.text_input("전일 열쇠", "")
prev_gyoyang5 = st.sidebar.text_input("전일 5교시 교양", "")
prev_sudong = st.sidebar.text_input("전일 1종수동", "")

st.sidebar.markdown("---")
st.sidebar.header("옵션")
sudong_count = st.sidebar.radio("1종 수동 인원수", [1, 2], index=0)
has_computer = st.sidebar.checkbox("전산병행 있음", value=False)
repair_cars = st.sidebar.text_input("정비중 차량 (쉼표 구분)", "")

# Google Vision OCR 함수
def extract_text_from_image(uploaded_file):
    if not uploaded_file:
        return ""
    try:
        client = vision.ImageAnnotatorClient()
        image = vision.Image(content=uploaded_file.read())
        response = client.text_detection(image=image)
        texts = response.text_annotations
        if texts:
            return texts[0].description
        else:
            return ""
    except Exception as e:
        st.error(f"OCR 오류 발생: {e}")
        return ""

# 이름 추출 (한글 2~3자)
name_regex = re.compile(r'[가-힣]{2,3}')
def extract_names(text):
    found = name_regex.findall(text)
    seen, ordered = set(), []
    for f in found:
        if f not in seen:
            seen.add(f)
            ordered.append(f)
    return ordered

def next_in_cycle(current, cycle_list):
    if not cycle_list:
        return None
    if current not in cycle_list:
        return cycle_list[0]
    idx = cycle_list.index(current)
    return cycle_list[(idx + 1) % len(cycle_list)]

def next_valid_after(current, cycle_list, present_set):
    if not cycle_list:
        return None
    start_idx = (cycle_list.index(current) + 1) % len(cycle_list) if current in cycle_list else 0
    for i in range(len(cycle_list)):
        cand = cycle_list[(start_idx + i) % len(cycle_list)]
        if cand in present_set:
            return cand
    return None

########################################################################
# 3) 파일 업로드 및 OCR 실행
########################################################################
st.markdown("## ① 오전/오후 근무표 이미지 업로드")
col1, col2 = st.columns(2)
with col1:
    morning_file = st.file_uploader("오전 근무표 (이미지)", type=["png", "jpg", "jpeg"], key="morning")
with col2:
    afternoon_file = st.file_uploader("오후 근무표 (이미지)", type=["png", "jpg", "jpeg"], key="afternoon")

st.markdown("옵션을 확인한 뒤 **분석 시작** 버튼을 눌러주세요.")

if st.button("분석 시작"):
    morning_text = extract_text_from_image(morning_file)
    afternoon_text = extract_text_from_image(afternoon_file)

    morning_names = extract_names(morning_text)
    afternoon_names = extract_names(afternoon_text)

    st.markdown("### OCR 결과 (오전)")
    st.text_area("오전 OCR 원문", morning_text, height=150)
    st.write("**이름 추출 결과:**", ", ".join(morning_names))

    st.markdown("### OCR 결과 (오후)")
    st.text_area("오후 OCR 원문", afternoon_text, height=150)
    st.write("**이름 추출 결과:**", ", ".join(afternoon_names))

    computer_names_input = st.text_input("전산병행자 이름 (콤마 구분)", "")
    computer_names = [n.strip() for n in computer_names_input.split(",") if n.strip()]

    morning_list = st.text_area("오전 근무자 수정", "\n".join(morning_names), height=120).splitlines()
    afternoon_list = st.text_area("오후 근무자 수정", "\n".join(afternoon_names), height=120).splitlines()
    morning_list = [x.strip() for x in morning_list if x.strip()]
    afternoon_list = [x.strip() for x in afternoon_list if x.strip()]
    repair_list = [x.strip() for x in repair_cars.split(",") if x.strip()]

    # 이후 근무 배정 로직 (기존 코드 그대로)
    # 🔽🔽 기존의 오전/오후 배정 계산 부분 그대로 유지 🔽🔽
    # (여기서는 생략 — 위 pytesseract 버전과 동일하게 이어서 작성)

else:
    st.info("이미지를 업로드하고 '분석 시작'을 눌러주세요. Google Vision API를 통해 한글 OCR을 수행합니다.")
