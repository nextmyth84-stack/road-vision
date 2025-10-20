import streamlit as st
from google.cloud import vision
from PIL import Image
import io, json, re

st.set_page_config(page_title="근무표 자동 배정 (Vision OCR)", layout="wide")

st.title("🚦 근무표 자동 배정 — Vision API 기반 (V3 완전본)")

# -----------------------------
# 🔧 Vision API OCR 함수
# -----------------------------
def ocr_text_google(image_file):
    try:
        client = vision.ImageAnnotatorClient()
        content = image_file.read()
        image = vision.Image(content=content)
        response = client.text_detection(image=image)
        if response.error.message:
            st.error(f"OCR 오류: {response.error.message}")
            return ""
        return response.text_annotations[0].description if response.text_annotations else ""
    except Exception as e:
        st.error(f"OCR 처리 중 예외 발생: {e}")
        return ""

# -----------------------------
# 🧹 텍스트 정제 (괄호, 특수문자 제거)
# -----------------------------
def clean_text(raw_text):
    # 괄호 안 내용 제거
    cleaned = re.sub(r"\([^)]*\)", "", raw_text)
    # 불필요 공백 및 특수문자 제거
    cleaned = re.sub(r"[^가-힣\n]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()

# -----------------------------
# 🔍 이름 추출 (수정된 부분)
# -----------------------------
def extract_korean_names(text):
    # 2~3글자에서 2~4글자까지 허용하도록 정규식 수정
    pattern = re.compile(r"[가-힣]{2,4}") 
    names = pattern.findall(text)
    seen, ordered = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            ordered.append(n)
    return ordered

# -----------------------------
# 🔄 순번 로직
# -----------------------------
def next_in_cycle(current, order_list):
    if not order_list:
        return None
    if current not in order_list:
        return order_list[0]
    idx = order_list.index(current)
    return order_list[(idx + 1) % len(order_list)]

def next_valid_after(current, cycle_list, present_set):
    if not cycle_list:
        return None
    if current not in cycle_list:
        start_idx = 0
    else:
        start_idx = (cycle_list.index(current) + 1) % len(cycle_list)
    for i in range(len(cycle_list)):
        idx = (start_idx + i) % len(cycle_list)
        cand = cycle_list[idx]
        if cand in present_set:
            return cand
    return None

# -----------------------------
# ⚙️ 초기 설정
# -----------------------------
st.sidebar.header("🔧 전일 기준 입력")
prev_key = st.sidebar.text_input("전일 열쇠", "")
prev_gyoyang = st.sidebar.text_input("전일 5교시 교양", "")
prev_sudong = st.sidebar.text_input("전일 1종 수동", "")

sudong_count = st.sidebar.radio("1종 수동 인원수", [1, 2], index=0)
has_computer = st.sidebar.checkbox("전산병행 있음 (교양 제외)", value=False)
repair_cars = st.sidebar.text_input("정비중 차량 (쉼표로 구분)", "")

# 순번표 (필요 시 수정 가능)
default_order = """권한솔
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
key_order = [x.strip() for x in default_order.splitlines() if x.strip()]
gyoyang_order = key_order
sudong_order = key_order

# 차량 매핑 (샘플)
veh1 = {"조정래":"2호", "권한솔":"5호", "김남균":"7호", "이호석":"8호", "김성연":"10호"}
veh2 = {"김남균":"4호", "김병욱":"5호", "김지은":"6호", "안유미":"12호", "김면정":"14호",
        "이호석":"15호", "김성연":"17호", "권한솔":"18호", "김주현":"19호", "조정래":"22호"}

# -----------------------------
# 🖼️ 이미지 업로드
# -----------------------------
st.markdown("## 🖼️ 오전 근무표 이미지 업로드 (Vision API)")
uploaded_file = st.file_uploader("근무표 이미지 (오전)", type=["png","jpg","jpeg"])

if uploaded_file:
    with st.spinner("Vision API로 OCR 인식 중..."):
        ocr_text = ocr_text_google(uploaded_file)

    cleaned = clean_text(ocr_text)
    names_all = extract_korean_names(cleaned)
    st.text_area("🔍 OCR 원문", ocr_text, height=180)
    st.text("🧩 추출된 이름: " + ", ".join(names_all))

    # 시작/끝 이름 선택
    start_name = st.selectbox("🚩 도로주행 시작 이름 선택", options=["(선택 없음)"] + names_all, index=0)
    end_name = st.selectbox("🏁 도로주행 끝 이름 선택", options=["(선택 없음)"] + names_all, index=0)

    if start_name != "(선택 없음)" and end_name != "(선택 없음)":
        try:
            s_idx = names_all.index(start_name)
            e_idx = names_all.index(end_name)
            if s_idx <= e_idx:
                road_names = names_all[s_idx:e_idx+1]
            else:
                road_names = names_all[e_idx:s_idx+1]
        except ValueError:
            road_names = []
    else:
        road_names = []

    st.markdown("### 🚗 도로주행 근무자 명단")
    st.write(", ".join(road_names) if road_names else "❌ 근무자 선택 필요")

    # -----------------------------
    # ✅ 근무자 순번 배정
    # -----------------------------
    if st.button("📋 오전 근무 자동 배정"):
        if not road_names:
            st.warning("도로주행 근무자를 먼저 선택하세요.")
        else:
            present_set = set(road_names)

            # 열쇠
            today_key = next_in_cycle(prev_key, key_order)

            # 교양 (2명)
            gy_start = next_in_cycle(prev_gyoyang, gyoyang_order)
            gy_candidates = []
            idx = gyoyang_order.index(gy_start) if gy_start in gyoyang_order else 0 # gy_start가 없을 경우 대비
            for i in range(len(gyoyang_order)):
                cand = gyoyang_order[(idx + i) % len(gyoyang_order)]
                if cand in present_set:
                    gy_candidates.append(cand)
                if len(gy_candidates) >= 2:
                    break

            # 1종 수동
            sudong_assigned = []
            cur = prev_sudong
            for _ in range(len(sudong_order)):
                cand = next_in_cycle(cur, sudong_order)
                cur = cand
                if cand in present_set and cand not in sudong_assigned:
                    sudong_assigned.append(cand)
                if len(sudong_assigned) >= sudong_count:
                    break

            # 2종 자동
            auto_drivers = [p for p in road_names if p not in sudong_assigned]

            # 결과 출력
            st.markdown("## 🧾 오전 근무 결과")
            st.text(f"열쇠: {today_key}")
            st.text(f"교양 1교시: {gy_candidates[0] if len(gy_candidates)>0 else '-'}")
            st.text(f"교양 2교시: {gy_candidates[1] if len(gy_candidates)>1 else '-'}")

            for idx, s in enumerate(sudong_assigned, start=1):
                car = veh1.get(s, "")
                st.text(f"1종 수동 #{idx}: {s} ({car})")

            st.markdown("**2종 자동 근무자:**")
            for a in auto_drivers:
                car = veh2.get(a, "")
                st.text(f"- {a} ({car})")
else:
    st.info("📤 근무표 이미지를 업로드하면 Vision API로 자동 인식합니다.")
