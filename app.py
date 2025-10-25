# =====================================
# app.py — 도로주행 근무 자동 배정 v7.41
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
# 복사 버튼 (모바일 호환)
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
          alert('복사가 지원되지 않는 브라우저입니다. 텍스트를 길게 눌러 복사하세요.');
        }}
      }});
    }})();
    </script>
    """
    st.components.v1.html(html, height=52)

# -----------------------
# 이름 정규화 / 차량 / 교정 / 순번
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
# OCR 함수
# -----------------------
def gpt_extract(img_bytes, want_early=False, want_late=False, want_excluded=False):
    b64 = base64.b64encode(img_bytes).decode()
    user = (
        "이 이미지는 운전면허시험 근무표입니다.\n"
        "다른 업무(학과, 기능, PC학과, 초소 등)는 완전히 무시하고,\n"
        "‘도로주행’ 항목의 근무자 이름만 순서대로 정확히 추출하세요.\n"
        "조건:\n"
        "1. ‘오전’ 또는 ‘오후’ 표시된 시간대만 인식합니다.\n"
        "2. 이름 옆 괄호 안 정보(A-불, B-합 등)는 그대로 인식합니다.\n"
        "3. 도로주행 근무자만 줄 단위로 출력하고, 다른 텍스트는 버립니다.\n"
        "4. ‘교육’, ‘휴가’, ‘출장’, ‘공가’, ‘연가’, ‘연차’, ‘돌봄’ 등의 이름은 결과에서 제외합니다.\n"
        "출력 예시(JSON):\n"
        "{\n"
        "  \"names\": [\"김성연(B합)\", \"김병욱(A불)\"],\n"
        "  \"excluded\": [\"안유미\"],\n"
        "  \"early_leave\": [{\"name\": \"김병욱\", \"time\": 14.5}],\n"
        "  \"late_start\": [{\"name\": \"김성연\", \"time\": 10}]\n"
        "}"
)

    try:
        res = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "근무표에서 도로주행 근무자 이름과 메타데이터를 JSON으로 추출"},
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
        return names, course_records, excluded, [], []
    except Exception as e:
        st.error(f"OCR 실패: {e}")
        return [], [], [], [], []
# -----------------------
# 데이터 파일 경로/기본값
# -----------------------
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

FILES = {
    "열쇠": os.path.join(DATA_DIR, "열쇠순번.json"),
    "교양": os.path.join(DATA_DIR, "교양순번.json"),
    "1종":  os.path.join(DATA_DIR, "1종순번.json"),
    "veh1": os.path.join(DATA_DIR, "1종차량표.json"),
    "veh2": os.path.join(DATA_DIR, "2종차량표.json"),
    "employees": os.path.join(DATA_DIR, "전체근무자.json"),
    "repair": os.path.join(DATA_DIR, "정비차량.json"),
}
DEFAULTS = {
    "열쇠": ["권한솔","김남균","김면정","김성연","김지은","안유미","윤여헌","윤원실","이나래","이호석","조윤영","조정래"],
    "교양": ["권한솔","김남균","김면정","김병욱","김성연","김주현","김지은","안유미","이호석","조정래"],
    "1종":  ["권한솔","김남균","김성연","김주현","이호석","조정래"],
    "veh1": {"2호":"조정래","5호":"권한솔","7호":"김남균","8호":"이호석","9호":"김주현","10호":"김성연"},
    "veh2": {"4호":"김남균","5호":"김병욱","6호":"김지은","12호":"안유미","14호":"김면정","15호":"이호석","17호":"김성연","18호":"권한솔","19호":"김주현","22호":"조정래"},
    "employees": ["권한솔","김남균","김면정","김성연","김지은","안유미","윤여헌","윤원실","이나래","이호석","조윤영","조정래","김병욱","김주현"],
    "repair": {"veh1": [], "veh2": []},  # 1종/2종 정비차량 분리 저장
}

# 파일 초기화
for k, path in FILES.items():
    if not os.path.exists(path):
        save_json(path, DEFAULTS[k])

# 로드
key_order     = load_json(FILES["열쇠"])
gyoyang_order = load_json(FILES["교양"])
sudong_order  = load_json(FILES["1종"])
veh1_map      = load_json(FILES["veh1"])
veh2_map      = load_json(FILES["veh2"])
employee_list = load_json(FILES["employees"])
repair_store  = load_json(FILES["repair"]) or {"veh1": [], "veh2": []}

# -----------------------
# 전일 근무자 파일
# -----------------------
PREV_FILE = "전일근무.json"
def load_prev_data():
    d = load_json(PREV_FILE, None)
    if d is None:
        d = {"열쇠": "", "교양_5교시": "", "1종수동": ""}
        save_json(PREV_FILE, d)
    return d

prev_data     = load_prev_data()
prev_key      = prev_data.get("열쇠", "")
prev_gyoyang5 = prev_data.get("교양_5교시", "")
prev_sudong   = prev_data.get("1종수동", "")

# -----------------------
# 사이드바 CSS (가독성)
# -----------------------
st.sidebar.markdown("""
<style>
section[data-testid="stSidebar"] { background:#f8fafc; padding:10px; border-right:1px solid #e5e7eb; }
.streamlit-expanderHeader { font-weight:700 !important; color:#1e3a8a !important; font-size:15px !important; }
textarea, input { font-size:14px !important; }
div.stButton > button { background:#2563eb; color:#fff; border:none; border-radius:8px; padding:6px 12px; margin-top:6px; font-weight:600; }
div.stButton > button:hover { background:#1d4ed8; }
.sidebar-subtitle { font-weight:600; color:#334155; margin:10px 0 4px 0; }
.badge { display:inline-block; background:#e2e8f0; color:#0f172a; padding:2px 8px; margin:2px; border-radius:999px; font-size:12px; }
.badge.red { background:#fee2e2; color:#991b1b; }
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
    if st.button("💾 전일 근무자 저장"):
        save_json(PREV_FILE, {"열쇠": prev_key, "교양_5교시": prev_gyoyang5, "1종수동": prev_sudong})
        st.sidebar.success("전일근무.json 저장 완료 ✅")

# -----------------------
# 🔢 순번표 관리
# -----------------------
with st.sidebar.expander("🔢 순번표 관리", expanded=False):
    st.markdown("<div class='sidebar-subtitle'>열쇠 순번</div>", unsafe_allow_html=True)
    t1 = st.text_area(" ", "\n".join(key_order), height=140, key="ta_key_order")
    st.markdown("<div class='sidebar-subtitle'>교양 순번</div>", unsafe_allow_html=True)
    t2 = st.text_area("  ", "\n".join(gyoyang_order), height=140, key="ta_gyo_order")
    st.markdown("<div class='sidebar-subtitle'>1종 수동 순번</div>", unsafe_allow_html=True)
    t3 = st.text_area("   ", "\n".join(sudong_order), height=110, key="ta_sd_order")

    if st.button("💾 순번표 저장"):
        key_order     = [x.strip() for x in t1.splitlines() if x.strip()]
        gyoyang_order = [x.strip() for x in t2.splitlines() if x.strip()]
        sudong_order  = [x.strip() for x in t3.splitlines() if x.strip()]
        save_json(FILES["열쇠"], key_order)
        save_json(FILES["교양"], gyoyang_order)
        save_json(FILES["1종"],  sudong_order)
        st.sidebar.success("순번표 저장 완료 ✅")

# -----------------------
# 🚘 차량 담당 관리
# -----------------------
with st.sidebar.expander("🚘 차량 담당 관리", expanded=False):
    def veh_map_to_text(m):  # {"10호":"김성연"} -> "10호 김성연"
        return "\n".join([f"{car} {nm}" for car, nm in m.items()])
    def text_to_veh_map(txt):
        out = {}
        for line in txt.splitlines():
            p = line.strip().split()
            if len(p) >= 2:
                out[p[0]] = " ".join(p[1:])
        return out

    st.markdown("<div class='sidebar-subtitle'>1종 수동 차량표</div>", unsafe_allow_html=True)
    tveh1 = st.text_area("    ", veh_map_to_text(veh1_map), height=120, key="ta_veh1")
    st.markdown("<div class='sidebar-subtitle'>2종 자동 차량표</div>", unsafe_allow_html=True)
    tveh2 = st.text_area("     ", veh_map_to_text(veh2_map), height=140, key="ta_veh2")

    if st.button("💾 차량표 저장"):
        veh1_map = text_to_veh_map(tveh1)
        veh2_map = text_to_veh_map(tveh2)
        save_json(FILES["veh1"], veh1_map)
        save_json(FILES["veh2"], veh2_map)
        st.sidebar.success("차량표 저장 완료 ✅")

# -----------------------
# 👥 전체 근무자
# -----------------------
with st.sidebar.expander("👥 전체 근무자", expanded=False):
    tall = st.text_area("      ", "\n".join(employee_list), height=180, key="ta_emp")
    if st.button("💾 근무자 저장"):
        employee_list = [x.strip() for x in tall.splitlines() if x.strip()]
        save_json(FILES["employees"], employee_list)
        st.sidebar.success("근무자 명단 저장 완료 ✅")

# -----------------------
# 🛠 정비 차량 관리 (선택+목록+삭제)
# -----------------------
with st.sidebar.expander("🛠 정비 차량 관리", expanded=True):
    # 현재 보유 차량번호 리스트
    veh1_list = sorted(list(veh1_map.keys()), key=lambda x: (len(x), x))
    veh2_list = sorted(list(veh2_map.keys()), key=lambda x: (len(x), x))

    st.markdown("<div class='sidebar-subtitle'>1종 수동 정비 차량 선택</div>", unsafe_allow_html=True)
    sel_veh1 = st.multiselect("1종(여러개 선택 가능)", options=veh1_list, default=repair_store.get("veh1", []), key="ms_repair_v1")

    st.markdown("<div class='sidebar-subtitle'>2종 자동 정비 차량 선택</div>", unsafe_allow_html=True)
    sel_veh2 = st.multiselect("2종(여러개 선택 가능)", options=veh2_list, default=repair_store.get("veh2", []), key="ms_repair_v2")

    if st.button("💾 정비 차량 저장"):
        repair_store = {"veh1": sel_veh1, "veh2": sel_veh2}
        save_json(FILES["repair"], repair_store)
        st.success("정비 차량 저장 완료 ✅")

    # 현재 정비 목록 표시 + 개별 삭제
    st.markdown("<div class='sidebar-subtitle'>현재 정비 목록</div>", unsafe_allow_html=True)
    if not repair_store.get("veh1") and not repair_store.get("veh2"):
        st.caption("등록된 정비 차량이 없습니다.")
    else:
        if repair_store.get("veh1"):
            st.write("**[1종]**", " ".join([f"<span class='badge red'>{c}</span>" for c in repair_store["veh1"]]), unsafe_allow_html=True)
        if repair_store.get("veh2"):
            st.write("**[2종]**", " ".join([f"<span class='badge red'>{c}</span>" for c in repair_store["veh2"]]), unsafe_allow_html=True)

        # 개별 삭제 UI
        del1 = st.multiselect("삭제할 1종 정비차량", options=repair_store.get("veh1", []), key="del_v1")
        del2 = st.multiselect("삭제할 2종 정비차량", options=repair_store.get("veh2", []), key="del_v2")
        if st.button("선택 삭제"):
            new_v1 = [c for c in repair_store.get("veh1", []) if c not in del1]
            new_v2 = [c for c in repair_store.get("veh2", []) if c not in del2]
            repair_store = {"veh1": new_v1, "veh2": new_v2}
            save_json(FILES["repair"], repair_store)
            st.success("선택한 정비 차량 삭제 완료 ✅")

# -----------------------
# 세션 최신화 (전역 참조용)
# -----------------------
CUTOFF = 0.6  # 고정 컷오프
st.session_state.update({
    "key_order": key_order,
    "gyoyang_order": gyoyang_order,
    "sudong_order": sudong_order,
    "veh1": veh1_map,
    "veh2": veh2_map,
    "employee_list": employee_list,
    "repair_store": repair_store,
    "prev_key": prev_key,
    "prev_gyoyang5": prev_gyoyang5,
    "prev_sudong": prev_sudong,
})
# =====================================
# 🌅 오전 근무 탭
# =====================================
tab1, tab2 = st.tabs(["🌅 오전 근무", "🌇 오후 근무"])

# 스타일
st.markdown("""
<style>
.stTabs [data-baseweb="tab-list"] { gap: 12px; }
.stTabs [data-baseweb="tab"] {
    font-size: 18px; padding: 14px 36px; border-radius: 10px 10px 0 0;
    background-color: #d1d5db;
}
.stTabs [aria-selected="true"] {
    background-color: #2563eb !important;
    color: white !important; font-weight: 700;
}
</style>
""", unsafe_allow_html=True)

# ----------------------- #
# 🌅 오전 탭 본문
# ----------------------- #
with tab1:
    st.markdown("<h4>1️⃣ 오전 근무표 업로드 & OCR</h4>", unsafe_allow_html=True)
    m_file = st.file_uploader("📸 오전 근무표 업로드", type=["png","jpg","jpeg"], key="m_upload")

    if st.button("🧩 오전 GPT 인식"):
        if not m_file:
            st.warning("오전 이미지를 업로드하세요.")
        else:
            with st.spinner("이미지 분석 중..."):
                names, course, excluded, early, late = gpt_extract(m_file.read(), want_excluded=True)
                fixed = [correct_name_v2(n, st.session_state["employee_list"], cutoff=0.6) for n in names]
                excluded_fixed = [correct_name_v2(n, st.session_state["employee_list"], cutoff=0.6) for n in excluded]

                st.session_state.m_names_raw = fixed
                st.session_state.course_records = course
                st.session_state.excluded_auto = excluded_fixed
                st.success(f"인식 완료: 근무자 {len(fixed)}명, 제외자 {len(excluded_fixed)}명, 코스 {len(course)}건")

    st.markdown("#### 🚫 근무 제외자 (자동 추출 후 수정 가능)")
    excluded_text = st.text_area("근무 제외자", "\n".join(st.session_state.get("excluded_auto", [])), height=120)
    excluded_set = {normalize_name(x) for x in excluded_text.splitlines() if x.strip()}

    st.markdown("#### 🌅 오전 근무자 (수정 가능)")
    morning_text = st.text_area("오전 근무자", "\n".join(st.session_state.get("m_names_raw", [])), height=220)
    m_list = [x.strip() for x in morning_text.splitlines() if x.strip()]

    # 제외자 반영
    m_norms = {normalize_name(x) for x in m_list} - excluded_set

    # 🚗 오전 근무 배정
    st.markdown("#### 🚗 오전 근무 배정")
    if st.button("📋 오전 배정 생성"):
        try:
            key_order     = st.session_state.get("key_order", [])
            gyoyang_order = st.session_state.get("gyoyang_order", [])
            sudong_order  = st.session_state.get("sudong_order", [])
            veh1_map      = st.session_state.get("veh1", {})
            veh2_map      = st.session_state.get("veh2", {})
            repair_store  = st.session_state.get("repair_store", {"veh1": [], "veh2": []})
            prev_key      = st.session_state.get("prev_key", "")
            prev_gyoyang5 = st.session_state.get("prev_gyoyang5", "")
            prev_sudong   = st.session_state.get("prev_sudong", "")

            # 🔑 열쇠
            today_key = pick_next_from_cycle(key_order, prev_key, m_norms) or prev_key

            # 🧑‍🏫 교양 1, 2교시
            gy1 = pick_next_from_cycle(gyoyang_order, prev_gyoyang5, m_norms)
            gy2 = pick_next_from_cycle(gyoyang_order, gy1 or prev_gyoyang5, m_norms - {normalize_name(gy1)})

            # 🚚 1종 수동
            sud_m = [pick_next_from_cycle(sudong_order, prev_sudong, m_norms)]
            sud_m = [x for x in sud_m if x]

            # 🚗 2종 자동
            sud_norms = {normalize_name(x) for x in sud_m}
            auto_m = [x for x in m_list if normalize_name(x) in (m_norms - sud_norms)]

            # 차량 배정 (정비차량 회피 + 랜덤대체)
            def pick_car(name, veh_map, repair_list):
                car = get_vehicle(name, veh_map)
                if car in repair_list:  # 정비 중이면 랜덤 배정
                    available = [c for c in veh_map.keys() if c not in repair_list]
                    return random.choice(available) if available else car
                return car

            assigned_veh1 = [pick_car(x, veh1_map, repair_store["veh1"]) for x in sud_m]
            assigned_veh2 = [pick_car(x, veh2_map, repair_store["veh2"]) for x in auto_m]

            # === 출력 ===
            lines = []
            if today_key: lines.append(f"열쇠: {today_key}\n")
            if gy1: lines.append(f"1교시: {gy1}")
            if gy2: lines.append(f"2교시: {gy2}\n")

            for i, nm in enumerate(sud_m):
                lines.append(f"1종수동: {assigned_veh1[i]} {nm}")

            lines.append("")  # 한줄 띄기
            lines.append("2종자동:")
            for i, nm in enumerate(auto_m):
                lines.append(f" • {assigned_veh2[i]} {nm}")

            # 코스점검
            course_records = st.session_state.get("course_records", [])
            if course_records:
                lines.append("\n코스점검 결과:")
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
    st.markdown("<h4>2️⃣ 오후 근무표 업로드 & OCR</h4>", unsafe_allow_html=True)
    a_file = st.file_uploader("📸 오후 근무표 업로드", type=["png","jpg","jpeg"], key="a_upload")

    if st.button("🧩 오후 GPT 인식"):
        if not a_file:
            st.warning("오후 이미지를 업로드하세요.")
        else:
            with st.spinner("이미지 분석 중..."):
                names, _, excluded, _, _ = gpt_extract(a_file.read(), want_excluded=True)
                fixed = [correct_name_v2(n, st.session_state["employee_list"], cutoff=0.6) for n in names]
                excluded_fixed = [correct_name_v2(n, st.session_state["employee_list"], cutoff=0.6) for n in excluded]
                st.session_state.a_names_raw = fixed
                st.session_state.excluded_auto_pm = excluded_fixed
                st.success(f"인식 완료: 근무자 {len(fixed)}명, 제외자 {len(excluded_fixed)}명")

    st.markdown("#### 🌇 오후 근무자 (수정 가능)")
    afternoon_text = st.text_area("오후 근무자", "\n".join(st.session_state.get("a_names_raw", [])), height=220)
    a_list = [x.strip() for x in afternoon_text.splitlines() if x.strip()]
    excluded_set = {normalize_name(x) for x in st.session_state.get("excluded_auto", [])}
    a_norms = {normalize_name(x) for x in a_list} - excluded_set

    save_check = st.checkbox("전일근무자(열쇠,5교시,1종수동) 자동 저장", value=True)

    st.markdown("#### 🚘 오후 근무 배정")
    if st.button("📋 오후 배정 생성"):
        try:
            gyoyang_order = st.session_state.get("gyoyang_order", [])
            sudong_order  = st.session_state.get("sudong_order", [])
            veh1_map      = st.session_state.get("veh1", {})
            veh2_map      = st.session_state.get("veh2", {})
            repair_store  = st.session_state.get("repair_store", {"veh1": [], "veh2": []})
            prev_key      = st.session_state.get("prev_key", "")
            prev_gyoyang5 = st.session_state.get("prev_gyoyang5", "")
            prev_sudong   = st.session_state.get("prev_sudong", "")

            # 🔑 열쇠
            today_key = pick_next_from_cycle(st.session_state.get("key_order", []), prev_key, a_norms) or prev_key

            # 🧑‍🏫 교양 3~5교시
            gy3 = pick_next_from_cycle(gyoyang_order, prev_gyoyang5, a_norms)
            gy4 = pick_next_from_cycle(gyoyang_order, gy3 or prev_gyoyang5, a_norms - {normalize_name(gy3)})
            gy5 = pick_next_from_cycle(gyoyang_order, gy4 or gy3 or prev_gyoyang5, a_norms - {normalize_name(gy3), normalize_name(gy4)})

            # 🚚 1종 수동
            sud_a = [pick_next_from_cycle(sudong_order, prev_sudong, a_norms)]
            sud_a = [x for x in sud_a if x]

            # 🚗 2종 자동
            sud_norms = {normalize_name(x) for x in sud_a}
            auto_a = [x for x in a_list if normalize_name(x) in (a_norms - sud_norms)]

            # 🚗 차량 배정 (정비 랜덤 대체)
            def pick_car(name, veh_map, repair_list):
                car = get_vehicle(name, veh_map)
                if car in repair_list:
                    available = [c for c in veh_map.keys() if c not in repair_list]
                    return random.choice(available) if available else car
                return car

            assigned_veh1 = [pick_car(x, veh1_map, repair_store["veh1"]) for x in sud_a]
            assigned_veh2 = [pick_car(x, veh2_map, repair_store["veh2"]) for x in auto_a]

            # === 출력 1 (근무 결과)
            lines1 = []
            if today_key: lines1.append(f"열쇠: {today_key}\n")
            if gy3: lines1.append(f"3교시: {gy3}")
            if gy4: lines1.append(f"4교시: {gy4}")
            if gy5: lines1.append(f"5교시: {gy5}\n")

            for i, nm in enumerate(sud_a):
                lines1.append(f"1종수동: {assigned_veh1[i]} {nm}")
            lines1.append("")
            lines1.append("2종자동:")
            for i, nm in enumerate(auto_a):
                lines1.append(f" • {assigned_veh2[i]} {nm}")

            # 🚫 미배정 차량
            am_c1 = set(st.session_state.get("morning_assigned_cars_1", []))
            am_c2 = set(st.session_state.get("morning_assigned_cars_2", []))
            pm_c1 = set(assigned_veh1)
            pm_c2 = set(assigned_veh2)
            un1 = sorted([c for c in am_c1 if c and c not in pm_c1])
            un2 = sorted([c for c in am_c2 if c and c not in pm_c2])
            if un1 or un2:
                lines1.append("")
                lines1.append("🚫 미배정 차량:")
                if un1:
                    lines1.append(" [1종 수동]")
                    for c in un1: lines1.append(f"  • {c} 마감")
                if un2:
                    lines1.append(" [2종 자동]")
                    for c in un2: lines1.append(f"  • {c} 마감")

            pm_text_main = "\n".join(lines1)
            st.markdown("#### 🌇 오후 근무 결과")
            st.code(pm_text_main, language="text")
            clipboard_copy_button("📋 결과 복사하기", pm_text_main)

            # === 출력 2 (비교 블록)
            lines2 = ["🔍 오전 대비 비교:"]
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

            if added:        lines2.append(" • 추가 인원: " + ", ".join(added))
            if missing:      lines2.append(" • 제외 인원: " + ", ".join(missing))
            if newly_joined: lines2.append(" • 신규 도로주행 인원: " + ", ".join(newly_joined))

            pm_text_compare = "\n".join(lines2)
            st.markdown("#### 🔍 비교 결과")
            st.code(pm_text_compare, language="text")
            clipboard_copy_button("📋 비교 결과 복사하기", pm_text_compare)

            # ✅ 전일 저장 (자동)
            if save_check:
                save_json(PREV_FILE, {
                    "열쇠": today_key,
                    "교양_5교시": gy5 or gy4 or gy3 or prev_gyoyang5,
                    "1종수동": (sud_a[-1] if sud_a else prev_sudong)
                })
                st.success("전일근무.json 자동 업데이트 완료 ✅")

        except Exception as e:
            st.error(f"오후 오류: {e}")
