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
    
# 순번표 및 차량 맵 파싱
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
        "응시자", "수험생", "검정원", "월", "일", "명단", "배정", "시험", "기능", "도로주행"
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

########################################################################
# 4) 유틸리티 함수: 순번 계산, JSON 로드
########################################################################

def next_in_cycle(current_item, item_list):
    """ 리스트에서 다음 순번 아이템을 찾습니다. (순환) """
    if not item_list:
        return None
    try:
        idx = item_list.index(current_item)
        return item_list[(idx + 1) % len(item_list)]
    except ValueError:
        # 현재 아이템이 리스트에 없으면 첫 번째 아이템 반환
        return item_list[0]

def next_valid_after(start_item, item_list, valid_set):
    """ 리스트에서 start_item 다음이면서 valid_set에 포함된 첫 아이템을 찾습니다. """
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
    """ 전일근무.json 파일이 있으면 데이터를 로드합니다. """
    if os.path.exists(PREV_DAY_FILE):
        try:
            with open(PREV_DAY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            st.sidebar.error(f"{PREV_DAY_FILE} 로드 실패: {e}")
    return {}

########################################################################
# 5) 사용자 입력: 전일 근무자, 정비차량 등 (사이드바)
########################################################################

# 앱 시작 시 전일 데이터 로드
prev_data = load_previous_day_data()

st.sidebar.markdown("---")
st.sidebar.header("날짜 및 옵션")
selected_date = st.sidebar.date_input("근무 날짜 선택")
st.session_state.date_str = selected_date.strftime("%Y/%m/%d") + f"({['월','화','수','목','금','토','일'][selected_date.weekday()]})"


st.sidebar.markdown("---")
st.sidebar.header("전일(기준) 입력 — (자동 로드됨)")
prev_key = st.sidebar.text_input("전일 열쇠", value=prev_data.get("열쇠", ""), key="prev_key_input")
prev_gyoyang5 = st.sidebar.text_input("전일 5교시 교양", value=prev_data.get("교양_5교시", ""), key="prev_gyoyang5_input")
prev_sudong = st.sidebar.text_input("전일 1종수동", value=prev_data.get("1종수동", ""), key="prev_sudong_input")

st.sidebar.markdown("---")
st.sidebar.header("옵션")
sudong_count = st.sidebar.radio("1종 수동 인원수", [1, 2], index=0, key="sudong_count_radio")
repair_cars = st.sidebar.text_input("정비중 차량 (쉼표로 구분)", value="", key="repair_cars_input")

computer_names_input = st.sidebar.text_input("전산병행자 이름 (쉼표로 구분)", value="", key="computer_names_input")
computer_names = [n.strip() for n in computer_names_input.split(",") if n.strip()]


########################################################################
# 6) 메인 UI: 2단계 (분석 -> 확인 및 배정)
########################################################################

st.markdown("## ① 오전/오후 근무표 이미지 업로드")
st.info("이미지 업로드 후 **[① 이미지 분석]** 버튼을 누르세요. OCR이 '도로주행' 근무자만 추출합니다.")

col1, col2 = st.columns(2)
with col1:
    morning_file = st.file_uploader("오전 근무표 이미지 업로드", type=["png","jpg","jpeg"], key="morning_uploader")
with col2:
    afternoon_file = st.file_uploader("오후 근무표 이미지 업로드", type=["png","jpg","jpeg"], key="afternoon_uploader")

# --- 1단계: OCR 분석 ---
if st.button("① 이미지 분석 및 근무자 추출", type="primary", key="analyze_button"):
    with st.spinner("Google Vision API로 이미지를 분석 중입니다..."):
        # 오전 파일 처리
        if morning_file:
            morning_content = morning_file.getvalue()
            m_workers, m_text, m_error = extract_doro_juhaeng_workers(morning_content)
            st.session_state.morning_workers = m_workers
            st.session_state.morning_raw_text = m_text
            st.session_state.morning_error = m_error
        else:
            st.session_state.morning_workers = []
            st.session_state.morning_raw_text = "(오전 이미지 없음)"
            st.session_state.morning_error = None

        # 오후 파일 처리
        if afternoon_file:
            afternoon_content = afternoon_file.getvalue()
            a_workers, a_text, a_error = extract_doro_juhaeng_workers(afternoon_content)
            st.session_state.afternoon_workers = a_workers
            st.session_state.afternoon_raw_text = a_text
            st.session_state.afternoon_error = a_error
        else:
            st.session_state.afternoon_workers = []
            st.session_state.afternoon_raw_text = "(오후 이미지 없음)"
            st.session_state.afternoon_error = None
    
    if st.session_state.get('morning_error') or st.session_state.get('afternoon_error'):
        st.error("⚠️ OCR 분석 중 오류가 발생했습니다. 아래 OCR 원문을 확인하고 근무자를 수동으로 입력해주세요.")
    else:
        st.success("✅ OCR 분석 완료. 아래 '② 근무자 목록 확인'에서 추출된 이름을 확인/수정하세요.")

st.markdown("---")

# --- 2단계: 근무자 확인 및 배정 생성 ---
# session_state에 OCR 결과가 있을 때만 이 섹션을 표시
if 'morning_workers' in st.session_state and 'afternoon_workers' in st.session_state:
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
            st.text_area("오전 OCR 원문", st.session_state.morning_raw_text, height=180, key="morning_raw_text_display")

    with col4:
        st.markdown("#### ❮오후❯ 근무자 (확정)")
        afternoon_list_str = st.text_area(
            "오후 근무자 (한 줄에 하나씩)", 
            value="\n".join(st.session_state.afternoon_workers), 
            height=250,
            key="afternoon_list_final"
        )
        with st.expander("오후 OCR 원문 보기 (참고용)"):
            st.text_area("오후 OCR 원문", st.session_state.afternoon_raw_text, height=180, key="afternoon_raw_text_display")

    st.markdown("---")
    
    if st.button("② 최종 근무 배정 생성", type="primary", key="generate_assignment_button"):
        with st.spinner("배정 로직을 계산 중입니다..."):
            
            # 확정된 리스트 파싱
            morning_list = parse_list(morning_list_str)
            afternoon_list = parse_list(afternoon_list_str)
            present_set_morning = set(morning_list)
            present_set_afternoon = set(afternoon_list)
            
            # 정비 차량 파싱
            repair_list = [x.strip() for x in repair_cars.split(",") if x.strip()]

            # --- 오전 배정 로직 ---
            
            # 열쇠
            today_key = next_in_cycle(prev_key, key_order)

            # 교양 오전 (2명)
            gy_start = next_in_cycle(prev_gyoyang5, gyoyang_order)
            gy_candidates = []
            
            current_gy = gy_start
            for _ in range(len(gyoyang_order) * 2): # 혹시 사이클이 길어질까봐 *2
                if current_gy in present_set_morning and current_gy not in computer_names:
                    if current_gy not in gy_candidates:
                         gy_candidates.append(current_gy)
                if len(gy_candidates) >= 2:
                    break
                current_gy = next_in_cycle(current_gy, gyoyang_order)
            
            gy1 = gy_candidates[0] if len(gy_candidates) >= 1 else None
            gy2 = gy_candidates[1] if len(gy_candidates) >= 2 else None

            # 1종 수동 오전
            sudong_assigned = []
            current_sudong = prev_sudong
            
            for _ in range(len(sudong_order) * 2):
                next_cand = next_in_cycle(current_sudong, sudong_order)
                current_sudong = next_cand 
                
                if next_cand in present_set_morning:
                    if next_cand not in sudong_assigned:
                        sudong_assigned.append(next_cand)
                
                if len(sudong_assigned) >= sudong_count:
                    break
            
            # 2종 자동 오전
            morning_2jong = [p for p in morning_list if p not in sudong_assigned]
            morning_2jong_map = []
            for name in morning_2jong:
                car = veh2.get(name, "")
                note = "(정비중)" if car and car in repair_list else ""
                morning_2jong_map.append((name, car, note))

            # 오전 결과 텍스트 생성
            morning_lines = []
            morning_lines.append(f"📅 {st.session_state.date_str} 오전 근무 배정 결과")
            morning_lines.append("="*30)
            morning_lines.append(f"🔑 열쇠: {today_key}")
            morning_lines.append("\n🎓 교양 (오전)")
            morning_lines.append(f"  - 1교시: {gy1 if gy1 else '-'}")
            morning_lines.append(f"  - 2교시: {gy2 if gy2 else '-'}")

            morning_lines.append("\n🚛 1종 수동 (오전)")
            if sudong_assigned:
                for idx, name in enumerate(sudong_assigned, start=1):
                    car = veh1.get(name, "")
                    morning_lines.append(f"  - 1종#{idx}: {name}" + (f" ({car})" if car else ""))
            else:
                morning_lines.append("  - (배정자 없음)")

            morning_lines.append("\n🚗 2종 자동 (오전)")
            for name, car, note in morning_2jong_map:
                morning_lines.append(f"  - {name} → {car if car else '-'} {note}")

            # --- 오후 배정 로직 ---
            
            # 오후 열쇠 (오전과 동일)
            afternoon_key = today_key
            last_gy = gy2 if gy2 else (gy1 if gy1 else prev_gyoyang5)
            last_sudong = sudong_assigned[-1] if sudong_assigned else prev_sudong

            # 오후 교양 (3, 4, 5교시)
            aft_gy_candidates = []
            current_gy = last_gy
            
            for _ in range(len(gyoyang_order) * 2):
                next_cand = next_in_cycle(current_gy, gyoyang_order)
                current_gy = next_cand

                if next_cand in present_set_afternoon and next_cand not in computer_names:
                     if next_cand not in aft_gy_candidates:
                        aft_gy_candidates.append(next_cand)
                
                if len(aft_gy_candidates) >= 3: 
                    break
            
            gy3 = aft_gy_candidates[0] if len(aft_gy_candidates) >= 1 else None
            gy4 = aft_gy_candidates[1] if len(aft_gy_candidates) >= 2 else None
            gy5 = aft_gy_candidates[2] if len(aft_gy_candidates) >= 3 else None

            # 오후 1종 (1명)
            aft_sudong = None
            current_sudong = last_sudong
            for _ in range(len(sudong_order) * 2):
                next_cand = next_in_cycle(current_sudong, sudong_order)
                current_sudong = next_cand
                if next_cand in present_set_afternoon:
                    aft_sudong = next_cand
                    break 

            # 오후 2종
            aft_2jong = [p for p in afternoon_list if p != aft_sudong]
            aft_2jong_map = []
            for name in aft_2jong:
                car = veh2.get(name, "")
                note = "(정비중)" if car and car in repair_list else ""
                aft_2jong_map.append((name, car, note))

            # --- 최종 결과 표시 ---
            st.markdown("---")
            st.markdown("## 🏁 최종 배정 결과 (텍스트)")
            
            res_col1, res_col2 = st.columns(2)
            with res_col1:
                morning_result_text = "\n".join(morning_lines)
                st.text_area("오전 결과", morning_result_text, height=400, key="final_morning_result")
            
            with res_col2:
                afternoon_result_text = "\n".join(afternoon_lines)
                st.text_area("오후 결과", afternoon_result_text, height=400, key="final_afternoon_result")

            # 다운로드 버튼
            all_text = f"== {st.session_state.date_str} 오전 ==\n" + morning_result_text + \
                       f"\n\n== {st.session_state.date_str} 오후 ==\n" + afternoon_result_text
            
            st.download_button(
                "결과 텍스트 다운로드 (.txt)", 
                data=all_text.encode('utf-8-sig'), # 한글 깨짐 방지
                file_name=f"근무배정결과_{selected_date.strftime('%Y%m%d')}.txt", 
                mime="text/plain",
                key="download_button"
            )

            # 전일 근무자 정보 저장
            st.markdown("---")
            if st.checkbox("이 결과를 '전일 기준'으로 저장 (다음 실행 시 자동 로드)", value=True, key="save_prev_day_checkbox"):
                today_record = {
                    "열쇠": afternoon_key,
                    # 5교시가 없으면 4교시, 4교시도 없으면 3교시, 그마저도 없으면 이전 5교시 (혹은 빈값)
                    "교양_5교시": gy5 if gy5 else (gy4 if gy4 else (gy3 if gy3 else prev_gyoyang5)),
                    "1종수동": aft_sudong if aft_sudong else last_sudong
                }
                try:
                    with open(PREV_DAY_FILE, "w", encoding="utf-8") as f:
                        json.dump(today_record, f, ensure_ascii=False, indent=2)
                    st.success(f"`{PREV_DAY_FILE}`에 저장했습니다. 다음 실행 시 자동으로 로드됩니다.")
                except Exception as e:
                    st.error(f"파일 저장 실패: {e}")

else:
    st.info("⬆️ 상단에서 오전/오후 근무표 이미지를 업로드한 뒤 '① 이미지 분석' 버튼을 눌러주세요.")
