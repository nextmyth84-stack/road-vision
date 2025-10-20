# app.py
import streamlit as st
from google.cloud import vision
from google.oauth2 import service_account
import re
import json
import os
from io import BytesIO
# fuzzywuzzy 라이브러리 추가
from fuzzywuzzy import fuzz

st.set_page_config(page_title="근무표 자동 배정 (한글 OCR 버전)", layout="wide")

st.title("🚦 근무표 자동 배정 (Google Vision OCR + 한글 텍스트 출력)")

########################################################################
# 1) Google Vision API 인증 설정
########################################################################
try:
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
def get_text_bounds_fuzzy(all_texts, target_description, threshold=80):
    """
    OCR 결과 리스트(all_texts)에서 특정 텍스트를 fuzzy matching으로 찾아서
    그 텍스트의 bounding box(위치 정보)를 반환합니다.
    """
    best_match_score = -1
    best_match_text = None
    best_match_box = None

    # all_texts[0]은 전체 텍스트이므로, 개별 단어들(all_texts[1:])만 탐색
    for text_annotation in all_texts[1:]:
        detected_text = text_annotation.description

        # 문자열 유사도 계산
        score_ratio = fuzz.ratio(detected_text, target_description)
        score_partial = fuzz.partial_ratio(detected_text, target_description)
        current_score = max(score_ratio, score_partial)

        # threshold 이상인 가장 유사한 텍스트 선택
        if current_score > best_match_score and current_score >= threshold:
            best_match_score = current_score
            best_match_text = detected_text
            best_match_box = text_annotation.bounding_poly

    # 디버깅용 정보 출력
    if best_match_box:
        st.info(f"'{target_description}'와 가장 유사한 텍스트 '{best_match_text}' (유사도: {best_match_score}) 를 찾았습니다.")
    else:
        st.warning(f"'{target_description}'와 유사한 텍스트를 찾지 못했습니다. (임계값: {threshold})")

    return best_match_box



# --- OCR 처리 후 "라인 보존 방식"으로 이름 후보 리스트 생성 ---
########################################################################
# 도로주행 OCR 처리 함수 (오전/오후 공용)
########################################################################

def extract_doro_juhaeng_workers(file_content):
    """
    도로주행 표 이미지 파일(binary)을 받아 OCR 처리 후
    이름 후보를 추출하고, 사용자가 시작~끝 이름을 선택해 확정하는 함수.
    반환: (근무자리스트, OCR원문, 오류메시지)
    """
    try:
        # OCR 수행
        full_text = ocr_get_fulltext(file_content)
        if not full_text:
            return [], "(OCR 결과 없음)", None
    except Exception as e:
        return [], "", str(e)

    # OCR 결과에서 이름 후보 추출 (줄 순서 보존)
    all_names = extract_names_preserve_order(full_text)

    # OCR 원문 보기
    with st.expander("📄 OCR 원문 보기", expanded=False):
        st.text_area("OCR 원문", full_text, height=200)

    if not all_names:
        st.warning("OCR에서 이름 후보를 찾지 못했습니다. 수동 입력이 필요할 수 있습니다.")
        return [], full_text, None

    st.markdown("### 🔍 추출된 이름 후보 (위→아래 순서)")
    numbered = [f"{i+1}. {n}" for i, n in enumerate(all_names)]
    st.text_area("이름 후보", "\n".join(numbered), height=180)

    # --- 이름 범위 선택 ---
    with st.form(key=f"select_range_form_{hash(file_content)}"):
        c1, c2 = st.columns(2)
        with c1:
            start_choice = st.selectbox("시작 이름", options=all_names, index=0)
        with c2:
            end_choice = st.selectbox("끝 이름", options=all_names, index=len(all_names)-1)
        ok = st.form_submit_button("이 구간만 확정")

    selected_workers = []
    if ok:
        try:
            s_idx = all_names.index(start_choice)
            e_idx = all_names.index(end_choice)
            if s_idx > e_idx:
                st.error("⚠️ 시작이 끝보다 뒤에 있습니다.")
            else:
                selected_workers = all_names[s_idx:e_idx+1]
                st.success(f"✅ 선택 구간: {start_choice} → {end_choice} ({len(selected_workers)}명)")
                st.write(selected_workers)
        except Exception as e:
            st.error(f"선택 오류: {e}")

    # 선택된 게 없으면 기본 전체 반환
    if not selected_workers:
        selected_workers = all_names

    return selected_workers, full_text, None


