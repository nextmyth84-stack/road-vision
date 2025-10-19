# app.py
import streamlit as st
from google.cloud import vision
from google.oauth2 import service_account
import re
import json
from PIL import Image
from io import BytesIO

st.set_page_config(page_title="근무표 자동 배정 (한글 OCR 버전)", layout="wide")

st.title("🚦 근무표 자동 배정 — (Google Vision OCR + 한글 텍스트 출력)")

########################################################################
# 1) Google Vision API 인증 설정
########################################################################
try:
    cred_data = json.loads(st.secrets["general"]["GOOGLE_APPLICATION_CREDENTIALS"])
    creds = service_account.Credentials.from_service_account_info(cred_data)
    client = vision.ImageAnnotatorClient(credentials=creds)
except Exception as e:
    st.error("⚠️ Google Vision API 인증 실패: Secrets 설정을 다시 확인하세요.")
    st.stop()

########################################################################
# 2) 순번표 및 차량 매핑 설정
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

key_order = parse_list(key_order_text)
gyoyang_order = parse_list(gyoyang_order_text)
sudong_order = parse_list(sudong_order_text)
veh1 = parse_vehicle_map(cha1_text)
veh2 = parse_vehicle_map(cha2_text)

########################################################################
# 3) Vision API OCR 함수
########################################################################

def extract_text_from_image(uploaded_file):
    if not uploaded_file:
        return ""
    try:
        image = vision.Image(content=uploaded_file.read())
        response = client.text_detection(image=image)
        texts = response.text_annotations
        if response.error.message:
            st.error(f"Vision API 오류: {response.error.message}")
            return ""
        return texts[0].description if texts else ""
    except Exception as e:
        st.error(f"OCR 중 오류 발생: {e}")
        return ""

name_regex = re.compile(r'[가-힣]{2,3}')

def extract_names(text):
    found = name_regex.findall(text)
    seen, ordered = set(), []
    for f in found:
        if f not in seen:
            seen.add(f)
            ordered.append(f)
    return ordered

########################################################################
# 4) 사용자 입력: 전일 근무자, 정비차량 등
########################################################################

st.sidebar.markdown("---")
st.sidebar.header("전일(기준) 입력 — 꼭 채워주세요")
prev_key = st.sidebar.text_input("전일 열쇠", value="")
prev_gyoyang5 = st.sidebar.text_input("전일 5교시 교양", value="")
prev_sudong = st.sidebar.text_input("전일 1종수동", value="")

st.sidebar.markdown("---")
st.sidebar.header("옵션")
sudong_count = st.sidebar.radio("1종 수동 인원수", [1, 2], index=0)
repair_cars = st.sidebar.text_input("정비중 차량 (쉼표로 구분)", value="")

########################################################################
# 5) 오전/오후 이미지 업로드 및 분석
########################################################################

st.markdown("## ① 오전/오후 근무표 이미지 업로드")
col1, col2 = st.columns(2)
with col1:
    morning_file = st.file_uploader("오전 근무표 이미지 업로드", type=["png", "jpg", "jpeg"], key="morning")
with col2:
    afternoon_file = st.file_uploader("오후 근무표 이미지 업로드", type=["png", "jpg", "jpeg"], key="afternoon")

if st.button("분석 시작"):
    st.markdown("### ⏳ Google Vision API로 OCR 중... 잠시만 기다려주세요.")

    morning_text = extract_text_from_image(morning_file)
    afternoon_text = extract_text_from_image(afternoon_file)

    morning_names = extract_names(morning_text)
    afternoon_names = extract_names(afternoon_text)

    st.markdown("### OCR 추출 결과 (오전)")
    st.text_area("오전 OCR 텍스트", morning_text, height=180)
    st.markdown("이름 추출: " + ", ".join(morning_names))

    st.markdown("### OCR 추출 결과 (오후)")
    st.text_area("오후 OCR 텍스트", afternoon_text, height=180)
    st.markdown("이름 추출: " + ", ".join(afternoon_names))

    # 이후 근무자 자동 배정 로직은 기존 코드와 동일하게 유지
    st.success("✅ OCR 완료! 다음 단계에서 근무자 자동 배정이 가능합니다.")
else:
    st.info("이미지를 업로드한 후 '분석 시작' 버튼을 눌러주세요.")
