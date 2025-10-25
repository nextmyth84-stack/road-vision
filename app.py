# =====================================
# app.py — 도로주행 근무 자동 배정 v7.42
# =====================================
import streamlit as st
from openai import OpenAI
import base64, re, json, os, difflib, random

# -----------------------
# 헤더 / 제작자 표시
# -----------------------
st.markdown("""
<h3 style='text-align:center; color:#1e3a8a;'>🚗 도로주행 근무 자동 배정 v7.42</h3>
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
# 이름 정규화 / 교정
# -----------------------
def normalize_name(s):
    return re.sub(r"[^가-힣]", "", re.sub(r"\(.*?\)", "", s or ""))

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
# 차량 매칭 / 마킹
# -----------------------
def get_vehicle(name, veh_map):
    nkey = normalize_name(name)
    for car, nm in veh_map.items():
        if normalize_name(nm) == nkey:
            return car
    return ""

def mark_car(car, repair_cars):
    return f"{car}{' (정비)' if car in repair_cars else ''}" if car else ""

def pick_next_from_cycle(cycle, last, allowed_norms: set, exclude_list=None):
    if not cycle:
        return None
    exclude_list = exclude_list or []
    cycle_norm = [normalize_name(x) for x in cycle]
    last_norm = normalize_name(last)
    start = (cycle_norm.index(last_norm) + 1) % len(cycle) if last_norm in cycle_norm else 0
    for i in range(len(cycle) * 2):
        cand = cycle[(start + i) % len(cycle)]
        if normalize_name(cand) not in exclude_list and normalize_name(cand) in allowed_norms:
            return cand
    return None

# -----------------------
# 디렉토리 구조 및 파일 경로
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
    "1종자동": "1종자동순번.json",   # NEW: 1종 자동(차량) 순번
    "정비차량": "정비차량.json"      # NEW: 정비차량 저장소
}
for k, v in files.items():
    files[k] = os.path.join(DATA_DIR, v)
# -----------------------
# 기본 데이터 (최초 생성 시)
# -----------------------
default_data = {
    "열쇠": ["권한솔","김남균","김면정","김성연","김지은","안유미","윤여헌","윤원실","이나래","이호석","조윤영","조정래"],
    "교양": ["권한솔","김남균","김면정","김병욱","김성연","김주현","김지은","안유미","이호석","조정래"],
    "1종":  ["권한솔","김남균","김성연","김주현","이호석","조정래"],
    "veh1": {"2호":"조정래","5호":"권한솔","7호":"김남균","8호":"이호석","9호":"김주현","10호":"김성연"},
    "veh2": {"4호":"김남균","5호":"김병욱","6호":"김지은","12호":"안유미","14호":"김면정","15호":"이호석","17호":"김성연","18호":"권한솔","19호":"김주현","22호":"조정래"},
    "employees": ["권한솔","김남균","김면정","김성연","김지은","안유미","윤여헌","윤원실","이나래","이호석","조윤영","조정래","김병욱","김주현"],
    "1종자동": ["21호","22호","23호","24호"],  # NEW
    "정비차량": {"veh1": [], "veh2": [], "auto1": []}  # NEW
}
for k, path in files.items():
    if not os.path.exists(path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default_data[k], f, ensure_ascii=False, indent=2)
        except Exception as e:
            st.error(f"{path} 초기화 실패: {e}")

# -----------------------
# 데이터 로드
# -----------------------
key_order     = load_json(files["열쇠"])
gyoyang_order = load_json(files["교양"])
sudong_order  = load_json(files["1종"])
veh1_map      = load_json(files["veh1"])
veh2_map      = load_json(files["veh2"])
employee_list = load_json(files["employees"])
auto1_order   = load_json(files["1종자동"]) or []
repair_store  = load_json(files["정비차량"]) or {"veh1": [], "veh2": [], "auto1": []}

# -----------------------
# 전일 근무자 로드/표시/저장
# -----------------------
PREV_FILE = "전일근무.json"
def load_prev_data():
    if os.path.exists(PREV_FILE):
        try:
            with open(PREV_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"열쇠":"", "교양_5교시":"", "1종수동":"", "1종자동":""}

prev_data     = load_prev_data()
prev_key      = prev_data.get("열쇠", "")
prev_gyoyang5 = prev_data.get("교양_5교시", "")
prev_sudong   = prev_data.get("1종수동", "")
prev_auto1    = prev_data.get("1종자동", "")

# -----------------------
# 사이드바 스타일
# -----------------------
st.sidebar.markdown("""
<style>
section[data-testid="stSidebar"] {
    background-color: #f8fafc; padding: 10px; border-right: 1px solid #e5e7eb;
}
.streamlit-expanderHeader { font-weight: 700 !important; color: #1e3a8a !important; font-size: 15px !important; }
textarea, input { font-size: 14px !important; }
div.stButton > button { background-color: #2563eb; color:#fff; border:none; border-radius:8px; padding:6px 12px; margin-top:6px; font-weight:600;}
div.stButton > button:hover { background-color: #1d4ed8; }
.sidebar-subtitle { font-weight:600; color:#334155; margin-top:10px; margin-bottom:4px; }
</style>
""", unsafe_allow_html=True)
st.sidebar.markdown("<h3 style='text-align:center; color:#1e3a8a;'>📂 데이터 관리</h3>", unsafe_allow_html=True)

# -----------------------
# 전일 근무자
# -----------------------
with st.sidebar.expander("🗓 전일 근무자", expanded=True):
    prev_key      = st.text_input("🔑 전일 열쇠 담당", prev_key)
    prev_gyoyang5 = st.text_input("🧑‍🏫 전일 교양(5교시)", prev_gyoyang5)
    prev_sudong   = st.text_input("🚚 전일 1종 수동", prev_sudong)
    prev_auto1    = st.text_input("🚗 전일 1종 자동(차량)", prev_auto1)
    if st.button("💾 전일 근무자 저장"):
        save_json(PREV_FILE, {
            "열쇠": prev_key,
            "교양_5교시": prev_gyoyang5,
            "1종수동": prev_sudong,
            "1종자동": prev_auto1
        })
        st.sidebar.success("전일근무.json 저장 완료 ✅")

# -----------------------
# 순번 관리
# -----------------------
with st.sidebar.expander("🔢 순번표 관리", expanded=False):
    st.markdown("<div class='sidebar-subtitle'>열쇠 순번</div>", unsafe_allow_html=True)
    t1 = st.text_area("", "\n".join(key_order), height=150)
    st.markdown("<div class='sidebar-subtitle'>교양 순번</div>", unsafe_allow_html=True)
    t2 = st.text_area("", "\n".join(gyoyang_order), height=150)
    st.markdown("<div class='sidebar-subtitle'>1종 수동 순번</div>", unsafe_allow_html=True)
    t3 = st.text_area("", "\n".join(sudong_order), height=120)
    st.markdown("<div class='sidebar-subtitle'>1종 자동 순번(차량)</div>", unsafe_allow_html=True)
    t4 = st.text_area("", "\n".join(auto1_order or []), height=100)

    if st.button("💾 순번표 저장"):
        save_json(files["열쇠"],    [x.strip() for x in t1.splitlines() if x.strip()])
        save_json(files["교양"],    [x.strip() for x in t2.splitlines() if x.strip()])
        save_json(files["1종"],     [x.strip() for x in t3.splitlines() if x.strip()])
        save_json(files["1종자동"], [x.strip() for x in t4.splitlines() if x.strip()])
        key_order[:]     = load_json(files["열쇠"])
        gyoyang_order[:] = load_json(files["교양"])
        sudong_order[:]  = load_json(files["1종"])
        auto1_order[:]   = load_json(files["1종자동"])
        st.sidebar.success("순번표 저장 완료 ✅")

# -----------------------
# 차량 담당 관리
# -----------------------
with st.sidebar.expander("🚘 차량 담당 관리", expanded=False):
    st.markdown("<div class='sidebar-subtitle'>1종 수동 차량표</div>", unsafe_allow_html=True)
    tveh1 = st.text_area("", "\n".join([f"{car} {nm}" for car,nm in veh1_map.items()]), height=130)
    st.markdown("<div class='sidebar-subtitle'>2종 자동 차량표</div>", unsafe_allow_html=True)
    tveh2 = st.text_area("", "\n".join([f"{car} {nm}" for car,nm in veh2_map.items()]), height=160)
    if st.button("💾 차량표 저장"):
        v1, v2 = {}, {}
        for line in tveh1.splitlines():
            p = line.strip().split()
            if len(p) >= 2: v1[p[0]] = " ".join(p[1:])
        for line in tveh2.splitlines():
            p = line.strip().split()
            if len(p) >= 2: v2[p[0]] = " ".join(p[1:])
        save_json(files["veh1"], v1); save_json(files["veh2"], v2)
        veh1_map = load_json(files["veh1"]); veh2_map = load_json(files["veh2"])
        st.sidebar.success("차량표 저장 완료 ✅")

# -----------------------
# 정비차량 관리 (멀티선택)
# -----------------------
with st.sidebar.expander("🛠 정비 차량 관리", expanded=False):
    veh1_choices  = sorted(list(veh1_map.keys()))
    veh2_choices  = sorted(list(veh2_map.keys()))
    auto1_choices = auto1_order or []

    sel_veh1  = st.multiselect("1종 수동 정비 차량", veh1_choices, default=repair_store.get("veh1", []))
    sel_veh2  = st.multiselect("2종 자동 정비 차량", veh2_choices, default=repair_store.get("veh2", []))
    sel_auto1 = st.multiselect("1종 자동(차량) 정비 차량", auto1_choices, default=repair_store.get("auto1", []))

    if st.button("💾 정비 차량 저장"):
        new_repair = {"veh1": sel_veh1, "veh2": sel_veh2, "auto1": sel_auto1}
        save_json(files["정비차량"], new_repair)
        repair_store = load_json(files["정비차량"])
        st.sidebar.success("정비 차량 저장 완료 ✅")
        st.sidebar.info(f"현재 정비목록 → 1종:{', '.join(repair_store['veh1']) or '-'} / 2종:{', '.join(repair_store['veh2']) or '-'} / 1종자동:{', '.join(repair_store['auto1']) or '-'}")

# -----------------------
# 기타 설정 (컷오프 제거)
# -----------------------
st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ 추가 설정")
sudong_count = st.sidebar.radio("1종 수동 인원 수", [1, 2], index=0)

st.sidebar.markdown("---")
st.sidebar.markdown("""
<p style='text-align:center; font-size:8px; color:#94a3b8;'>
    powered by <b>wook</b>
</p>
""", unsafe_allow_html=True)

# 세션 갱신
st.session_state.update({
    "key_order": key_order, "gyoyang_order": gyoyang_order, "sudong_order": sudong_order,
    "veh1": veh1_map, "veh2": veh2_map, "employee_list": employee_list,
    "sudong_count": sudong_count,
    "auto1_order": auto1_order,
    "repair_store": repair_store
})
# -----------------------
# 클립보드 버튼
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
# OCR (이름/코스/제외자/지각/조퇴)
# -----------------------
def gpt_extract(img_bytes, want_early=False, want_late=False, want_excluded=False):
    b64 = base64.b64encode(img_bytes).decode()
    user = (
        "이 이미지는 운전면허시험 근무표입니다.\n"
        "1) '학과','기능','초소','PC'는 제외하고 도로주행 근무자만 추출.\n"
        "2) 이름 옆 괄호의 'A-합','B-불','A합','B불'은 코스점검 결과.\n"
        "3) 상단/별도 표기된 '휴가,교육,출장,공가,연가,연차,돌봄' 섹션의 이름을 'excluded' 로 추출.\n"
        "4) '지각/10시 출근/외출' 등 표기에서 오전 시작시간(예:10 또는 10.5)을 late_start 로.\n"
        "5) '조퇴' 표기에서 오후 시간(13/14.5/16 등)을 early_leave 로.\n"
        "JSON 예시: {\"names\":[\"김성연(B합)\"],\"excluded\":[\"안유미\"],\"early_leave\":[{\"name\":\"김병욱\",\"time\":14.5}],\"late_start\":[{\"name\":\"김성연\",\"time\":10}]}\n"
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

        excluded    = js.get("excluded", []) if want_excluded else []
        early_leave = js.get("early_leave", []) if want_early else []
        late_start  = js.get("late_start", []) if want_late else []

        def to_float(x):
            try: return float(x)
            except: return None
        for e in early_leave: e["time"] = to_float(e.get("time"))
        for l in late_start:  l["time"] = to_float(l.get("time"))

        return names, course_records, excluded, early_leave, late_start
    except Exception as e:
        st.error(f"OCR 실패: {e}")
        return [], [], [], [], []

# -----------------------
# 시간 규칙
# -----------------------
def can_attend_period_morning(name_pure: str, period:int, late_list):
    tmap = {1: 9.0, 2: 10.5}
    nn = normalize_name(name_pure)
    for e in late_list or []:
        if normalize_name(e.get("name","")) == nn:
            t = e.get("time", 99) or 99
            try: t = float(t)
            except: t = 99
            return t <= tmap[period]
    return True

def can_attend_period_afternoon(name_pure: str, period:int, early_list):
    tmap = {3: 13.0, 4: 14.5, 5: 16.0}
    nn = normalize_name(name_pure)
    for e in early_list or []:
        if normalize_name(e.get("name","")) == nn:
            t = e.get("time", 0)
            try: t = float(t)
            except: t = 0
            return t > tmap[period]
    return True

# -----------------------
# 탭 구성
# -----------------------
tab1, tab2 = st.tabs(["🌅 오전 근무", "🌇 오후 근무"])

# =====================================
# 🌅 오전 탭
# =====================================
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
                for e in early:
                    e["name"] = correct_name_v2(e.get("name",""), st.session_state["employee_list"])
                for l in late:
                    l["name"] = correct_name_v2(l.get("name",""), st.session_state["employee_list"])

                st.session_state.m_names_raw   = fixed
                st.session_state.course_records = course
                st.session_state.excluded_auto = excluded_fixed
                st.session_state.early_leave   = [e for e in early if e.get("time") is not None]
                st.session_state.late_start    = [l for l in late  if l.get("time") is not None]
                st.success(f"오전 인식 완료 → 근무자 {len(fixed)}명, 제외자 {len(excluded_fixed)}명, 코스 {len(course)}건")

    st.markdown("<h4 style='font-size:16px;'>🚫 근무 제외자 (자동 추출 후 수정 가능)</h4>", unsafe_allow_html=True)
    excluded_text = st.text_area("근무 제외자", "\n".join(st.session_state.get("excluded_auto", [])), height=120)
    excluded_set  = {normalize_name(x) for x in excluded_text.splitlines() if x.strip()}

    st.markdown("<h4 style='font-size:18px;'>🌅 오전 근무자 (수정 가능)</h4>", unsafe_allow_html=True)
    morning_text = st.text_area("오전 근무자", "\n".join(st.session_state.get("m_names_raw", [])), height=220)
    m_list = [x.strip() for x in morning_text.splitlines() if x.strip()]

    early_leave = st.session_state.get("early_leave", [])
    late_start  = st.session_state.get("late_start", [])
    m_norms = {normalize_name(x) for x in m_list} - excluded_set
    # -----------------------
    # 🚗 오전 근무 배정
    # -----------------------
    if st.button("📋 오전 배정 생성"):
        try:
            key_order     = st.session_state.get("key_order", [])
            gyoyang_order = st.session_state.get("gyoyang_order", [])
            sudong_order  = st.session_state.get("sudong_order", [])
            veh1_map      = st.session_state.get("veh1", {})
            veh2_map      = st.session_state.get("veh2", {})
            sudong_count  = st.session_state.get("sudong_count", 1)
            auto1_order   = st.session_state.get("auto1_order", []) or []
            repair_store  = st.session_state.get("repair_store", {"veh1":[], "veh2":[], "auto1":[]})

            # 전일 데이터
            PREV_FILE = "전일근무.json"
            prev_data = load_json(PREV_FILE, {"열쇠":"","교양_5교시":"","1종수동":"","1종자동":""})
            prev_key      = prev_data.get("열쇠","")
            prev_gyoyang5 = prev_data.get("교양_5교시","")
            prev_sudong   = prev_data.get("1종수동","")
            prev_auto1    = prev_data.get("1종자동","")

            # 🔑 열쇠
            today_key = ""
            if key_order:
                norm_list = [normalize_name(x) for x in key_order if normalize_name(x) not in excluded_set]
                prev_norm = normalize_name(prev_key)
                if prev_norm in norm_list:
                    idx = (norm_list.index(prev_norm) + 1) % len(norm_list)
                    today_key = [x for x in key_order if normalize_name(x) == norm_list[idx]][0]
                elif norm_list:
                    today_key = [x for x in key_order if normalize_name(x) == norm_list[0]][0]
            st.session_state.today_key = today_key

            # 🧑‍🏫 교양 1·2교시 (지각 반영)
            gy1 = pick_next_from_cycle(gyoyang_order, prev_gyoyang5, m_norms)
            if gy1 and not can_attend_period_morning(gy1, 1, late_start):
                gy1 = pick_next_from_cycle(gyoyang_order, gy1, m_norms)
            used_norm = {normalize_name(gy1)} if gy1 else set()
            gy2 = pick_next_from_cycle(gyoyang_order, gy1 or prev_gyoyang5, m_norms - used_norm)
            st.session_state.gyoyang_base_for_pm = gy2 if gy2 else prev_gyoyang5

            # 🚚 1종 수동
            sud_m, last = [], prev_sudong
            for _ in range(sudong_count):
                pick = pick_next_from_cycle(sudong_order, last, m_norms - {normalize_name(x) for x in sud_m})
                if not pick: break
                sud_m.append(pick); last = pick
            st.session_state.sudong_base_for_pm = sud_m[-1] if sud_m else prev_sudong

            # 🚗 2종 자동(사람)
            sud_norms = {normalize_name(x) for x in sud_m}
            auto_m = [x for x in m_list if normalize_name(x) in (m_norms - sud_norms)]

            # === NEW: 1종 자동 차량 순번 (정비차량 제외하며 순번 회전)
            today_auto1 = ""
            if auto1_order:
                # 순회하면서 정비(auto1) 목록에 없는 차만 선택
                if prev_auto1 in auto1_order:
                    start = (auto1_order.index(prev_auto1) + 1) % len(auto1_order)
                else:
                    start = 0
                for i in range(len(auto1_order)):
                    cand = auto1_order[(start + i) % len(auto1_order)]
                    if cand not in (repair_store.get("auto1") or []):
                        today_auto1 = cand
                        break
            st.session_state.today_auto1 = today_auto1  # ''일수도 있음

            # === 차량 배정(정비 대체: 1·2종은 랜덤 대체)
            used_veh1, used_veh2 = set(), set()
            veh1_all = list(veh1_map.keys())
            veh2_all = list(veh2_map.keys())
            veh1_repair = set(repair_store.get("veh1") or [])
            veh2_repair = set(repair_store.get("veh2") or [])

            # 오전 1종수동 차량 배정
            sud_m_with_car = []
            for nm in sud_m:
                base = get_vehicle(nm, veh1_map)
                if base and base not in veh1_repair and base not in used_veh1:
                    car = base
                else:
                    # 랜덤 대체
                    candidates = [c for c in veh1_all if c not in veh1_repair and c not in used_veh1]
                    car = random.choice(candidates) if candidates else ""
                if car: used_veh1.add(car)
                sud_m_with_car.append((nm, car))

            # 오전 2종자동 차량 배정
            auto_m_with_car = []
            for nm in auto_m:
                base = get_vehicle(nm, veh2_map)
                if base and base not in veh2_repair and base not in used_veh2:
                    car = base
                else:
                    candidates = [c for c in veh2_all if c not in veh2_repair and c not in used_veh2]
                    car = random.choice(candidates) if candidates else ""
                if car: used_veh2.add(car)
                auto_m_with_car.append((nm, car))

            # 오전 차량 기록(오전-오후 비교용)
            st.session_state.morning_assigned_cars_1 = list(used_veh1)
            st.session_state.morning_assigned_cars_2 = list(used_veh2)
            st.session_state.morning_auto_names    = auto_m + sud_m

            # === 출력 구성
            lines = []
            if today_key:
                lines.append(f"열쇠: {today_key}")
                lines.append("")
            if gy1: lines.append(f"1교시: {gy1}")
            if gy2: lines.append(f"2교시: {gy2}")
            if gy1 or gy2: lines.append("")

            if sud_m_with_car:
                for nm, car in sud_m_with_car:
                    if car: lines.append(f"1종수동: {car} {nm}")
                    else:   lines.append(f"1종수동: {nm}")
                if sudong_count == 2 and len(sud_m_with_car) < 2:
                    lines.append("※ 수동 가능 인원이 1명입니다.")
            else:
                lines.append("1종수동: (배정자 없음)")
                if sudong_count >= 1:
                    lines.append("※ 수동 가능 인원이 0명입니다.")

            # 1종 자동 차량(차량 순번)
            if today_auto1:
                lines.append("")
                lines.append(f"1종자동: {today_auto1}")
                lines.append("")

            if auto_m_with_car:
                lines.append("2종자동:")
                for nm, car in auto_m_with_car:
                    if car: lines.append(f" • {car} {nm}")
                    else:   lines.append(f" • {nm}")

            # 코스점검
            course_records = st.session_state.get("course_records", [])
            if course_records:
                lines.append("")
                lines.append(" 코스점검 :")
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
# 🌇 오후 탭 (최종)
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
                names, _, excluded, early, late = gpt_extract(
                    a_file.read(), want_early=True, want_late=True, want_excluded=True
                )
                fixed = [correct_name_v2(n, st.session_state["employee_list"]) for n in names]
                excluded_fixed = [correct_name_v2(n, st.session_state["employee_list"]) for n in excluded]
                for e in early: e["name"] = correct_name_v2(e.get("name",""), st.session_state["employee_list"])
                for l in late:  l["name"] = correct_name_v2(l.get("name",""), st.session_state["employee_list"])

                st.session_state.a_names_raw     = fixed
                st.session_state.excluded_auto_pm = excluded_fixed
                st.session_state.early_leave_pm   = [e for e in early if e.get("time") is not None]
                st.session_state.late_start_pm    = [l for l in late  if l.get("time") is not None]
                st.success(f"오후 인식 완료 → 근무자 {len(fixed)}명, 제외자 {len(excluded_fixed)}명")

    st.markdown("<h4 style='font-size:18px;'>🌇 오후 근무자 (수정 가능)</h4>", unsafe_allow_html=True)
    afternoon_text = st.text_area("오후 근무자", "\n".join(st.session_state.get("a_names_raw", [])), height=220)
    a_list  = [x.strip() for x in afternoon_text.splitlines() if x.strip()]
    excluded_set = {normalize_name(x) for x in st.session_state.get("excluded_auto", [])}
    a_norms = {normalize_name(x) for x in a_list} - excluded_set

    save_check = st.checkbox("전일근무자(열쇠,5교시,1종수동,1종자동) 자동 저장", value=True)

    # -------------------------------
    # 🚗 오후 배정 생성
    # -------------------------------
    if st.button("📋 오후 배정 생성"):
        try:
            # 기본 세팅
            gyoyang_order = st.session_state.get("gyoyang_order", [])
            sudong_order  = st.session_state.get("sudong_order", [])
            veh1_map      = st.session_state.get("veh1", {})
            veh2_map      = st.session_state.get("veh2", {})
            sudong_count  = st.session_state.get("sudong_count", 1)
            auto1_order   = st.session_state.get("auto1_order", []) or []
            repair_store  = st.session_state.get("repair_store", {"veh1":[], "veh2":[], "auto1":[]})

            # 전일 + 오전 데이터
            prev_data = load_json("전일근무.json", {"열쇠":"","교양_5교시":"","1종수동":"","1종자동":""})
            today_key = st.session_state.get("today_key", prev_data["열쇠"])
            gy_start  = st.session_state.get("gyoyang_base_for_pm", prev_data["교양_5교시"]) or (gyoyang_order[0] if gyoyang_order else "")
            sud_base  = st.session_state.get("sudong_base_for_pm", prev_data["1종수동"])
            today_auto1 = st.session_state.get("today_auto1", prev_data["1종자동"])

            early_leave = st.session_state.get("early_leave", [])

            # 🧑‍🏫 교양(3~5교시)
            used = set()
            gy3 = gy4 = gy5 = None
            last_ptr = gy_start
            for period in [3,4,5]:
                while True:
                    pick = pick_next_from_cycle(gyoyang_order, last_ptr, a_norms - used)
                    if not pick: break
                    last_ptr = pick
                    if can_attend_period_afternoon(pick, period, early_leave):
                        if period == 3: gy3 = pick
                        elif period == 4: gy4 = pick
                        else: gy5 = pick
                        used.add(normalize_name(pick))
                        break

            # 🚚 1종 수동
            sud_a, last = [], sud_base
            for _ in range(sudong_count):
                pick = pick_next_from_cycle(sudong_order, last, a_norms)
                if not pick: break
                sud_a.append(pick); last = pick

            # 🚗 2종 자동(사람)
            sud_a_norms = {normalize_name(x) for x in sud_a}
            auto_a = [x for x in a_list if normalize_name(x) in (a_norms - sud_a_norms)]

            # === 차량 배정 (정비 대체 포함)
            used_veh1, used_veh2 = set(), set()
            veh1_all = list(veh1_map.keys())
            veh2_all = list(veh2_map.keys())
            veh1_repair = set(repair_store.get("veh1") or [])
            veh2_repair = set(repair_store.get("veh2") or [])

            # 1종 수동
            sud_a_with_car = []
            for nm in sud_a:
                base = get_vehicle(nm, veh1_map)
                if base and base not in veh1_repair and base not in used_veh1:
                    car = base
                else:
                    cands = [c for c in veh1_all if c not in veh1_repair and c not in used_veh1]
                    car = random.choice(cands) if cands else ""
                if car: used_veh1.add(car)
                sud_a_with_car.append((nm, car))

            # 2종 자동
            auto_a_with_car = []
            for nm in auto_a:
                base = get_vehicle(nm, veh2_map)
                if base and base not in veh2_repair and base not in used_veh2:
                    car = base
                else:
                    cands = [c for c in veh2_all if c not in veh2_repair and c not in used_veh2]
                    car = random.choice(cands) if cands else ""
                if car: used_veh2.add(car)
                auto_a_with_car.append((nm, car))

            # 🚫 마감차량 계산
            am_c1 = set(st.session_state.get("morning_assigned_cars_1", []))
            am_c2 = set(st.session_state.get("morning_assigned_cars_2", []))
            pm_c1 = {c for _, c in sud_a_with_car if c}
            pm_c2 = {c for _, c in auto_a_with_car if c}
            un1 = sorted([c for c in am_c1 if c and c not in pm_c1])
            un2 = sorted([c for c in am_c2 if c and c not in pm_c2])

            # -----------------------------
            # 🟩 1️⃣ 블록 — 오후 근무 결과
            # -----------------------------
            lines = []

            # 🔑 열쇠 (위에 한 줄 띄움)
            lines.append("")  
            if today_key:
                lines.append(f"열쇠: {today_key}")
                lines.append("")

            # 🧑‍🏫 교양
            if gy3: lines.append(f"3교시: {gy3}")
            if gy4: lines.append(f"4교시: {gy4}")
            if gy5:
                lines.append(f"5교시: {gy5}")
                lines.append("")

            # 🚚 1종 수동
            if sud_a_with_car:
                for nm, car in sud_a_with_car:
                    if car: lines.append(f"1종수동: {car} {nm}")
                    else:   lines.append(f"1종수동: {nm}")
            else:
                lines.append("1종수동: (배정자 없음)")

            # 🚗 1종 자동
            if today_auto1:
                lines.append("")
                lines.append(f"1종자동: {today_auto1}")

            # 🚙 2종 자동 (위에 한 줄 띄움)
            if auto_a_with_car:
                lines.append("")
                lines.append("2종자동:")
                for nm, car in auto_a_with_car:
                    if car: lines.append(f" • {car} {nm}")
                    else:   lines.append(f" • {nm}")

            # 🚫 마감 차량
            if un1 or un2:
                lines.append("")
                lines.append("🚫 마감 차량:")
                if un1:
                    lines.append(" [1종 수동]")
                    for c in un1: lines.append(f"  • {c} 마감")
                if un2:
                    lines.append(" [2종 자동]")
                    for c in un2: lines.append(f"  • {c} 마감")



            
            # -----------------------------
            # 🟦 2️⃣ 블록 — 오전 대비 비교
            # -----------------------------
            lines2 = []
            morning_auto_names = set(st.session_state.get("morning_auto_names", []))
            afternoon_auto_names = {normalize_name(nm) for nm, _ in auto_a_with_car}
            afternoon_sudong_norms = {normalize_name(nm) for nm, _ in sud_a_with_car}

            added   = sorted([x for x in afternoon_auto_names - {normalize_name(y) for y in morning_auto_names}])
            missing = sorted([
                nm for nm in morning_auto_names
                if normalize_name(nm) not in afternoon_auto_names
                and normalize_name(nm) not in afternoon_sudong_norms
            ])

            lines2.append("🔍 오전 대비 비교:")
            if added:   lines2.append(" • 추가 인원: " + ", ".join(added))
            if missing: lines2.append(" • 제외 인원: " + ", ".join(missing))

            pm_compare_text = "\n".join(lines2).strip()
            st.markdown("#### 🔍 오전 대비 비교")
            st.code(pm_compare_text, language="text")
            clipboard_copy_button("📋 상세 복사하기", pm_compare_text)

            # ✅ 전일 저장
            if save_check:
                save_json("전일근무.json", {
                    "열쇠": today_key,
                    "교양_5교시": gy5 or gy4 or gy3 or prev_data["교양_5교시"],
                    "1종수동": (sud_a[-1] if sud_a else prev_data["1종수동"]),
                    "1종자동": today_auto1
                })
                st.success("전일근무.json 업데이트 완료 ✅")

        except Exception as e:
            st.error(f"오후 오류: {e}")
