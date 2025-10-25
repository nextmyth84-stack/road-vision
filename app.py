# =====================================
# app.py — 도로주행 근무 자동 배정 v7.43
# =====================================
import streamlit as st
from openai import OpenAI
import base64, re, json, os, difflib, random

st.markdown("""
<h3 style='text-align:center; color:#1e3a8a;'> 🚗 도로주행 근무 자동 배정 </h3>
<p style='text-align:center; font-size:6px; color:#64748b; margin-top:-6px;'>
    Developed by <b>wook</b>
</p>
""", unsafe_allow_html=True)

# -----------------------
# OpenAI 연결
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
# 클립보드 복사 버튼
# -----------------------
def clipboard_copy_button(label, text):
    btn_id = f"btn_{abs(hash(label+text))}"
    safe = (text or "").replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
    html = f"""
    <button id='{btn_id}' style="background:#2563eb;color:white;border:none;
    padding:8px 14px;border-radius:8px;cursor:pointer;margin-top:8px;">
      {label}
    </button>
    <script>
    (function(){{
      var b=document.getElementById('{btn_id}');
      if(!b)return;
      b.addEventListener('click', async function(){{
        try{{
          await navigator.clipboard.writeText("{safe}");
          var t=b.innerText; b.innerText="✅ 복사됨!";
          setTimeout(()=>b.innerText=t, 1800);
        }}catch(e){{
          alert('복사가 지원되지 않는 브라우저입니다.');
        }}
      }});
    }})();
    </script>
    """
    st.components.v1.html(html, height=52)

# -----------------------
# 이름 정규화 및 순번 유틸
# -----------------------
def normalize_name(s):
    return re.sub(r"[^가-힣]", "", re.sub(r"\(.*?\)", "", s or ""))

def get_vehicle(name, veh_map):
    nkey = normalize_name(name)
    for car, nm in veh_map.items():
        if normalize_name(nm) == nkey:
            return car
    return ""

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
# OCR (이름/코스/제외자/지각/조퇴)
# -----------------------
def gpt_extract(img_bytes, want_early=False, want_late=False, want_excluded=False):
    """
    반환: names(괄호 제거), course_records, excluded, early_leave, late_start
    - course_records = [{name,'A코스'/'B코스','합격'/'불합격'}]
    - excluded = ["김OO", ...]
    - early_leave = [{"name":"김OO","time":14.5}, ...]
    - late_start = [{"name":"김OO","time":10.0}, ...]
    """
    b64 = base64.b64encode(img_bytes).decode()
    user = (
        "이 이미지는 운전면허시험 근무표입니다.\n"
        "1) '학과','기능','초소','PC'는 제외하고 도로주행 근무자만 추출.\n"
        "2) 이름 옆 괄호의 'A-합','B-불','A합','B불'은 코스점검 결과.\n"
        "3) 상단/별도 표기된 '휴가,교육,출장,공가,연가,연차,돌봄' 섹션의 이름을 'excluded' 로 추출.\n"
        "4) '지각/10시 출근/외출' 등 표기에서 오전 시작시간(예:10 또는 10.5)을 late_start 로.\n"
        "5) '조퇴' 표기에서 오후 시간(13/14.5/16 등)을 early_leave 로.\n"
        "JSON 예시: {\n"
        "  \"names\": [\"김성연(B합)\",\"김병욱(A불)\"],\n"
        "  \"excluded\": [\"안유미\"],\n"
        "  \"early_leave\": [{\"name\":\"김병욱\",\"time\":14.5}],\n"
        "  \"late_start\": [{\"name\":\"김성연\",\"time\":10}]\n"
        "}"
    )
    try:
        res = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "근무표에서 이름과 메타데이터를 JSON으로 추출"},
                {"role": "user", "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]}
            ],
        )
        raw = res.choices[0].message.content
        js = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))

        raw_names = js.get("names", [])
        names, course_records = [], []
        for n in raw_names:
            m = re.search(r"([가-힣]+)\s*\(([^)]*)\)", n)
            if m:
                name = m.group(1).strip()
                detail = re.sub(r"[^A-Za-z가-힣]", "", m.group(2)).upper()
                course = "A" if "A" in detail else ("B" if "B" in detail else None)
                result = "합격" if "합" in detail else ("불합격" if "불" in detail else None)
                if course and result:
                    course_records.append({"name": name, "course": f"{course}코스", "result": result})
                names.append(name)
            else:
                names.append(n.strip())

        excluded = js.get("excluded", []) if want_excluded else []
        early_leave = js.get("early_leave", []) if want_early else []
        late_start = js.get("late_start", []) if want_late else []

        # 숫자 캐스팅
        def to_float(x):
            try:
                return float(x)
            except:
                return None
        for e in early_leave:
            e["time"] = to_float(e.get("time"))
        for l in late_start:
            l["time"] = to_float(l.get("time"))

        return names, course_records, excluded, early_leave, late_start
    except Exception as e:
        st.error(f"OCR 실패: {e}")
        return [], [], [], [], []

