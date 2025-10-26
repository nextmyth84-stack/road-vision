# =====================================
# app.py — 도로주행 근무 자동 배정 v7.44 (완전본)
# =====================================
import streamlit as st
from openai import OpenAI
import base64, re, json, os, difflib, random

st.markdown("""
<h3 style='text-align:center; color:#1e3a8a;'> 도로주행 근무 자동 배정 </h3>
<p style='text-align:center; font-size:6px; color:#64748b; margin-top:-6px;'>
    Developed by <b>wook</b>
</p>
""", unsafe_allow_html=True)

# -----------------------
# OpenAI API 연결
# -----------------------
try:
    client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
except Exception:
    st.error("⚠️ OPENAI_API_KEY 설정 필요")
    st.stop()
MODEL_NAME = "gpt-4o"

# -----------------------
# JSON 유틸
# -----------------------
def load_json(file, default=None):
    if not os.path.exists(file):
        return default
    try:
        with open(file, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def save_json(file, data):
    try:
        with open(file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"저장 실패: {e}")

# -----------------------
# 이름/차량 처리
# -----------------------
def normalize_name(s):
    return re.sub(r"[^가-힣]", "", re.sub(r"\(.*?\)", "", s or ""))

def get_vehicle(name, veh_map):
    nkey = normalize_name(name)
    for car, nm in veh_map.items():
        if normalize_name(nm) == nkey:
            return car
    return ""

def mark_car(car, repair_cars):
    return f"{car}{' (정비)' if car in repair_cars else ''}" if car else ""

def pick_next_from_cycle(cycle, last, allowed_norms: set):
    if not cycle:
        return None
    cycle_norm = [normalize_name(x) for x in cycle]
    last_norm = normalize_name(last)
    start = (cycle_norm.index(last_norm) + 1) % len(cycle) if last_norm in cycle_norm else 0
    for i in range(len(cycle) * 2):
        cand = cycle[(start + i) % len(cycle)]
        if normalize_name(cand) in allowed_norms:
            return cand
    return None

def correct_name_v2(name, employee_list, cutoff=0.6):
    name_norm = normalize_name(name)
    if not name_norm:
        return name
    best, best_score = None, 0.0
    for cand in employee_list:
        score = difflib.SequenceMatcher(None, normalize_name(cand), name_norm).ratio()
        if score > best_score:
            best_score, best = score, cand
    return best if best and best_score >= cutoff else name
# -----------------------
# JSON 기반 순번 / 차량 / 근무자 관리 (+ 1종자동 순번)
# -----------------------
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
files = {
    "열쇠": "열쇠순번.json",
    "교양": "교양순번.json",
    "1종": "1종순번.json",
    "veh1": "1종차량표.json",
    "veh2": "2종차량표.json",
    "employees": "전체근무자.json",
    "1종자동": "1종자동순번.json",  # NEW
}
for k, v in files.items():
    files[k] = os.path.join(DATA_DIR, v)

default_data = {
    "열쇠": ["권한솔","김남균","김면정","김성연","김지은","안유미","윤여헌","윤원실","이나래","이호석","조윤영","조정래"],
    "교양": ["권한솔","김남균","김면정","김병욱","김성연","김주현","김지은","안유미","이호석","조정래"],
    "1종":  ["권한솔","김남균","김성연","김주현","이호석","조정래"],
    "veh1": {"2호":"조정래","5호":"권한솔","7호":"김남균","8호":"이호석","9호":"김주현","10호":"김성연"},
    "veh2": {"4호":"김남균","5호":"김병욱","6호":"김지은","12호":"안유미","14호":"김면정","15호":"이호석","17호":"김성연","18호":"권한솔","19호":"김주현","22호":"조정래"},
    "employees": ["권한솔","김남균","김면정","김성연","김지은","안유미","윤여헌","윤원실","이나래","이호석","조윤영","조정래","김병욱","김주현"],
    "1종자동": ["21호","22호","23호","24호"],  # NEW
}
for k, v in files.items():
    if not os.path.exists(v):
        try:
            with open(v, "w", encoding="utf-8") as f:
                json.dump(default_data[k], f, ensure_ascii=False, indent=2)
        except Exception as e:
            st.error(f"{v} 초기화 실패: {e}")

# 로드
key_order    = load_json(files["열쇠"])
gyoyang_order= load_json(files["교양"])
sudong_order = load_json(files["1종"])
veh1_map     = load_json(files["veh1"])
veh2_map     = load_json(files["veh2"])
employee_list= load_json(files["employees"])
auto1_order  = load_json(files["1종자동"])  # NEW

# -----------------------
# 전일 근무자 로드 (1종자동 포함)
# -----------------------
PREV_FILE = "전일근무.json"
def load_prev_data():
    if os.path.exists(PREV_FILE):
        try:
            with open(PREV_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"열쇠":"", "교양_5교시":"", "1종수동":"", "1종자동":""}  # NEW key

prev_data = load_prev_data()
prev_key      = prev_data.get("열쇠","")
prev_gyoyang5 = prev_data.get("교양_5교시","")
prev_sudong   = prev_data.get("1종수동","")
prev_auto1    = prev_data.get("1종자동","")  # NEW

# -----------------------
# 사이드바 스타일
# -----------------------
st.sidebar.markdown("""
<style>
section[data-testid="stSidebar"] {
    background-color: #f8fafc;
    padding: 10px;
    border-right: 1px solid #e5e7eb;
}
.streamlit-expanderHeader { font-weight:700 !important; color:#1e3a8a !important; font-size:15px !important; }
textarea, input { font-size:14px !important; }
div.stButton > button {
    background-color:#2563eb; color:white; border:none; border-radius:8px;
    padding:6px 12px; margin-top:6px; font-weight:600;
}
div.stButton > button:hover { background-color:#1d4ed8; }
.sidebar-subtitle { font-weight:600; color:#334155; margin-top:10px; margin-bottom:4px; }
</style>
""", unsafe_allow_html=True)

st.sidebar.markdown("<h3 style='text-align:center; color:#1e3a8a;'>📂 데이터 관리</h3>", unsafe_allow_html=True)

# -----------------------
# 🗓 전일 근무자 (수정 가능)
# -----------------------
with st.sidebar.expander("🗓 전일 근무자", expanded=True):
    prev_key      = st.text_input("🔑 전일 열쇠 담당", prev_key)
    prev_gyoyang5 = st.text_input("🧑‍🏫 전일 교양(5교시)", prev_gyoyang5)
    prev_sudong   = st.text_input("🚚 전일 1종 수동", prev_sudong)
    prev_auto1    = st.text_input("🚗 전일 1종 자동", prev_auto1)  # NEW

    if st.button("💾 전일 근무자 저장"):
        save_json(PREV_FILE, {
            "열쇠": prev_key,
            "교양_5교시": prev_gyoyang5,
            "1종수동": prev_sudong,
            "1종자동": prev_auto1,  # NEW
        })
        st.sidebar.success("전일근무.json 저장 완료 ✅")

# -----------------------
# 🔢 순번표 / 차량표 / 근무자
# -----------------------
with st.sidebar.expander("🔢 순번표 관리", expanded=False):
    st.markdown("<div class='sidebar-subtitle'>열쇠 순번</div>", unsafe_allow_html=True)
    t1 = st.text_area("", "\n".join(key_order), height=140)

    st.markdown("<div class='sidebar-subtitle'>교양 순번</div>", unsafe_allow_html=True)
    t2 = st.text_area("", "\n".join(gyoyang_order), height=140)

    st.markdown("<div class='sidebar-subtitle'>1종 수동 순번</div>", unsafe_allow_html=True)
    t3 = st.text_area("", "\n".join(sudong_order), height=120)

    st.markdown("<div class='sidebar-subtitle'>1종 자동 순번</div>", unsafe_allow_html=True)
    t4 = st.text_area("", "\n".join(auto1_order or []), height=100)

    if st.button("💾 순번표 저장"):
        save_json(files["열쇠"], [x.strip() for x in t1.splitlines() if x.strip()])
        save_json(files["교양"], [x.strip() for x in t2.splitlines() if x.strip()])
        save_json(files["1종"], [x.strip() for x in t3.splitlines() if x.strip()])
        save_json(files["1종자동"], [x.strip() for x in (t4.splitlines() if t4 else []) if x.strip()])
        # 즉시 재로드
        key_order[:]     = load_json(files["열쇠"])
        gyoyang_order[:] = load_json(files["교양"])
        sudong_order[:]  = load_json(files["1종"])
        auto1_order[:]   = load_json(files["1종자동"])
        st.sidebar.success("순번표 저장 완료 ✅")

with st.sidebar.expander("🚘 차량 담당 관리", expanded=False):
    def _cars_to_text(m):  # car -> name
        return "\n".join([f"{car} {nm}" for car, nm in m.items()])

    st.markdown("<div class='sidebar-subtitle'>1종 수동 차량표</div>", unsafe_allow_html=True)
    tveh1 = st.text_area("", _cars_to_text(veh1_map), height=120)

    st.markdown("<div class='sidebar-subtitle'>2종 자동 차량표</div>", unsafe_allow_html=True)
    tveh2 = st.text_area("", _cars_to_text(veh2_map), height=150)

    if st.button("💾 차량표 저장"):
        veh1_new, veh2_new = {}, {}
        for line in tveh1.splitlines():
            p = line.strip().split()
            if len(p) >= 2:
                veh1_new[p[0]] = " ".join(p[1:])
        for line in tveh2.splitlines():
            p = line.strip().split()
            if len(p) >= 2:
                veh2_new[p[0]] = " ".join(p[1:])
        save_json(files["veh1"], veh1_new)
        save_json(files["veh2"], veh2_new)
        veh1_map = load_json(files["veh1"])
        veh2_map = load_json(files["veh2"])
        st.sidebar.success("차량표 저장 완료 ✅")

with st.sidebar.expander("🛠 정비 차량 (멀티선택)", expanded=False):
    veh1_choices = sorted(list(veh1_map.keys()))
    veh2_choices = sorted(list(veh2_map.keys()))
    auto1_choices = sorted(list(auto1_order or []))  # ex) ["21호","22호",...]

    repair_cars_1 = st.multiselect("1종 수동 정비 차량", options=veh1_choices, default=st.session_state.get("repair_cars_1", []))
    repair_cars_2 = st.multiselect("2종 자동 정비 차량", options=veh2_choices, default=st.session_state.get("repair_cars_2", []))
    repair_cars_auto1 = st.multiselect("1종 자동 정비 차량", options=auto1_choices, default=st.session_state.get("repair_cars_auto1", []))

    if st.button("🧰 정비 목록 적용"):
        st.session_state.repair_cars_1 = repair_cars_1
        st.session_state.repair_cars_2 = repair_cars_2
        st.session_state.repair_cars_auto1 = repair_cars_auto1
        st.sidebar.success("정비 목록이 적용되었습니다.")

with st.sidebar.expander("👥 전체 근무자", expanded=False):
    st.markdown("<div class='sidebar-subtitle'>근무자 목록</div>", unsafe_allow_html=True)
    t_emp = st.text_area("", "\n".join(employee_list), height=160)
    if st.button("💾 근무자 저장"):
        save_json(files["employees"], [x.strip() for x in t_emp.splitlines() if x.strip()])
        employee_list = load_json(files["employees"])
        st.sidebar.success("근무자 명단 저장 완료 ✅")

# -----------------------
# ⚙️ 추가 설정 (1종 수동 인원 수) — 컷오프 슬라이더 제거
# -----------------------
st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ 추가 설정")
sudong_count = st.sidebar.radio("1종 수동 인원 수", [1, 2], index=0)

# -----------------------
# 세션 최신화
# -----------------------
st.session_state.update({
    "key_order": key_order, "gyoyang_order": gyoyang_order, "sudong_order": sudong_order,
    "veh1": veh1_map, "veh2": veh2_map, "employee_list": employee_list,
    "auto1_order": auto1_order,
    "sudong_count": sudong_count,
    # 정비 멀티선택 결과
    "repair_cars_1": st.session_state.get("repair_cars_1", []),
    "repair_cars_2": st.session_state.get("repair_cars_2", []),
    "repair_cars_auto1": st.session_state.get("repair_cars_auto1", []),
})
# =====================================
# 🌅 오전 근무 탭
# =====================================
tab1, tab2 = st.tabs(["🌅 오전 근무", "🌇 오후 근무"])

with tab1:
    st.markdown("<h4 style='margin-top:6px;'>1️⃣ 오전 근무표 업로드 & OCR</h4>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        m_file = st.file_uploader("📸 오전 근무표 업로드", type=["png","jpg","jpeg"], key="m_upload")
    with col2:
        pass

    if st.button("오전 GPT 인식"):
        if not m_file:
            st.warning("오전 이미지를 업로드하세요.")
        else:
            with st.spinner("🧩 GPT 이미지 분석 중..."):
                names, course, excluded, early, late = gpt_extract(
                    m_file.read(), want_early=True, want_late=True, want_excluded=True
                )
                fixed = [correct_name_v2(n, st.session_state["employee_list"]) for n in names]
                excluded_fixed = [correct_name_v2(n, st.session_state["employee_list"]) for n in excluded]

                st.session_state.m_names_raw = fixed
                st.session_state.excluded_auto = excluded_fixed
                st.session_state.early_leave = early
                st.session_state.late_start = late
                st.success(f"오전 인식 완료 → 근무자 {len(fixed)}명, 제외자 {len(excluded_fixed)}명")

    excluded_text = st.text_area("🚫 근무 제외자", "\n".join(st.session_state.get("excluded_auto", [])), height=100)
    excluded_set = {normalize_name(x) for x in excluded_text.splitlines() if x.strip()}

    morning_text = st.text_area("🌅 오전 근무자", "\n".join(st.session_state.get("m_names_raw", [])), height=200)
    m_list = [x.strip() for x in morning_text.splitlines() if x.strip()]
    m_norms = {normalize_name(x) for x in m_list} - excluded_set

    if st.button("📋 오전 배정 생성"):
        try:
            veh1_map = st.session_state.get("veh1", {})
            veh2_map = st.session_state.get("veh2", {})
            repair_veh1 = st.session_state.get("repair_cars_1", [])
            repair_veh2 = st.session_state.get("repair_cars_2", [])

            lines = []

            # 🔑 열쇠 담당 순번
            today_key = pick_next_from_cycle(st.session_state["key_order"], prev_key, m_norms)
            if today_key:
                lines.append(f"열쇠: {today_key}")
                lines.append("")

            # 🚚 1종 수동
            sudong_order = st.session_state["sudong_order"]
            sudong_count = st.session_state["sudong_count"]
            sud_m = []
            for _ in range(sudong_count):
                pick = pick_next_from_cycle(sudong_order, prev_sudong, m_norms - {normalize_name(x) for x in sud_m})
                if pick:
                    sud_m.append(pick)
                    prev_sudong = pick

            # 🚗 차량 배정 (1종 수동)
            morning_person_car_1 = {}
            veh1_candidates = [v for v in veh1_map.keys() if v not in repair_veh1]
            for nm in sud_m:
                assigned_car = get_vehicle(nm, veh1_map)
                if assigned_car in repair_veh1 or not assigned_car:
                    assigned_car = random.choice(veh1_candidates) if veh1_candidates else ""
                morning_person_car_1[nm] = assigned_car

            # 🚗 2종 자동
            auto_m = [x for x in m_list if normalize_name(x) not in {normalize_name(y) for y in sud_m}]
            morning_person_car_2 = {}
            veh2_candidates = [v for v in veh2_map.keys() if v not in repair_veh2]
            for nm in auto_m:
                assigned_car = get_vehicle(nm, veh2_map)
                if assigned_car in repair_veh2 or not assigned_car:
                    assigned_car = random.choice(veh2_candidates) if veh2_candidates else ""
                morning_person_car_2[nm] = assigned_car

            # 🔹 오전 차량 기록 세션 저장
            st.session_state["morning_person_car_1"] = morning_person_car_1
            st.session_state["morning_person_car_2"] = morning_person_car_2
            st.session_state["morning_auto_names"] = auto_m + sud_m

            # === 출력 ===
            for nm in sud_m:
                car = morning_person_car_1.get(nm, "")
                lines.append(f"1종수동: {car} {nm}")
            lines.append("")

            lines.append("1종자동:")
            for nm in st.session_state.get("auto1_order", []):
                lines.append(f" • {nm}")
            lines.append("")

            if auto_m:
                lines.append("2종자동:")
                for nm in auto_m:
                    car = morning_person_car_2.get(nm, "")
                    lines.append(f" • {car} {nm}")

            am_text = "\n".join(lines)
            st.markdown("#### 📋 오전 결과")
            st.code(am_text, language="text")

        except Exception as e:
            st.error(f"오전 오류: {e}")
# =====================================
# 🌇 오후 근무 탭
# =====================================
with tab2:
    st.markdown("<h4 style='margin-top:6px;'>2️⃣ 오후 근무표 업로드 & OCR</h4>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        a_file = st.file_uploader("📸 오후 근무표 업로드", type=["png","jpg","jpeg"], key="a_upload")

    if st.button("오후 GPT 인식"):
        if not a_file:
            st.warning("오후 이미지를 업로드하세요.")
        else:
            with st.spinner("🧩 GPT 이미지 분석 중..."):
                names, course, excluded, early, late = gpt_extract(
                    a_file.read(), want_early=True, want_late=True, want_excluded=True
                )
                fixed = [correct_name_v2(n, st.session_state["employee_list"]) for n in names]
                excluded_fixed = [correct_name_v2(n, st.session_state["employee_list"]) for n in excluded]

                st.session_state.a_names_raw = fixed
                st.session_state.excluded_auto_afternoon = excluded_fixed
                st.session_state.afternoon_early = early
                st.session_state.afternoon_late = late
                st.success(f"오후 인식 완료 → 근무자 {len(fixed)}명, 제외자 {len(excluded_fixed)}명")

    excluded_a_text = st.text_area("🚫 근무 제외자", "\n".join(st.session_state.get("excluded_auto_afternoon", [])), height=100)
    excluded_a_set = {normalize_name(x) for x in excluded_a_text.splitlines() if x.strip()}

    afternoon_text = st.text_area("🌇 오후 근무자", "\n".join(st.session_state.get("a_names_raw", [])), height=200)
    a_list = [x.strip() for x in afternoon_text.splitlines() if x.strip()]
    a_norms = {normalize_name(x) for x in a_list} - excluded_a_set

    if st.button("📋 오후 배정 생성"):
        try:
            veh1_map = st.session_state.get("veh1", {})
            veh2_map = st.session_state.get("veh2", {})
            repair_veh1 = st.session_state.get("repair_cars_1", [])
            repair_veh2 = st.session_state.get("repair_cars_2", [])
            repair_auto1 = st.session_state.get("repair_cars_auto1", [])
            auto1_order = st.session_state.get("auto1_order", [])

            lines = []

            # 🔑 열쇠 순번
            today_key = pick_next_from_cycle(st.session_state["key_order"], prev_key, a_norms)
            if today_key:
                lines.append(f"열쇠: {today_key}")
                lines.append("")

            # 🚚 1종 수동
            sudong_order = st.session_state["sudong_order"]
            sudong_count = st.session_state["sudong_count"]
            sud_a = []
            for _ in range(sudong_count):
                pick = pick_next_from_cycle(sudong_order, prev_sudong, a_norms - {normalize_name(x) for x in sud_a})
                if pick:
                    sud_a.append(pick)
                    prev_sudong = pick

            # 🚗 1종 수동 차량 배정 (오전 차량 우선)
            morning_car_1 = st.session_state.get("morning_person_car_1", {})
            afternoon_person_car_1 = {}
            veh1_candidates = [v for v in veh1_map.keys() if v not in repair_veh1]
            for nm in sud_a:
                am_car = morning_car_1.get(nm, "")
                assigned_car = am_car if am_car and am_car not in repair_veh1 else random.choice(veh1_candidates) if veh1_candidates else ""
                afternoon_person_car_1[nm] = assigned_car

            # 🚗 1종 자동 차량 배정 (단순 순번, 정비 제외)
            auto1_valid = [x for x in auto1_order if x not in repair_auto1]
            next_auto1 = pick_next_from_cycle(auto1_valid, prev_auto1, {normalize_name(x) for x in a_list})
            prev_auto1 = next_auto1

            # 🚗 2종 자동
            morning_car_2 = st.session_state.get("morning_person_car_2", {})
            auto_a = [x for x in a_list if normalize_name(x) not in {normalize_name(y) for y in sud_a}]
            afternoon_person_car_2 = {}
            veh2_candidates = [v for v in veh2_map.keys() if v not in repair_veh2]
            for nm in auto_a:
                am_car = morning_car_2.get(nm, "")
                assigned_car = am_car if am_car and am_car not in repair_veh2 else random.choice(veh2_candidates) if veh2_candidates else ""
                afternoon_person_car_2[nm] = assigned_car

            # 🚘 마감 차량
            closed_cars = sorted(set(repair_veh1 + repair_veh2 + repair_auto1))

            # ========== 첫 번째 블록: 근무 배정 ==========
            lines.append(f"1교시: {pick_next_from_cycle(st.session_state['gyoyang_order'], prev_gyoyang5, a_norms) or ''}")
            lines.append(f"")
            for nm in sud_a:
                lines.append(f"1종수동: {afternoon_person_car_1.get(nm, '')} {nm}")
            lines.append("")
            lines.append(f"1종자동: {next_auto1 or ''}")
            lines.append("")
            lines.append("2종자동:")
            for nm in auto_a:
                lines.append(f" • {afternoon_person_car_2.get(nm, '')} {nm}")
            lines.append("")
            lines.append("마감 차량:")
            for c in closed_cars:
                lines.append(f" • {c}")

            am_text = "\n".join(lines)
            st.markdown("#### 📋 오후 근무 결과 (1/2)")
            st.code(am_text, language="text")

            # ========== 두 번째 블록: 오전 대비 비교 ==========
            lines2 = []
            lines2.append("")
            lines2.append("🔍 오전 대비 비교:")
            morning_auto_names = set(st.session_state.get("morning_auto_names", []))
            afternoon_auto_names = set(auto_a)
            afternoon_sudong_norms = {normalize_name(x) for x in sud_a}

            missing = []
            for nm in morning_auto_names:
                n_norm = normalize_name(nm)
                if n_norm not in afternoon_auto_names and n_norm not in afternoon_sudong_norms:
                    missing.append(nm)

            newly_joined = sorted([
                x for x in a_list
                if normalize_name(x) not in {normalize_name(y) for y in st.session_state.get("morning_auto_names", [])}
            ])

            if missing:
                lines2.append(" • 제외 인원: " + ", ".join(missing))
            if newly_joined:
                lines2.append(" • 신규 인원: " + ", ".join(newly_joined))

            if not missing and not newly_joined:
                lines2.append(" • 변동 없음")

            st.markdown("#### 📋 오후 근무 결과 (2/2)")
            st.code("\n".join(lines2), language="text")

        except Exception as e:
            st.error(f"오후 오류: {e}")