def extract_names_preserve_order(full_text):
    """
    full_text: OCR이 반환한 전체 문자열 (줄바꿈 보존)
    반환: 표의 위->아래, 왼쪽->오른쪽 순서로 추출된 이름 리스트 (중복 제거, 순서 유지)
    """
    if not full_text:
        return []

    # 먼저 '도로주행' 이후 텍스트만 사용 (없으면 전체 사용)
    m = re.search(r"도로\s*주행(.*)", full_text, re.DOTALL)
    target_text = m.group(1) if m else full_text

    lines = [ln.strip() for ln in target_text.splitlines() if ln.strip()]
    all_names = []
    name_pattern = re.compile(r"[가-힣]{2,4}")

    for line in lines:
        # 같은 줄에서 여러 이름이 붙어 있을 수 있으니 순서대로 찾는다.
        found = name_pattern.findall(line)
        for name in found:
            # 필터링: 불필요 단어는 걸러냄
            if name in ("성명","교육","차량","오전","오후","정비","합","불"):
                continue
            all_names.append(name)

    # 중복 제거(순서 유지)
    seen = set()
    ordered = []
    for n in all_names:
        if n not in seen:
            seen.add(n)
            ordered.append(n)
    return ordered

# --- OCR 호출 함수(단순화 예시) ---
def ocr_get_fulltext(file_content):
    if not file_content:
        return ""
    image = vision.Image(content=file_content)
    response = client.text_detection(image=image)
    if response.error.message:
        raise Exception(response.error.message)
    return response.text_annotations[0].description if response.text_annotations else ""

# === 사용 예시: OCR 수행 후 '선택 폼'으로 범위 지정 ===
# (이 코드는 앱의 이미지 분석 후 표시되는 부분에 넣으세요)

full_text = ""  # OCR 전체 원문 (예: morning_raw_text)
try:
    full_text = ocr_get_fulltext(morning_file.getvalue()) if morning_file else ""
except Exception as e:
    st.error(f"OCR 오류: {e}")
    full_text = ""

all_names = extract_names_preserve_order(full_text)

st.expander("OCR 원문 보기 (참고)", expanded=False)
with st.expander("OCR 원문 보기 (참고)"):
    st.text_area("OCR 원문", full_text, height=200)

if not all_names:
    st.warning("OCR에서 이름 후보를 찾지 못했습니다. OCR 원문을 확인하거나 수동으로 입력하세요.")
else:
    st.markdown("### 추출된 이름 후보 (표의 위→아래 순서로 나열됨)")
    # 인덱스와 함께 보여주기
    numbered = [f"{i+1}. {n}" for i, n in enumerate(all_names)]
    st.text_area("이름 후보 (순서)", "\n".join(numbered), height=200)

    # --- 폼으로 시작/끝 선택 및 제출(동시에 처리) ---
    with st.form(key="select_range_form"):
        col1, col2 = st.columns(2)
        with col1:
            start_choice = st.selectbox("시작 이름 (첫번째)", options=all_names, index=0, key="start_select")
        with col2:
            end_choice = st.selectbox("끝 이름 (마지막)", options=all_names, index=len(all_names)-1, key="end_select")
        submit_btn = st.form_submit_button("구간 선택 적용")

    if submit_btn:
        start_idx = all_names.index(start_choice)
        end_idx = all_names.index(end_choice)
        if start_idx > end_idx:
            st.error("시작이 끝보다 뒤에 있습니다. 올바른 순서를 선택하세요.")
            selected_workers = []
        else:
            selected_workers = all_names[start_idx:end_idx+1]
            st.success(f"선택된 구간: {start_choice} → {end_choice} ({len(selected_workers)}명)")
            st.write(selected_workers)
            # selected_workers를 이후 배정 로직에 사용 (예: morning_list_final에 채우기)
            # 예: st.session_state['morning_workers_selected'] = selected_workers





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