# -----------------------
# 교양 시간 제한
# -----------------------
def can_attend_period_morning(name_pure: str, period:int, late_list):
    tmap = {1: 9.0, 2: 10.5}
    nn = normalize_name(name_pure)
    for e in (late_list or []):
        if normalize_name(e.get("name","")) == nn:
            t = e.get("time", 99) or 99
            try: t = float(t)
            except: t = 99
            return t <= tmap[period]
    return True

def can_attend_period_afternoon(name_pure: str, period:int, early_list):
    tmap = {3: 13.0, 4: 14.5, 5: 16.0}
    nn = normalize_name(name_pure)
    for e in (early_list or []):
        if normalize_name(e.get("name","")) == nn:
            t = e.get("time", 0)
            try: t = float(t)
            except: t = 0
            return t > tmap[period]
    return True

# -----------------------
# 데이터 파일 경로 / 기본값
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
    "1종자동": "1종자동순번.json",
    "repair": "정비차량.json",  # NEW: 정비차량 저장
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
    "1종자동": ["21호","22호","23호","24호"],
    "repair": {"veh1": [], "veh2": [], "auto1": []},  # 분리 저장
}
# 초기화
for k, path in files.items():
    if not os.path.exists(path):
        save_json(path, default_data[k] if k in default_data else {})

# 로드
key_order     = load_json(files["열쇠"]) or []
gyoyang_order = load_json(files["교양"]) or []
sudong_order  = load_json(files["1종"]) or []
veh1_map      = load_json(files["veh1"]) or {}
veh2_map      = load_json(files["veh2"]) or {}
employee_list = load_json(files["employees"]) or []
auto1_order   = load_json(files["1종자동"]) or []
repair_data   = load_json(files["repair"]) or {"veh1": [], "veh2": [], "auto1": []}

# -----------------------
# 전일 근무자
# -----------------------
PREV_FILE = "전일근무.json"
def load_prev_data():
    if os.path.exists(PREV_FILE):
        try:
            with open(PREV_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"열쇠": "", "교양_5교시": "", "1종수동": "", "1종자동": ""}

prev_data   = load_prev_data()
prev_key    = prev_data.get("열쇠", "")
prev_gyo5   = prev_data.get("교양_5교시", "")
prev_sudong = prev_data.get("1종수동", "")
prev_auto1  = prev_data.get("1종자동", "")

# -----------------------
# 사이드바 (정비차량 멀티선택 + 저장/표시)
# -----------------------
st.sidebar.markdown("""
<style>
section[data-testid="stSidebar"] { background-color:#f8fafc; padding:10px; border-right:1px solid #e5e7eb; }
.streamlit-expanderHeader { font-weight:700 !important; color:#1e3a8a !important; font-size:15px !important; }
textarea, input { font-size:14px !important; }
div.stButton > button { background:#2563eb; color:#fff; border:none; border-radius:8px; padding:6px 12px; margin-top:6px; font-weight:600; }
div.stButton > button:hover { background:#1d4ed8; }
.sidebar-subtitle { font-weight:600; color:#334155; margin:10px 0 4px 0; }
</style>
""", unsafe_allow_html=True)
st.sidebar.markdown("<h3 style='text-align:center; color:#1e3a8a;'>📂 데이터 관리</h3>", unsafe_allow_html=True)

