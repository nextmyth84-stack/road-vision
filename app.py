# app.py
import streamlit as st
from google.cloud import vision
from google.oauth2 import service_account
from PIL import Image
import json
import re
import os
from io import BytesIO

# -----------------------------
# 페이지 설정 & CSS (모바일 최적화)
# -----------------------------
st.set_page_config(page_title="도로주행 근무자동배정 (통합본)", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
    <style>
        .stApp { font-family: "Apple SD Gothic Neo", "Nanum Gothic", "Malgun Gothic", sans-serif; }
        textarea, input, select, button { font-size: 16px !important; }
        .big-button .stButton>button { height:56px !important; font-size:18px !important; }
        .stTextArea textarea { font-size:15px !important; }
        @media (max-width: 600px) {
            .css-1offfwp { padding: 0.5rem 1rem; } /* adjust main padding on mobile */
        }
    </style>
""", unsafe_allow_html=True)

st.title("🚦 도로주행 근무자동배정 — 완전본 (app.py)")

# -----------------------------
# 상수 / 파일
# -----------------------------
PREV_DAY_FILE = "전일근무.json"

# -----------------------------
# Vision API 인증
# -----------------------------
def init_vision_client():
    try:
        # Expect full service account JSON content stored in Streamlit secrets:
        # st.secrets["general"]["GOOGLE_APPLICATION_CREDENTIALS"]
        cred_info = json.loads(st.secrets["general"]["GOOGLE_APPLICATION_CREDENTIALS"])
        creds = service_account.Credentials.from_service_account_info(cred_info)
        client = vision.ImageAnnotatorClient(credentials=creds)
        return client
    except Exception as e:
        st.error("⚠️ Google Vision 인증 실패: " + str(e))
        st.stop()

client = init_vision_client()

# -----------------------------
# 유틸: 텍스트 정제 / 이름 추출 / 순환 계산 등
# -----------------------------
def clean_ocr_text(text):
    """괄호 제거, 영어/숫자/특수 제거, 공백 정리"""
    if not text:
        return ""
    text = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", text)   # 괄호 안 내용 제거
    text = re.sub(r"[A-Za-z0-9\-\=\+\*\/\\:;,.·••]+", " ", text)  # 영어/숫자/특수
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def extract_korean_names_from_text(text, min_len=2, max_len=5):
    """한글 이름 후보 추출(2~5글자 허용), 불용어 제거, 순서 유지"""
    if not text:
        return []
    # 후보: 연속된 한글 2~5 글자
    candidates = re.findall(r"[가-힣]{%d,%d}" % (min_len, max_len), text)
    # 제외어 확장
    exclude = {
        "성명","교육","오전","오후","합","불","정비","시간","차량","확정",
        "합격","불합격","근무","휴무","대기","번호","감독","코스","도로","주행",
        "응시자","수험생","검정원","월","일","명단","배정","시험","기능","도로주행",
        "전산병행","전산"
    }
    ordered = []
    seen = set()
    for w in candidates:
        if w in exclude: 
            continue
        if w not in seen:
            seen.add(w)
            ordered.append(w)
    return ordered

def next_in_cycle(current, cycle_list):
    if not cycle_list:
        return None
    if not current:
        return cycle_list[0]
    try:
        idx = cycle_list.index(current)
        return cycle_list[(idx + 1) % len(cycle_list)]
    except ValueError:
        return cycle_list[0]

def next_valid_after(start_item, item_list, valid_set):
    if not item_list:
        return None
    if start_item in item_list:
        start_idx = item_list.index(start_item)
    else:
        start_idx = -1
    for i in range(1, len(item_list)+1):
        cand = item_list[(start_idx + i) % len(item_list)]
        if cand in valid_set:
            return cand
    return None

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

# -----------------------------
# 사이드바: 순번표 / 차량 매핑 / 옵션 / 전일 자동 로드
# -----------------------------
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

# 전일 자동 로드
def load_previous_day_data():
    if os.path.exists(PREV_DAY_FILE):
        try:
            with open(PREV_DAY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

prev_data = load_previous_day_data()

st.sidebar.markdown("---")
st.sidebar.header("전일(기준) 입력 — 자동/수동")
prev_key = st.sidebar.text_input("전일 열쇠", value=prev_data.get("열쇠",""))
prev_gyoyang5 = st.sidebar.text_input("전일 5교시 교양", value=prev_data.get("교양_5교시",""))
prev_sudong = st.sidebar.text_input("전일 1종수동", value=prev_data.get("1종수동",""))

st.sidebar.markdown("---")
st.sidebar.header("옵션")
sudong_count = st.sidebar.radio("1종 수동 인원수", [1,2], index=0)
computer_names_input = st.sidebar.text_input("전산병행자 이름 (쉼표로 구분)", value="")
computer_names = [n.strip() for n in computer_names_input.split(",") if n.strip()]
repair_cars = st.sidebar.text_input("정비중 차량 (쉼표로 구분, 예: 12호,6호)", value="")

# parse orders and vehicles
key_order = parse_list(key_order_text)
gyoyang_order = parse_list(gyoyang_order_text)
sudong_order = parse_list(sudong_order_text)
veh1 = parse_vehicle_map(cha1_text)
veh2 = parse_vehicle_map(cha2_text)

# -----------------------------
# OCR 호출: Vision text_detection (전체 텍스트)
# -----------------------------
def ocr_full_text_from_image_bytes(image_bytes):
    image = vision.Image(content=image_bytes)
    response = client.text_detection(image=image)
    if response.error.message:
        raise Exception(response.error.message)
    return response.text_annotations[0].description if response.text_annotations else ""

# -----------------------------
# UI: 이미지 업로드 (오전/오후)
# -----------------------------
st.markdown("## ① 오전/오후 근무표 이미지 업로드 (원본 이미지를 권장합니다)")
col1, col2 = st.columns(2)
with col1:
    morning_file = st.file_uploader("오전 근무표 이미지 업로드", type=["png","jpg","jpeg"], key="morning")
with col2:
    afternoon_file = st.file_uploader("오후 근무표 이미지 업로드", type=["png","jpg","jpeg"], key="afternoon")

st.markdown("**설명:** OCR로 먼저 근무자 후보를 추출합니다. 추출 후 '시작 이름'과 '끝 이름'을 선택하여 도로주행 근무자 목록을 확정하세요.")

# -----------------------------
# OCR 실행 버튼 — 추출 및 세션 저장
# -----------------------------
if st.button("① 이미지 분석 및 근무자 추출"):
    if not morning_file and not afternoon_file:
        st.warning("오전 또는 오후 근무표 이미지를 업로드하세요.")
    else:
        # morning
        if morning_file:
            try:
                raw = ocr_full_text_from_image_bytes(morning_file.getvalue())
                cleaned = clean_ocr_text(raw)
                names = extract_korean_names_from_text(cleaned)
                st.session_state.morning_raw_text = raw
                st.session_state.morning_names = names
                st.success(f"오전 OCR 완료 — {len(names)}명 후보 인식")
            except Exception as e:
                st.error("오전 OCR 오류: " + str(e))
                st.session_state.morning_names = []
                st.session_state.morning_raw_text = ""
        else:
            st.session_state.morning_names = []
            st.session_state.morning_raw_text = ""

        # afternoon
        if afternoon_file:
            try:
                raw = ocr_full_text_from_image_bytes(afternoon_file.getvalue())
                cleaned = clean_ocr_text(raw)
                names = extract_korean_names_from_text(cleaned)
                st.session_state.afternoon_raw_text = raw
                st.session_state.afternoon_names = names
                st.success(f"오후 OCR 완료 — {len(names)}명 후보 인식")
            except Exception as e:
                st.error("오후 OCR 오류: " + str(e))
                st.session_state.afternoon_names = []
                st.session_state.afternoon_raw_text = ""
        else:
            st.session_state.afternoon_names = []
            st.session_state.afternoon_raw_text = ""

        # reset prior selections
        for k in ["selected_morning","selected_afternoon"]:
            if k in st.session_state:
                del st.session_state[k]
        st.experimental_rerun()

# -----------------------------
# ② 선택 UI: 인식 후보 -> 시작/끝 선택(구간)
# -----------------------------
def selection_ui_for_list(names, label):
    """시작/끝 selectboxes로 구간 정함 (모바일 호환)"""
    if not names:
        st.info(f"{label} 이미지에서 이름 후보가 없습니다.")
        return []
    st.markdown(f"### {label} 인식 후보 (위→아래 순서)")
    # show numbered list
    numbered = [f"{i+1}. {n}" for i,n in enumerate(names)]
    st.text_area(f"{label} 후보 목록 (확인용)", "\n".join(numbered), height=180)
    col1, col2, col3 = st.columns([1,1,1])
    with col1:
        start = st.selectbox(f"{label} 시작 이름 선택", options=["(선택)"] + names, key=f"start_{label}")
    with col2:
        end = st.selectbox(f"{label} 끝 이름 선택", options=["(선택)"] + names, key=f"end_{label}")
    with col3:
        if st.button(f"{label} 구간 적용", key=f"apply_{label}"):
            if start == "(선택)" or end == "(선택)":
                st.warning("시작/끝 모두 선택해야 합니다.")
                return []
            s_idx = names.index(start)
            e_idx = names.index(end)
            if s_idx <= e_idx:
                sel = names[s_idx:e_idx+1]
            else:
                sel = names[e_idx:s_idx+1]
            st.success(f"{label} 구간 선택: {sel[0]} → {sel[-1]} ({len(sel)}명)")
            return sel
    # if not applied, return empty list (user can manually copy from text area if needed)
    return []

st.markdown("---")
st.markdown("## ② OCR 후보 확인 및 도로주행 근무자 확정 (시작/끝 선택 후 '구간 적용')")

# morning selection UI
morning_selected = []
if st.session_state.get("morning_names") is not None:
    st.subheader("🌅 오전")
    morning_selected = selection_ui_for_list(st.session_state.get("morning_names", []), "오전")
    if morning_selected:
        st.session_state.selected_morning = morning_selected

# afternoon selection UI
afternoon_selected = []
if st.session_state.get("afternoon_names") is not None:
    st.subheader("🌇 오후")
    afternoon_selected = selection_ui_for_list(st.session_state.get("afternoon_names", []), "오후")
    if afternoon_selected:
        st.session_state.selected_afternoon = afternoon_selected

# allow manual edits if needed
st.markdown("---")
st.markdown("### (선택 사항) 수동 편집 — 자동 인식/선택이 잘못된 경우 직접 수정하세요")
colm, cola = st.columns(2)
with colm:
    morning_manual = st.text_area("오전 근무자 최종 (한 줄에 하나씩)", value="\n".join(st.session_state.get("selected_morning", [])), height=160, key="morning_manual")
with cola:
    afternoon_manual = st.text_area("오후 근무자 최종 (한 줄에 하나씩)", value="\n".join(st.session_state.get("selected_afternoon", [])), height=160, key="afternoon_manual")

# parse final lists
morning_list = [x.strip() for x in morning_manual.splitlines() if x.strip()]
afternoon_list = [x.strip() for x in afternoon_manual.splitlines() if x.strip()]

# -----------------------------
# ③ 최종 배정 생성 (순번로직 / 차량배정)
# -----------------------------
st.markdown("---")
st.markdown("## ③ 최종 근무 배정 생성")
if st.button("② 최종 근무 배정 생성", type="primary", key="generate_assignment_button"):
    with st.spinner("배정 로직을 계산 중입니다..."):
        # present sets
        present_set_morning = set(morning_list)
        present_set_afternoon = set(afternoon_list)
        repair_list = [x.strip() for x in repair_cars.split(",") if x.strip()]

        # --- 오전 배정 ---
        today_key = next_in_cycle(prev_key, key_order)

        # 교양 오전 (2명) — start from next after prev_gyoyang5
        gy_start = next_in_cycle(prev_gyoyang5, gyoyang_order)
        gy_candidates = []
        cur = gy_start
        for _ in range(len(gyoyang_order) * 2):
            if cur in present_set_morning and cur not in computer_names:
                if cur not in gy_candidates:
                    gy_candidates.append(cur)
            if len(gy_candidates) >= 2:
                break
            cur = next_in_cycle(cur, gyoyang_order)
        gy1 = gy_candidates[0] if len(gy_candidates) >=1 else None
        gy2 = gy_candidates[1] if len(gy_candidates) >=2 else None

        # 1종 수동 오전 (sudong_count people) starting after prev_sudong
        sudong_assigned = []
        cur_s = prev_sudong if prev_sudong else sudong_order[0]
        # iterate and pick next present(s)
        for _ in range(len(sudong_order) * 2):
            cand = next_in_cycle(cur_s, sudong_order)
            cur_s = cand
            if cand in present_set_morning and cand not in sudong_assigned:
                sudong_assigned.append(cand)
            if len(sudong_assigned) >= sudong_count:
                break

        # morning 2종 automatic list (present minus sudong_assigned)
        morning_2jong = [p for p in morning_list if p not in sudong_assigned]
        morning_2jong_map = []
        for name in morning_2jong:
            car = veh2.get(name, "")
            note = "(정비중)" if car and car in repair_list else ""
            morning_2jong_map.append((name, car, note))

        # Build morning output
        morning_lines = []
        morning_lines.append(f"📅 {st.session_state.get('date', '') if 'date' in st.session_state else ''} 오전 근무 배정 결과")
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

        # --- 오후 배정 ---
        afternoon_key = today_key
        last_gy = gy2 if gy2 else (gy1 if gy1 else prev_gyoyang5)
        last_sudong = sudong_assigned[-1] if sudong_assigned else prev_sudong

        # afternoon 교양 3,4,5 (start after last_gy)
        aft_gy_candidates = []
        cur_g = last_gy if last_gy else gyoyang_order[0]
        for _ in range(len(gyoyang_order)*2):
            cur_g = next_in_cycle(cur_g, gyoyang_order)
            if cur_g in present_set_afternoon and cur_g not in computer_names:
                if cur_g not in aft_gy_candidates:
                    aft_gy_candidates.append(cur_g)
            if len(aft_gy_candidates) >= 3:
                break
        gy3 = aft_gy_candidates[0] if len(aft_gy_candidates) >=1 else None
        gy4 = aft_gy_candidates[1] if len(aft_gy_candidates) >=2 else None
        gy5 = aft_gy_candidates[2] if len(aft_gy_candidates) >=3 else None

        # afternoon 1종 (single)
        aft_sudong = None
        cur_s2 = last_sudong if last_sudong else sudong_order[0]
        for _ in range(len(sudong_order)*2):
            cand = next_in_cycle(cur_s2, sudong_order)
            cur_s2 = cand
            if cand in present_set_afternoon:
                aft_sudong = cand
                break

        # afternoon 2종
        aft_2jong = [p for p in afternoon_list if p != aft_sudong]
        aft_2jong_map = []
        for name in aft_2jong:
            car = veh2.get(name, "")
            note = "(정비중)" if car and car in repair_list else ""
            aft_2jong_map.append((name, car, note))

        # Build afternoon output
        afternoon_lines = []
        afternoon_lines.append(f"📅 {st.session_state.get('date', '') if 'date' in st.session_state else ''} 오후 근무 배정 결과")
        afternoon_lines.append("="*30)
        afternoon_lines.append(f"🔑 열쇠: {afternoon_key}")
        afternoon_lines.append("\n🎓 교양 (오후)")
        afternoon_lines.append(f"  - 3교시: {gy3 if gy3 else '-'}")
        afternoon_lines.append(f"  - 4교시: {gy4 if gy4 else '-'}")
        afternoon_lines.append(f"  - 5교시: {gy5 if gy5 else '-'}")
        afternoon_lines.append("\n🚛 1종 수동 (오후)")
        if aft_sudong:
            car = veh1.get(aft_sudong, "")
            afternoon_lines.append(f"  - 1종(오후): {aft_sudong}" + (f" ({car})" if car else ""))
        else:
            afternoon_lines.append("  - (배정자 없음)")
        afternoon_lines.append("\n🚗 2종 자동 (오후)")
        for name, car, note in aft_2jong_map:
            afternoon_lines.append(f"  - {name} → {car if car else '-'} {note}")

        # -----------------------------
        # 표시 & 다운로드
        # -----------------------------
        st.markdown("---")
        st.markdown("## 🏁 최종 배정 결과 (텍스트)")
        res_col1, res_col2 = st.columns(2)
        morning_result_text = "\n".join(morning_lines)
        afternoon_result_text = "\n".join(afternoon_lines)
        with res_col1:
            st.text_area("오전 결과", morning_result_text, height=420)
        with res_col2:
            st.text_area("오후 결과", afternoon_result_text, height=420)

        all_text = f"== 오전 ==\n{morning_result_text}\n\n== 오후 ==\n{afternoon_result_text}"
        st.download_button("결과 텍스트 다운로드 (.txt)", data=all_text.encode('utf-8-sig'),
                           file_name=f"근무배정결과.txt", mime="text/plain")

        # 저장(전일 기준)
        if st.checkbox("이 결과를 '전일 기준'으로 저장 (다음 실행 시 자동 로드)", value=True):
            today_record = {
                "열쇠": afternoon_key,
                "교양_5교시": gy5 if gy5 else (gy4 if gy4 else (gy3 if gy3 else prev_gyoyang5)),
                "1종수동": aft_sudong if aft_sudong else last_sudong
            }
            try:
                with open(PREV_DAY_FILE, "w", encoding="utf-8") as f:
                    json.dump(today_record, f, ensure_ascii=False, indent=2)
                st.success(f"`{PREV_DAY_FILE}`에 저장했습니다. 다음 실행 시 자동 로드됩니다.")
            except Exception as e:
                st.error("전일 저장 실패: " + str(e))

# -----------------------------
# 하단 도움말
# -----------------------------
st.markdown("---")
st.info("사용법 요약:\n\n"
        "1) 오전/오후 근무표 이미지를 각각 업로드\n"
        "2) '이미지 분석 및 근무자 추출' 버튼 클릭 → 인식 후보 확인\n"
        "3) 각 후보에서 시작/끝을 선택하고 '구간 적용' 클릭 → 도로주행 근무자 목록 확정\n"
        "4) 필요 시 수동 편집 후 '최종 근무 배정 생성' 클릭하여 배정 결과 확인 및 저장\n\n"
        "옵션: 전산병행자, 정비중 차량, 1종수동 인원수 등을 사이드바에서 설정하세요.")

