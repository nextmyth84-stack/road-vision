# app.py — 도로주행 근무자동배정 완전본 v2
import streamlit as st
from google.cloud import vision
from google.oauth2 import service_account
import json, re, os
from io import BytesIO
from fuzzywuzzy import fuzz

# -------------------------------
# 기본 페이지 / 스타일
# -------------------------------
st.set_page_config(page_title="도로주행 근무자동배정", layout="centered", initial_sidebar_state="collapsed")

# 모바일 UI 최적화를 위한 CSS
st.markdown("""
    <style>
        textarea, input, select, button {
            font-size: 18px !important;
        }
        button[kind="primary"] {
            width: 100% !important;
            height: 60px !important;
            font-size: 20px !important;
        }
        .stTextArea textarea {
            font-size: 16px !important;
        }
        .stMarkdown {
            font-size: 18px !important;
        }
        .stButton button {
            width: 100% !important;
            height: 55px !important;
        }
    </style>
""", unsafe_allow_html=True)

st.title("🚗 도로주행 근무자동배정 (완전본 v2)")

# -------------------------------
# 1. Google Vision API 인증
# -------------------------------
try:
    cred_info = json.loads(st.secrets["general"]["GOOGLE_APPLICATION_CREDENTIALS"])
    creds = service_account.Credentials.from_service_account_info(cred_info)
    client = vision.ImageAnnotatorClient(credentials=creds)
except Exception as e:
    st.error(f"⚠️ Vision API 인증 실패: {e}")
    st.stop()

# -------------------------------
# 2. OCR 및 이름 추출 함수
# -------------------------------
def ocr_get_text(image_bytes):
    """Google Vision OCR 실행 후 텍스트 반환"""
    image = vision.Image(content=image_bytes)
    res = client.text_detection(image=image)
    if res.error.message:
        raise Exception(res.error.message)
    return res.text_annotations[0].description if res.text_annotations else ""

def clean_and_extract_names(text):
    """OCR 원문에서 한글 이름만 정제 후 순서대로 추출"""
    if not text:
        return []

    # 불필요 영역 제거
    text = re.sub(r"[\(\[\{].*?[\)\]\}]", "", text)   # 괄호 안 내용 삭제
    text = re.sub(r"[0-9\-\.,·•:]+", " ", text)       # 숫자, 특수문자 제거
    text = re.sub(r"[a-zA-Z]+", " ", text)            # 영어 제거
    text = re.sub(r"\s+", " ", text)

    # '도로주행' 이후 부분만 사용
    m = re.search(r"도로\s*주행(.*)", text, re.DOTALL)
    if m:
        text = m.group(1)

    # 이름 후보 추출
    candidates = re.findall(r"[가-힣]{2,4}", text)
    # 제외어 필터
    exclude = {"성명", "교육", "오전", "오후", "합", "불", "정비", "시간", "차량", "확정"}
    names = [n for n in candidates if n not in exclude]

    # 중복 제거(순서 유지)
    seen = set()
    ordered = []
    for n in names:
        if n not in seen:
            seen.add(n)
            ordered.append(n)
    return ordered

# -------------------------------
# 3. 드래그형(터치형) 이름 선택 UI
# -------------------------------
def range_select_ui(names, label):
    """클릭 두 번으로 시작/끝 구간 선택"""
    if "sel_start" not in st.session_state:
        st.session_state.sel_start = None
    if "sel_end" not in st.session_state:
        st.session_state.sel_end = None

    st.markdown(f"### 👇 {label} 근무자 구간 선택 (한 번 클릭: 시작, 두 번째 클릭: 끝)")
    cols = st.columns(3)

    chosen = None
    for idx, name in enumerate(names):
        col = cols[idx % 3]
        with col:
            btn_key = f"{label}_{idx}"
            style = ""
            if name == st.session_state.sel_start or name == st.session_state.sel_end:
                style = "background-color:#90EE90;font-weight:bold;"
            if st.button(name, key=btn_key, use_container_width=True):
                if not st.session_state.sel_start:
                    st.session_state.sel_start = name
                elif not st.session_state.sel_end:
                    st.session_state.sel_end = name
                    chosen = True
    # 구간 확정
    if st.session_state.sel_start and st.session_state.sel_end:
        try:
            s = names.index(st.session_state.sel_start)
            e = names.index(st.session_state.sel_end)
            if s > e:
                s, e = e, s
            selected = names[s:e+1]
            st.success(f"✅ 선택된 구간: {names[s]} → {names[e]} ({len(selected)}명)")
            if chosen:
                # 선택 완료 후 초기화
                st.session_state.sel_start = None
                st.session_state.sel_end = None
            return selected
        except Exception:
            st.warning("선택 구간을 찾을 수 없습니다.")
    return []

# -------------------------------
# 4. 메인 로직
# -------------------------------
st.markdown("#### ① 근무표 이미지 업로드")
col1, col2 = st.columns(2)
with col1:
    morning = st.file_uploader("오전 근무표", type=["png","jpg","jpeg"], key="m_upload")
with col2:
    afternoon = st.file_uploader("오후 근무표", type=["png","jpg","jpeg"], key="a_upload")

if st.button("② OCR 실행 및 근무자 인식", type="primary"):
    if not morning and not afternoon:
        st.warning("이미지를 업로드하세요.")
    else:
        if morning:
            st.subheader("🌅 오전")
            txt = ocr_get_text(morning.getvalue())
            names = clean_and_extract_names(txt)
            st.write(f"인식된 이름 수: {len(names)}명")
            if names:
                st.session_state.morning_names = names
                selected_m = range_select_ui(names, "오전")
                st.session_state.selected_morning = selected_m
            else:
                st.error("이름을 인식하지 못했습니다.")
        if afternoon:
            st.subheader("🌇 오후")
            txt = ocr_get_text(afternoon.getvalue())
            names = clean_and_extract_names(txt)
            st.write(f"인식된 이름 수: {len(names)}명")
            if names:
                st.session_state.afternoon_names = names
                selected_a = range_select_ui(names, "오후")
                st.session_state.selected_afternoon = selected_a
            else:
                st.error("이름을 인식하지 못했습니다.")

# -------------------------------
# 5. 결과 확인
# -------------------------------
if st.session_state.get("selected_morning") or st.session_state.get("selected_afternoon"):
    st.markdown("---")
    st.subheader("✅ 최종 근무자 결과 확인")

    col3, col4 = st.columns(2)
    with col3:
        morning_final = st.text_area("오전 근무자", "\n".join(st.session_state.get("selected_morning", [])), height=200)
    with col4:
        afternoon_final = st.text_area("오후 근무자", "\n".join(st.session_state.get("selected_afternoon", [])), height=200)

    if st.button("③ 결과 저장 및 다운로드", type="primary"):
        data = {
            "오전": morning_final.splitlines(),
            "오후": afternoon_final.splitlines()
        }
        result_text = "📋 도로주행 근무자 결과\n\n" + \
                      "❮오전❯\n" + "\n".join(data["오전"]) + "\n\n" + \
                      "❮오후❯\n" + "\n".join(data["오후"])
        st.download_button(
            "결과 파일 다운로드 (.txt)",
            data=result_text.encode("utf-8-sig"),
            file_name="도로주행_근무자_결과.txt",
            mime="text/plain"
        )
        st.success("✅ 결과 파일이 생성되었습니다.")
else:
    st.info("이미지를 업로드하고 OCR을 실행해보세요.")
