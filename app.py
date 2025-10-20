# app.py — 도로주행 근무자동배정 완전본 v2 (수정본)
import streamlit as st
from google.cloud import vision
from google.oauth2 import service_account
import json, re, os
from io import BytesIO
# from fuzzywuzzy import fuzz # [참고] 원본 코드에서 import되었으나 사용되지 않아 주석 처리

# -------------------------------
# 기본 페이지 / 스타일
# -------------------------------
st.set_page_config(page_title="도로주행 근무자동배정", layout="centered", initial_sidebar_state="collapsed")

# 모바일 UI 최적화를 위한 CSS (원본과 동일)
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
    
# ---------------------------
# 2) Sidebar: 기본 순번 / 차량표
# ---------------------------
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

# [수정] 이름 추출 로직 대폭 개선
def clean_and_extract_names(text):
    """OCR 원문에서 한글 이름만 정제 후 순서대로 추출"""
    if not text:
        return []

    # 불필요 영역 제거 (괄호, 숫자, 영어 등) - 원본과 유사
    text = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", text)  # 괄호 안 내용 삭제 (공백으로 치환)
    text = re.sub(r"[0-9\-\.,·•:/\\]+", " ", text)   # 숫자, 특수문자 제거 (공백으로 치환)
    text = re.sub(r"[a-zA-Z]+", " ", text)           # 영어 제거 (공백으로 치환)

    # [수정 1] '도로주행' 필터 제거
    # 이 필터가 '도로주행' 글자 이전에 인식된 이름들을 잘라내는 핵심 원인이었습니다.
    # m = re.search(r"도로\s*주행(.*)", text, re.DOTALL)
    # if m:
    #     text = m.group(1)

    # 여러 공백을 하나로
    text = re.sub(r"\s+", " ", text)

    # [수정 2] 이름 후보 추출 (2~5글자)
    # 5글자 이름(예: 남궁민수)이나 OCR 오류를 대비해 5글자까지 허용
    candidates = re.findall(r"[가-힣]{2,5}", text)

    # [수정 3] 제외어 목록 확장
    # '합격', '불합격', '근무', '휴무' 등 이름으로 오인될 수 있는 단어 추가
    exclude = {
        "성명", "교육", "오전", "오후", "합", "불", "정비", "시간", "차량", "확정",
        "합격", "불합격", "근무", "휴무", "대기", "번호", "감독", "코스", "도로", "주행",
        "응시자", "수험생", "검정원", "월", "일", "명단", "배정", "시험", "기능"
    }
    
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
# [수정] 오전/오후 상태가 겹치지 않도록 session_state 키 수정
def range_select_ui(names, label):
    """클릭 두 번으로 시작/끝 구간 선택. (오전/오후 상태 분리)"""
    
    # [수정] 오전/오후가 상태를 공유하지 않도록 label을 키 이름에 포함
    start_key = f"sel_start_{label}"
    end_key = f"sel_end_{label}"

    if start_key not in st.session_state:
        st.session_state[start_key] = None
    if end_key not in st.session_state:
        st.session_state[end_key] = None

    st.markdown(f"### 👇 {label} 근무자 구간 선택 (시작/끝 클릭)")
    cols = st.columns(3)

    chosen = None
    for idx, name in enumerate(names):
        col = cols[idx % 3]
        with col:
            btn_key = f"{label}_{idx}"
            
            # [수정] 고유한 session_state 키 사용
            is_selected = (name == st.session_state[start_key] or name == st.session_state[end_key])
            btn_type = "primary" if is_selected else "secondary"
            
            if st.button(name, key=btn_key, use_container_width=True, type=btn_type):
                if not st.session_state[start_key]:
                    st.session_state[start_key] = name
                elif not st.session_state[end_key]:
                    st.session_state[end_key] = name
                    chosen = True # 구간 선택 완료
                else: 
                    # [수정] 이미 시작/끝이 선택된 경우, 새로 선택 시작
                    st.session_state[start_key] = name
                    st.session_state[end_key] = None

    # 구간 확정
    if st.session_state[start_key] and st.session_state[end_key]:
        try:
            s = names.index(st.session_state[start_key])
            e = names.index(st.session_state[end_key])
            if s > e:
                s, e = e, s
            selected = names[s:e+1]
            st.success(f"✅ {label} 선택: {names[s]} → {names[e]} ({len(selected)}명)")
            
            if chosen:
                # 선택 완료 후 상태 초기화
                st.session_state[start_key] = None
                st.session_state[end_key] = None
            return selected
        except Exception:
            st.warning("선택 구간을 찾을 수 없습니다. 다시 시도하세요.")
            # 오류 시 초기화
            st.session_state[start_key] = None
            st.session_state[end_key] = None
    return []