# 전일 근무자
with st.sidebar.expander("🗓 전일 근무자", expanded=True):
    prev_key    = st.text_input("🔑 전일 열쇠 담당", prev_key)
    prev_gyo5   = st.text_input("🧑‍🏫 전일 교양(5교시)", prev_gyo5)
    prev_sudong = st.text_input("🚚 전일 1종 수동", prev_sudong)
    prev_auto1  = st.text_input("🚗 전일 1종 자동(차량번호)", prev_auto1)
    if st.button("💾 전일 근무자 저장"):
        save_json(PREV_FILE, {
            "열쇠": prev_key, "교양_5교시": prev_gyo5,
            "1종수동": prev_sudong, "1종자동": prev_auto1
        })
        st.sidebar.success("전일근무.json 저장 완료 ✅")

# 순번표/차량표/근무자
with st.sidebar.expander("🔢 순번표 / 차량표 / 근무자", expanded=False):
    st.markdown("<div class='sidebar-subtitle'>열쇠 순번</div>", unsafe_allow_html=True)
    t1 = st.text_area("", "\n".join(key_order), height=120)
    st.markdown("<div class='sidebar-subtitle'>교양 순번</div>", unsafe_allow_html=True)
    t2 = st.text_area("", "\n".join(gyoyang_order), height=120)
    st.markdown("<div class='sidebar-subtitle'>1종 수동 순번</div>", unsafe_allow_html=True)
    t3 = st.text_area("", "\n".join(sudong_order), height=100)
    st.markdown("<div class='sidebar-subtitle'>1종 자동 순번(차량)</div>", unsafe_allow_html=True)
    t4 = st.text_area("", "\n".join(auto1_order), height=80)

    st.markdown("<div class='sidebar-subtitle'>1종 수동 차량표</div>", unsafe_allow_html=True)
    tveh1 = st.text_area("", "\n".join([f"{car} {nm}" for car, nm in veh1_map.items()]), height=100)
    st.markdown("<div class='sidebar-subtitle'>2종 자동 차량표</div>", unsafe_allow_html=True)
    tveh2 = st.text_area("", "\n".join([f"{car} {nm}" for car, nm in veh2_map.items()]), height=140)

    st.markdown("<div class='sidebar-subtitle'>전체 근무자</div>", unsafe_allow_html=True)
    tstaff = st.text_area("", "\n".join(employee_list), height=140)

    if st.button("💾 일괄 저장(순번/차량/근무자)"):
        save_json(files["열쇠"],     [x.strip() for x in t1.splitlines() if x.strip()])
        save_json(files["교양"],     [x.strip() for x in t2.splitlines() if x.strip()])
        save_json(files["1종"],      [x.strip() for x in t3.splitlines() if x.strip()])
        save_json(files["1종자동"],  [x.strip() for x in t4.splitlines() if x.strip()])

        # 차량표 파싱
        veh1_new, veh2_new = {}, {}
        for line in tveh1.splitlines():
            p = line.strip().split()
            if len(p) >= 2: veh1_new[p[0]] = " ".join(p[1:])
        for line in tveh2.splitlines():
            p = line.strip().split()
            if len(p) >= 2: veh2_new[p[0]] = " ".join(p[1:])
        save_json(files["veh1"], veh1_new)
        save_json(files["veh2"], veh2_new)
        save_json(files["employees"], [x.strip() for x in tstaff.splitlines() if x.strip()])
        st.sidebar.success("저장 완료 ✅ (다시 불러오려면 새로고침)")

# ✅ 정비차량 멀티선택(1종/2종/1종자동) + 저장/표시
with st.sidebar.expander("🛠 정비 차량 관리 (멀티선택)", expanded=False):
    veh1_all  = sorted(list(veh1_map.keys()))
    veh2_all  = sorted(list(veh2_map.keys()))
    auto1_all = sorted(list(auto1_order))

    sel_veh1  = st.multiselect("1종 수동 정비 차량", veh1_all, default=repair_data.get("veh1", []))
    sel_veh2  = st.multiselect("2종 자동 정비 차량", veh2_all, default=repair_data.get("veh2", []))
    sel_auto1 = st.multiselect("1종 자동 정비 차량(순번 제외)", auto1_all, default=repair_data.get("auto1", []))

    if st.button("💾 정비 목록 저장"):
        repair_data = {"veh1": sel_veh1, "veh2": sel_veh2, "auto1": sel_auto1}
        save_json(files["repair"], repair_data)
        st.sidebar.success("정비 목록 저장 완료 ✅")

    st.caption("현재 정비 목록")
    st.write("• 1종 수동:", ", ".join(sel_veh1) if sel_veh1 else "-")
    st.write("• 2종 자동:", ", ".join(sel_veh2) if sel_veh2 else "-")
    st.write("• 1종 자동(순번제외):", ", ".join(sel_auto1) if sel_auto1 else "-")

# 세션 상태 업데이트
st.session_state.update({
    "key_order": key_order, "gyoyang_order": gyoyang_order, "sudong_order": sudong_order,
    "veh1": veh1_map, "veh2": veh2_map, "employee_list": employee_list,
    "auto1_order": auto1_order,
    "repair_veh1": repair_data.get("veh1", []),
    "repair_veh2": repair_data.get("veh2", []),
    "repair_auto1": repair_data.get("auto1", []),
})

# 탭 UI
tab1, tab2 = st.tabs(["🌅 오전 근무", "🌇 오후 근무"])
st.markdown("""
    <style>
    .stTabs [data-baseweb="tab-list"] { gap: 12px; }
    .stTabs [data-baseweb="tab"] {
        font-size: 20px; padding: 16px 40px;
        border-radius: 10px 10px 0 0; background-color: #d1d5db;
    }
    .stTabs [aria-selected="true"] {
        background-color: #2563eb !important; color: white !important; font-weight: 700;
    }
    </style>
""", unsafe_allow_html=True)
# =====================================
# 🌅 오전 근무 탭
# =====================================
with tab1:
    st.markdown("<h4 style='margin-top:6px;'>1️⃣ 오전 근무표 업로드 & OCR</h4>", unsafe_allow_html=True)
    col1, _ = st.columns(2)
    with col1:
        m_file = st.file_uploader("📸 오전 근무표 업로드", type=["png","jpg","jpeg"], key="m_upload")

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
                for e in early:
                    e["name"] = correct_name_v2(e.get("name",""), st.session_state["employee_list"])
                for l in late:
                    l["name"] = correct_name_v2(l.get("name",""), st.session_state["employee_list"])

                st.session_state.m_names_raw   = fixed
                st.session_state.course_records = course
                st.session_state.excluded_auto  = excluded_fixed
                st.session_state.early_leave    = [e for e in early if e.get("time") is not None]
                st.session_state.late_start     = [l for l in late if l.get("time") is not None]
                st.success(f"오전 인식 완료 → 근무자 {len(fixed)}명, 제외자 {len(excluded_fixed)}명, 코스 {len(course)}건")

    st.markdown("<h4 style='font-size:16px;'>🚫 근무 제외자 (자동 추출 후 수정 가능)</h4>", unsafe_allow_html=True)
    excluded_text = st.text_area("근무 제외자", "\n".join(st.session_state.get("excluded_auto", [])), height=120)
    excluded_set = {normalize_name(x) for x in excluded_text.splitlines() if x.strip()}

    st.markdown("<h4 style='font-size:18px;'>🌅 오전 근무자 (수정 가능)</h4>", unsafe_allow_html=True)
    morning_text = st.text_area("오전 근무자", "\n".join(st.session_state.get("m_names_raw", [])), height=220)
    m_list = [x.strip() for x in morning_text.splitlines() if x.strip()]

    early_leave = st.session_state.get("early_leave", [])
    late_start  = st.session_state.get("late_start", [])
    m_norms = {normalize_name(x) for x in m_list} - excluded_set

    st.markdown("<h4 style='font-size:18px;'>🚗 오전 근무 배정</h4>", unsafe_allow_html=True)
    if st.button("📋 오전 배정 생성"):
        try:
            key_order     = st.session_state.get("key_order", [])
            gyoyang_order = st.session_state.get("gyoyang_order", [])
            sudong_order  = st.session_state.get("sudong_order", [])
            auto1_order   = st.session_state.get("auto1_order", [])
            veh1_map      = st.session_state.get("veh1", {})
            veh2_map      = st.session_state.get("veh2", {})
            repair_veh1   = set(st.session_state.get("repair_veh1", []))
            repair_veh2   = set(st.session_state.get("repair_veh2", []))
            repair_auto1  = set(st.session_state.get("repair_auto1", []))  # 순번 제외용
            sudong_count  = 1 if "sudong_count" not in st.session_state else st.session_state["sudong_count"]

            # 🔑 열쇠
            today_key = ""
            if key_order:
                norm_list = [normalize_name(x) for x in key_order if normalize_name(x) not in excluded_set]
                pnorm = normalize_name(prev_key)
                if pnorm in norm_list:
                    idx = (norm_list.index(pnorm) + 1) % len(norm_list)
                    today_key = [x for x in key_order if normalize_name(x) == norm_list[idx]][0]
                elif norm_list:
                    today_key = [x for x in key_order if normalize_name(x) == norm_list[0]][0]
            st.session_state.today_key = today_key

            # 🧑‍🏫 교양 1·2교시
            gy1 = pick_next_from_cycle(gyoyang_order, prev_gyo5, m_norms)
            if gy1 and not can_attend_period_morning(gy1, 1, late_start):
                gy1 = pick_next_from_cycle(gyoyang_order, gy1, m_norms)
            used_norm = {normalize_name(gy1)} if gy1 else set()
            gy2 = pick_next_from_cycle(gyoyang_order, gy1 or prev_gyo5, m_norms - used_norm)
            st.session_state.gyoyang_base_for_pm = gy2 if gy2 else prev_gyo5

            # 🚚 1종 수동 배정 (정비차 대체: 랜덤)
            sud_m, last = [], prev_sudong
            assigned_cars_1 = set()  # 오전 1종 수동 배정 차량
            for _ in range(sudong_count):
                pick = pick_next_from_cycle(sudong_order, last, m_norms - {normalize_name(x) for x in sud_m})
                if not pick: break
                last = pick
                sud_m.append(pick)
                base_car = get_vehicle(pick, veh1_map)
                car = base_car
                # 정비면 대체 (랜덤, 미사용 차량)
                if car in repair_veh1 or not car:
                    candidates = [c for c in veh1_map.keys() if c not in repair_veh1 and c not in assigned_cars_1]
                    car = random.choice(candidates) if candidates else ""
                if car: assigned_cars_1.add(car)

            st.session_state.sudong_base_for_pm = sud_m[-1] if sud_m else prev_sudong

            # 🚗 2종 자동(사람) + 정비차 대체(랜덤)
            sud_norms = {normalize_name(x) for x in sud_m}
            auto_m_people = [x for x in m_list if normalize_name(x) in (m_norms - sud_norms)]
            assigned_cars_2 = set()
            # 오전 기록(이름→차량) 저장용
            morning_person_car_2 = {}

            for nm in auto_m_people:
                base_car = get_vehicle(nm, veh2_map)
                car = base_car
                if car in repair_veh2 or not car:
                    candidates = [c for c in veh2_map.keys() if c not in repair_veh2 and c not in assigned_cars_2]
                    car = random.choice(candidates) if candidates else ""
                if car:
                    assigned_cars_2.add(car)
                    morning_person_car_2[normalize_name(nm)] = car

            # 오전 차량 기록
            st.session_state.morning_assigned_cars_1 = list(assigned_cars_1)
            st.session_state.morning_assigned_cars_2 = list(assigned_cars_2)
            st.session_state.morning_auto_names = auto_m_people + sud_m
            st.session_state.morning_person_car_2 = morning_person_car_2  # 오후에 우선 배정

            # === NEW: 1종 자동 순번 (정비 차량 제외 후 순번)
            today_auto1 = ""
            rot_pool = [c for c in auto1_order if c not in repair_auto1]  # 정비 제외
            if rot_pool:
                if prev_auto1 in rot_pool:
                    idx = (rot_pool.index(prev_auto1) + 1) % len(rot_pool)
                    today_auto1 = rot_pool[idx]
                else:
                    today_auto1 = rot_pool[0]
            st.session_state.today_auto1 = today_auto1

            # === 출력 ===
            lines = []
            if today_key:
                lines.append(f"열쇠: {today_key}")
                lines.append("")  # 열쇠 다음 한 줄

            if gy1: lines.append(f"1교시: {gy1}")
            if gy2: lines.append(f"2교시: {gy2}")
            if gy1 or gy2: lines.append("")

            # 1종수동
            if sud_m:
                for nm in sud_m:
                    # 출력은 '차량 이름' 형태
                    out_car = get_vehicle(nm, veh1_map)
                    if out_car in repair_veh1 or out_car == "":
                        # 실제 배정된 차량 추정: 오전 assigned_cars_1에 존재
                        # 정확한 매핑은 상단 선택에서 기록을 안했으므로 간단 표기
                        pass
                    car_label = out_car if out_car else "(배정없음)"
                    lines.append(f"1종수동: {car_label} {nm}")
            else:
                lines.append("1종수동: (배정자 없음)")

            # 1종자동 (한 줄 공백 후)
            lines.append("")
            if today_auto1:
                lines.append(f"1종자동: {today_auto1}")
            else:
                lines.append("1종자동: (순번 없음)")

            # 2종자동 (한 줄 공백 후)
            lines.append("")
            if auto_m_people:
                lines.append("2종자동:")
                for nm in auto_m_people:
                    car = st.session_state.morning_person_car_2.get(normalize_name(nm), get_vehicle(nm, veh2_map) or "")
                    label = f"{car} {nm}" if car else nm
                    lines.append(f" • {label}")
            else:
                lines.append("2종자동: (배정자 없음)")

            # 코스점검
            course_records = st.session_state.get("course_records", [])
            if course_records:
                lines.append("")
                lines.append("코스점검:")
                for c in ["A", "B"]:
                    passed = [r["name"] for r in course_records if r["course"] == f"{c}코스" and r["result"] == "합격"]
                    failed = [r["name"] for r in course_records if r["course"] == f"{c}코스" and r["result"] == "불합격"]
                    if passed: lines.append(f" • {c}코스 합격: {', '.join(passed)}")
                    if failed: lines.append(f" • {c}코스 불합격: {', '.join(failed)}")

            am_text = "\n".join(lines)
            st.markdown("#### 📋 오전 결과")
            st.code(am_text, language="text")
            clipboard_copy_button("📋 결과 복사하기", am_text)

        except Exception as e:
            st.error(f"오전 오류: {e}")