# -------------------------------
# 4. 메인 로직 (OCR 실행)
# -------------------------------
st.markdown("#### ① 근무표 이미지 업로드")
col1, col2 = st.columns(2)
with col1:
    morning = st.file_uploader("오전 근무표", type=["png","jpg","jpeg"], key="m_upload")
with col2:
    afternoon = st.file_uploader("오후 근무표", type=["png","jpg","jpeg"], key="a_upload")

# [수정] OCR 실행 버튼은 'st.session_state'에 이름 목록을 '저장'하는 역할만 담당
if st.button("② OCR 실행 및 근무자 인식", type="primary"):
    if not morning and not afternoon:
        st.warning("이미지를 업로드하세요.")
    else:
        with st.spinner("OCR을 실행 중입니다..."):
            if morning:
                txt = ocr_get_text(morning.getvalue())
                names_m = clean_and_extract_names(txt)
                if names_m:
                    st.session_state.morning_names = names_m
                else:
                    st.error("오전 근무표에서 이름을 인식하지 못했습니다.")
                    if "morning_names" in st.session_state: # 이전 결과 삭제
                        del st.session_state.morning_names

            if afternoon:
                txt = ocr_get_text(afternoon.getvalue())
                names_a = clean_and_extract_names(txt)
                if names_a:
                    st.session_state.afternoon_names = names_a
                else:
                    st.error("오후 근무표에서 이름을 인식하지 못했습니다.")
                    if "afternoon_names" in st.session_state: # 이전 결과 삭제
                        del st.session_state.afternoon_names
        
        # OCR 실행 후에는 이전에 '선택 완료'된 항목들을 초기화
        if "selected_morning" in st.session_state:
            del st.session_state.selected_morning
        if "selected_afternoon" in st.session_state:
            del st.session_state.selected_afternoon
        
        # UI를 즉시 새로고침하여 아래의 '이름 선택 UI'가 표시되도록 함
        st.rerun() 

# -------------------------------
# [수정] 4.5. 이름 선택 UI (메인 로직과 분리)
# -------------------------------
# OCR 버튼 클릭 여부와 관계없이, st.session_state에 이름이 '있으면' 항상 UI를 그림
# 이것이 Streamlit 상태 관리의 핵심입니다.

has_names = False # 선택 UI가 하나라도 그려졌는지 확인

if st.session_state.get("morning_names"):
    has_names = True
    st.subheader("🌅 오전")
    st.write(f"인식된 이름 수: {len(st.session_state.morning_names)}명")
    selected_m = range_select_ui(st.session_state.morning_names, "오전")
    if selected_m: # range_select_ui가 최종 선택 리스트를 반환했을 때
        st.session_state.selected_morning = selected_m
        st.rerun() # 선택 완료 후 즉시 새로고침하여 '결과 확인'란에 반영

if st.session_state.get("afternoon_names"):
    has_names = True
    st.subheader("🌇 오후")
    st.write(f"인식된 이름 수: {len(st.session_state.afternoon_names)}명")
    selected_a = range_select_ui(st.session_state.afternoon_names, "오후")
    if selected_a: # range_select_ui가 최종 선택 리스트를 반환했을 때
        st.session_state.selected_afternoon = selected_a
        st.rerun() # 선택 완료 후 즉시 새로고침하여 '결과 확인'란에 반영

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
    # [수정] UI 흐름에 맞는 안내 메시지
    # 이름은 인식되었으나 아직 '구간 선택'을 안 한 경우
    if has_names: 
        st.info("위에서 근무자 구간을 선택하세요. (시작 이름 클릭, 끝 이름 클릭)")
    # 처음 상태
    else:
        st.info("이미지를 업로드하고 ② OCR 실행 버튼을 눌러주세요.")