# =====================================
# 🌇 오후 근무 탭
# =====================================
with tab2:
    st.markdown("<h4 style='margin-top:6px;'>2️⃣ 오후 근무표 업로드 & OCR</h4>", unsafe_allow_html=True)
    col1, _ = st.columns(2)
    with col1:
        a_file = st.file_uploader("📸 오후 근무표 업로드", type=["png","jpg","jpeg"], key="a_upload")

    if st.button("오후 GPT 인식"):
        if not a_file:
            st.warning("오후 이미지를 업로드하세요.")
        else:
            with st.spinner("🧩 GPT 이미지 분석 중..."):
                names, _, excluded, early, late = gpt_extract(
                    a_file.read(), want_early=True, want_late=True, want_excluded=True
                )
                fixed = [correct_name_v2(n, st.session_state["employee_list"]) for n in names]
                excluded_fixed = [correct_name_v2(n, st.session_state["employee_list"]) for n in excluded]
                for e in early:
                    e["name"] = correct_name_v2(e.get("name",""), st.session_state["employee_list"])
                for l in late:
                    l["name"] = correct_name_v2(l.get("name",""), st.session_state["employee_list"])

                st.session_state.a_names_raw      = fixed
                st.session_state.excluded_auto_pm = excluded_fixed
                st.session_state.early_leave_pm   = [e for e in early if e.get("time") is not None]
                st.session_state.late_start_pm    = [l for l in late if l.get("time") is not None]
                st.success(f"오후 인식 완료 → 근무자 {len(fixed)}명, 제외자 {len(excluded_fixed)}명")

    st.markdown("<h4 style='font-size:18px;'>🌇 오후 근무자 (수정 가능)</h4>", unsafe_allow_html=True)
    afternoon_text = st.text_area("오후 근무자", "\n".join(st.session_state.get("a_names_raw", [])), height=220)
    a_list = [x.strip() for x in afternoon_text.splitlines() if x.strip()]

    excluded_set = {normalize_name(x) for x in st.session_state.get("excluded_auto", [])}
    a_norms = {normalize_name(x) for x in a_list} - excluded_set

    save_check = st.checkbox("전일근무자(열쇠,5교시,1종수동,1종자동) 자동 저장", value=True)

    st.markdown("<h4 style='font-size:18px;'>🚘 오후 근무 배정</h4>", unsafe_allow_html=True)
    if st.button("📋 오후 배정 생성"):
        try:
            gyoyang_order = st.session_state.get("gyoyang_order", [])
            sudong_order  = st.session_state.get("sudong_order", [])
            auto1_order   = st.session_state.get("auto1_order", [])
            veh1_map      = st.session_state.get("veh1", {})
            veh2_map      = st.session_state.get("veh2", {})
            repair_veh1   = set(st.session_state.get("repair_veh1", []))
            repair_veh2   = set(st.session_state.get("repair_veh2", []))
            repair_auto1  = set(st.session_state.get("repair_auto1", []))
            sudong_count  = 1 if "sudong_count" not in st.session_state else st.session_state["sudong_count"]

            today_key = st.session_state.get("today_key", prev_key)
            gy_start  = st.session_state.get("gyoyang_base_for_pm", prev_gyo5) or (gyoyang_order[0] if gyoyang_order else "")
            sud_base  = st.session_state.get("sudong_base_for_pm", prev_sudong)
            early_leave = st.session_state.get("early_leave", [])

            # 🧑‍🏫 교양 3~5교시
            used = set()
            gy3 = gy4 = gy5 = None
            last_ptr = gy_start
            for period in [3, 4, 5]:
                while True:
                    pick = pick_next_from_cycle(gyoyang_order, last_ptr, a_norms - used)
                    if not pick:
                        break
                    last_ptr = pick
                    if can_attend_period_afternoon(pick, period, early_leave):
                        if period == 3: gy3 = pick
                        elif period == 4: gy4 = pick
                        else: gy5 = pick
                        used.add(normalize_name(pick))
                        break

            # 🚚 1종 수동 (오전에 배정된 차가 정비가 아니면 우선 유지, 아니면 랜덤 대체)
            sud_a, last = [], sud_base
            assigned_cars_1_pm = set()
            morning_person_car_1 = {}  # 오전 1종 수동은 차량-사람 매핑이 없어서 비워둠

            for _ in range(sudong_count):
                pick = pick_next_from_cycle(sudong_order, last, a_norms)
                if not pick: break
                last = pick
                sud_a.append(pick)

                car = get_vehicle(pick, veh1_map)
                # 정비면 랜덤 대체(미사용)
                if car in repair_veh1 or not car:
                    candidates = [c for c in veh1_map.keys() if c not in repair_veh1 and c not in assigned_cars_1_pm]
                    car = random.choice(candidates) if candidates else ""
                if car: assigned_cars_1_pm.add(car)

            # 🚗 2종 자동(사람) — 오전 차량 유지 우선, 불가시 랜덤 대체
            sud_a_norms = {normalize_name(x) for x in sud_a}
            auto_a_people = [x for x in a_list if normalize_name(x) in (a_norms - sud_a_norms)]

            assigned_cars_2_pm = set()
            morning_person_car_2 = st.session_state.get("morning_person_car_2", {})

            for nm in auto_a_people:
                nn = normalize_name(nm)
                prefer_car = morning_person_car_2.get(nn, "")
                car = prefer_car
                # 오전 차량이 유효하고 미정비/미사용이면 그대로
                if car and car not in repair_veh2 and car not in assigned_cars_2_pm:
                    assigned_cars_2_pm.add(car)
                else:
                    # 랜덤 대체
                    candidates = [c for c in veh2_map.keys() if c not in repair_veh2 and c not in assigned_cars_2_pm]
                    car = random.choice(candidates) if candidates else ""
                    if car:
                        assigned_cars_2_pm.add(car)

            # === 1종 자동 순번 (정비 제외) — 오전과 동일 순번값 사용
            rot_pool = [c for c in auto1_order if c not in repair_auto1]
            today_auto1 = st.session_state.get("today_auto1", "")
            if not today_auto1 and rot_pool:
                # 오전이 없었다면 여기서라도 계산
                if prev_auto1 in rot_pool:
                    idx = (rot_pool.index(prev_auto1) + 1) % len(rot_pool)
                    today_auto1 = rot_pool[idx]
                else:
                    today_auto1 = rot_pool[0]
                st.session_state.today_auto1 = today_auto1

            # === 출력(블록1: 열쇠~마감차량)
            lines = []
            if today_key: 
                lines.append(f"열쇠: {today_key}")
                lines.append("")  # 열쇠 다음 한 줄

            if gy3: lines.append(f"3교시: {gy3}")
            if gy4: lines.append(f"4교시: {gy4}")
            if gy5: lines.append(f"5교시: {gy5}")
            if gy3 or gy4 or gy5: lines.append("")

            # 1종수동
            if sud_a:
                for nm in sud_a:
                    car = get_vehicle(nm, veh1_map)
                    label = f"{car} {nm}" if car else nm
                    lines.append(f"1종수동: {label}")
            else:
                lines.append("1종수동: (배정자 없음)")

            # 1종자동 (한 줄 공백 후)
            lines.append("")
            if today_auto1:
                lines.append(f"1종자동: {today_auto1}")
            else:
                lines.append("1종자동: (순번 없음)")

            # 2종자동 (한 줄 공백 후)
            lines.append("")
            if auto_a_people:
                lines.append("2종자동:")
                for nm in auto_a_people:
                    # 표시 우선순위: 오후 실제 배정차량 추정 불가 → 오전 유지 or 기본차량
                    # (여기서는 차량번호 표시보다 사람명 위주)
                    base_car = get_vehicle(nm, veh2_map)
                    prefer_car = morning_person_car_2.get(normalize_name(nm), base_car)
                    label = f"{prefer_car} {nm}" if prefer_car else nm
                    lines.append(f" • {label}")
            else:
                lines.append("2종자동: (배정자 없음)")

            # 🚫 마감 차량 (오전 → 오후 빠진 차량)
            am_c1 = set(st.session_state.get("morning_assigned_cars_1", []))
            am_c2 = set(st.session_state.get("morning_assigned_cars_2", []))
            pm_c1 = set(assigned_cars_1_pm)
            pm_c2 = set(assigned_cars_2_pm)
            un1 = sorted([c for c in am_c1 if c and c not in pm_c1])
            un2 = sorted([c for c in am_c2 if c and c not in pm_c2])
            if un1 or un2:
                lines.append("")
                lines.append("🚫 마감 차량:")
                if un1:
                    lines.append(" [1종 수동]")
                    for c in un1: lines.append(f"  • {c} 마감")
                if un2:
                    lines.append(" [2종 자동]")
                    for c in un2: lines.append(f"  • {c} 마감")

            # ===== 블록 분리 지점 =====
            block1_text = "\n".join(lines).strip()

            # 🔍 블록2: 오전 대비 비교 (도로주행 근무자만, 신규 인원만 표시)
            morning_auto_names = set(st.session_state.get("morning_auto_names", []))
            afternoon_auto_names = set(auto_a)
            afternoon_sudong_norms = {normalize_name(x) for x in sud_a}

            added = sorted(list(afternoon_auto_names - morning_auto_names))
            missing = []
            for nm in morning_auto_names:
                n_norm = normalize_name(nm)
                if n_norm not in afternoon_auto_names and n_norm not in afternoon_sudong_norms:
                    missing.append(nm)

            newly_joined = sorted([
                x for x in a_list
                if normalize_name(x) not in {normalize_name(y) for y in st.session_state.get("morning_auto_names", [])}
            ])
            
            if added:        lines.append(" • 추가 인원: " + ", ".join(added))
            if missing:      lines.append(" • 제외 인원: " + ", ".join(missing))
            if newly_joined: lines.append(" • 신규 인원: " + ", ".join(newly_joined))

            # === 출력 ===
            st.markdown("#### 🌇 오후 근무 결과 (블록 1)")
            st.code(block1_text, language="text")
            clipboard_copy_button("📋 결과 복사하기", block1_text)

            st.markdown("#### 🔍 오전 대비 비교 (블록 2)")
            st.code(block2_text, language="text")
            clipboard_copy_button("📋 비교 복사하기", block2_text)

            # ✅ 전일 저장 (열쇠/5교시/1종수동/1종자동)
            if save_check:
                save_json(PREV_FILE, {
                    "열쇠": today_key,
                    "교양_5교시": gy5 or gy4 or gy3 or prev_gyo5,
                    "1종수동": (sud_a[-1] if sud_a else prev_sudong),
                    "1종자동": st.session_state.get("today_auto1", prev_auto1)
                })
                st.success("전일근무.json 업데이트 완료 ✅")

        except Exception as e:
            st.error(f"오후 오류: {e}")
