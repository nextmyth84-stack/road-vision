# =====================================
# app.py — 도로주행 근무 자동 배정 v7.43 (정비차량 랜덤대체 완전본)
# =====================================
import streamlit as st
from openai import OpenAI
import base64, re, json, os, difflib, random

# -----------------------
# 헤더
# -----------------------
st.set_page_config(page_title="도로주행 근무 자동 배정 v7.43", layout="wide")
st.markdown("""
<h3 style='text-align:center; color:#1e3a8a; margin-bottom:4px;'>🚗 도로주행 근무 자동 배정 v7.43</h3>
<p style='text-align:center; font-size:10px; color:#64748b; margin-top:-6px;'>
    developed by <b>wook</b>
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
# 복사 버튼
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
          setTimeout(()=>b.innerText=t, 1600);
        }}catch(e){{
          alert('복사가 제한된 환경입니다. 텍스트를 길게 눌러 복사하세요.');
        }}
      }});
    }})();
    </script>
    """
    st.components.v1.html(html, height=52)

# -----------------------
# 이름 정규화 / 차량 / 순환 / 교정
# -----------------------
def normalize_name(s): return re.sub(r"[^가-힣]", "", re.sub(r"\(.*?\)", "", s or ""))

def get_vehicle(name, veh_map):
    nkey = normalize_name(name)
    for car, nm in veh_map.items():
        if normalize_name(nm) == nkey:
            return car
    return ""

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
# 정비 차량 랜덤 대체 함수 ✅
# -----------------------
def assign_vehicle_with_repair_check(name, veh_map, repair_cars, already_assigned):
    """
    이름 기준으로 차량을 배정하되,
    해당 차량이 정비 중이면 같은 종별 내 미배정 차량 중 랜덤으로 대체.
    """
    original = get_vehicle(name, veh_map)
    # 정비차량이 아닐 경우 그대로 반환
    if not original or original not in repair_cars:
        if original:
            already_assigned.add(original)
        return original

    # 정비차량이면 랜덤 대체
    available = [v for v in veh_map.keys() if v not in repair_cars and v not in already_assigned]
    if not available:
        return f"{original} (정비중)"
    alt = random.choice(available)
    already_assigned.add(alt)
    return f"{alt} (정비대체)"
# -----------------------
# OCR (이름/코스/제외자/지각/조퇴)
# -----------------------
def gpt_extract(img_bytes, want_early=False, want_late=False, want_excluded=False):
    """
    반환: names(괄호 제거), course_records, excluded, early_leave, late_start
    - course_records = [{name,'A코스'/'B코스','합격'/'불합격'}]
    - excluded = ["김OO", ...]
    - early_leave = [{"name":"김OO","time":14.5}, ...]
    - late_start  = [{"name":"김OO","time":10.0}, ...]
    """
    b64 = base64.b64encode(img_bytes).decode()
    user = (
        "이 이미지는 운전면허시험 근무표입니다.\n"
        "1) '학과','기능','초소','PC'는 제외하고 도로주행 근무자만 추출.\n"
        "2) 이름 옆 괄호의 'A-합','B-불','A합','B불'은 코스점검 결과.\n"
        "3) 상단/별도 표기된 '휴가,교육,출장,공가,연가,연차,돌봄' 섹션의 이름을 'excluded' 로 추출.\n"
        "4) '지각/10시 출근/외출' 표기에서 오전 시작시간(예:10/10.5)을 late_start 로.\n"
        "5) '조퇴' 표기에서 오후 시간(13/14.5/16 등)을 early_leave 로.\n"
        "JSON 예시: {\"names\":[\"김성연(B합)\"],\"excluded\":[\"안유미\"],"
        "\"early_leave\":[{\"name\":\"김병욱\",\"time\":14.5}],"
        "\"late_start\":[{\"name\":\"김성연\",\"time\":10}]}"
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
                names.append(name)  # 괄호 제거 저장
            else:
                names.append(n.strip())

        excluded = js.get("excluded", []) if want_excluded else []
        early_leave = js.get("early_leave", []) if want_early else []
        late_start  = js.get("late_start",  []) if want_late  else []

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
# 교양 시간 제한
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
# JSON 기반 순번 / 차량 / 근무자 관리
# -----------------------
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
files = {
    "열쇠": "열쇠순번.json",
    "교양": "교양순번.json",
    "1종":  "1종순번.json",
    "veh1": "1종차량표.json",
    "veh2": "2종차량표.json",
    "employees": "전체근무자.json"
}
for k, v in files.items():
    files[k] = os.path.join(DATA_DIR, v)

default_data = {
    "열쇠": ["권한솔","김남균","김면정","김성연","김지은","안유미","윤여헌","윤원실","이나래","이호석","조윤영","조정래"],
    "교양": ["권한솔","김남균","김면정","김병욱","김성연","김주현","김지은","안유미","이호석","조정래"],
    "1종":  ["권한솔","김남균","김성연","김주현","이호석","조정래"],
    "veh1": {"2호":"조정래","5호":"권한솔","7호":"김남균","8호":"이호석","9호":"김주현","10호":"김성연"},
    "veh2": {"4호":"김남균","5호":"김병욱","6호":"김지은","12호":"안유미","14호":"김면정","15호":"이호석","17호":"김성연","18호":"권한솔","19호":"김주현","22호":"조정래"},
    "employees": ["권한솔","김남균","김면정","김성연","김지은","안유미","윤여헌","윤원실","이나래","이호석","조윤영","조정래","김병욱","김주현"]
}
for k, v in files.items():
    if not os.path.exists(v):
        save_json(v, default_data[k])

# 로드
key_order     = load_json(files["열쇠"])
gyoyang_order = load_json(files["교양"])
sudong_order  = load_json(files["1종"])
veh1_map      = load_json(files["veh1"])
veh2_map      = load_json(files["veh2"])
employee_list = load_json(files["employees"])

# -----------------------
# 전일 근무자 로드/저장
# -----------------------
PREV_FILE = "전일근무.json"
def load_prev():
    if os.path.exists(PREV_FILE):
        try:
            with open(PREV_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"열쇠":"", "교양_5교시":"", "1종수동":""}

prev = load_prev()
prev_key       = prev.get("열쇠","")
prev_gyoyang5  = prev.get("교양_5교시","")
prev_sudong    = prev.get("1종수동","")

# -----------------------
# 사이드바 (디자인 + 입력)
# -----------------------
st.sidebar.markdown("""
<style>
section[data-testid="stSidebar"]{background:#f8fafc;padding:10px;border-right:1px solid #e5e7eb;}
.streamlit-expanderHeader{font-weight:700 !important;color:#1e3a8a !important;font-size:15px !important;}
textarea,input{font-size:14px !important;}
div.stButton > button{background:#2563eb;color:#fff;border:none;border-radius:8px;padding:6px 12px;margin-top:6px;font-weight:600;}
div.stButton > button:hover{background:#1d4ed8;}
.sidebar-subtitle{font-weight:600;color:#334155;margin-top:10px;margin-bottom:4px;}
</style>
""", unsafe_allow_html=True)

st.sidebar.markdown("<h3 style='text-align:center; color:#1e3a8a;'>📂 데이터 관리</h3>", unsafe_allow_html=True)

with st.sidebar.expander("🗓 전일 근무자", expanded=True):
    prev_key      = st.text_input("🔑 전일 열쇠", prev_key)
    prev_gyoyang5 = st.text_input("🧑‍🏫 전일 교양(5교시)", prev_gyoyang5)
    prev_sudong   = st.text_input("🚚 전일 1종 수동", prev_sudong)
    if st.button("💾 전일 근무자 저장"):
        save_json(PREV_FILE, {"열쇠":prev_key,"교양_5교시":prev_gyoyang5,"1종수동":prev_sudong})
        st.sidebar.success("전일근무.json 저장 완료 ✅")

with st.sidebar.expander("🔢 순번표 관리", expanded=False):
    st.markdown("<div class='sidebar-subtitle'>열쇠 순번</div>", unsafe_allow_html=True)
    t1 = st.text_area("", "\n".join(key_order), height=150)
    st.markdown("<div class='sidebar-subtitle'>교양 순번</div>", unsafe_allow_html=True)
    t2 = st.text_area("", "\n".join(gyoyang_order), height=150)
    st.markdown("<div class='sidebar-subtitle'>1종 수동 순번</div>", unsafe_allow_html=True)
    t3 = st.text_area("", "\n".join(sudong_order), height=120)
    if st.button("💾 순번표 저장"):
        save_json(files["열쇠"], [x.strip() for x in t1.splitlines() if x.strip()])
        save_json(files["교양"], [x.strip() for x in t2.splitlines() if x.strip()])
        save_json(files["1종"],  [x.strip() for x in t3.splitlines() if x.strip()])
        st.sidebar.success("순번표 저장 완료 ✅")

with st.sidebar.expander("🚘 차량 담당 관리", expanded=False):
    st.markdown("<div class='sidebar-subtitle'>1종 수동 차량표</div>", unsafe_allow_html=True)
    tveh1 = st.text_area("", "\n".join([f"{car} {nm}" for car, nm in veh1_map.items()]), height=130)
    st.markdown("<div class='sidebar-subtitle'>2종 자동 차량표</div>", unsafe_allow_html=True)
    tveh2 = st.text_area("", "\n".join([f"{car} {nm}" for car, nm in veh2_map.items()]), height=160)
    if st.button("💾 차량표 저장"):
        v1, v2 = {}, {}
        for line in tveh1.splitlines():
            p = line.strip().split()
            if len(p) >= 2: v1[p[0]] = " ".join(p[1:])
        for line in tveh2.splitlines():
            p = line.strip().split()
            if len(p) >= 2: v2[p[0]] = " ".join(p[1:])
        save_json(files["veh1"], v1); save_json(files["veh2"], v2)
        st.sidebar.success("차량표 저장 완료 ✅")

with st.sidebar.expander("👥 전체 근무자", expanded=False):
    st.markdown("<div class='sidebar-subtitle'>근무자 목록</div>", unsafe_allow_html=True)
    tall = st.text_area("", "\n".join(employee_list), height=180)
    if st.button("💾 근무자 저장"):
        save_json(files["employees"], [x.strip() for x in tall.splitlines() if x.strip()])
        st.sidebar.success("근무자 명단 저장 완료 ✅")

st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ 추가 설정")
sudong_count = st.sidebar.radio("1종 수동 인원 수", [1, 2], index=0)
# ⚙️ 추가 설정
st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ 추가 설정")

# 1종 수동 인원 수 설정
sudong_count = st.sidebar.radio("1종 수동 인원 수", [1, 2], index=0)

# 🚗 정비 차량 선택 (1종·2종 차량 전체 목록에서 선택)
all_cars = sorted(list(set(
    list(st.session_state["veh1"].keys()) + list(st.session_state["veh2"].keys())
)))
repair_cars = st.sidebar.multiselect("정비 차량 선택", options=all_cars, default=[])

# 👇 제작자 표시
st.sidebar.markdown("---")
st.sidebar.markdown("""
<p style='text-align:center; font-size:10px; color:#94a3b8;'>
    powered by <b>wook</b>
</p>
""", unsafe_allow_html=True)


# 아래 제작자 표시
st.sidebar.markdown("---")
st.sidebar.markdown("<p style='text-align:center; font-size:10px; color:#94a3b8;'>powered by <b>wook</b></p>", unsafe_allow_html=True)

# 세션 최신화
st.session_state.update({
    "key_order": key_order, "gyoyang_order": gyoyang_order, "sudong_order": sudong_order,
    "veh1": veh1_map, "veh2": veh2_map, "employee_list": employee_list,
    "sudong_count": sudong_count, "repair_cars": repair_cars
})
# -----------------------
# 탭 UI 구성
# -----------------------
tab1, tab2 = st.tabs(["🌅 오전 근무", "🌇 오후 근무"])
st.markdown("""
<style>
.stTabs [data-baseweb="tab-list"] { gap:12px; }
.stTabs [data-baseweb="tab"] { font-size:18px; padding:14px 36px; border-radius:10px 10px 0 0; background:#d1d5db; }
.stTabs [aria-selected="true"] { background:#2563eb !important; color:white !important; font-weight:700; }
</style>
""", unsafe_allow_html=True)

# =====================================
# 🌅 오전 근무 탭
# =====================================
with tab1:
    st.markdown("<h4>1️⃣ 오전 근무표 업로드 & OCR</h4>", unsafe_allow_html=True)
    m_file = st.file_uploader("📸 오전 근무표 업로드", type=["png","jpg","jpeg"], key="m_upload")

    if st.button("오전 GPT 인식"):
        if not m_file:
            st.warning("오전 이미지를 업로드하세요.")
        else:
            with st.spinner("🧩 GPT 이미지 분석 중..."):
                names, course, excluded, early, late = gpt_extract(
                    m_file.read(), want_early=True, want_late=True, want_excluded=True
                )
                fixed = [correct_name_v2(n, employee_list) for n in names]
                excluded_fixed = [correct_name_v2(n, employee_list) for n in excluded]
                for e in early: e["name"] = correct_name_v2(e.get("name",""), employee_list)
                for l in late:  l["name"] = correct_name_v2(l.get("name",""), employee_list)

                st.session_state.m_names_raw = fixed
                st.session_state.course_records = course
                st.session_state.excluded_auto = excluded_fixed
                st.session_state.early_leave = [e for e in early if e.get("time")]
                st.session_state.late_start = [l for l in late if l.get("time")]
                st.success(f"오전 인식 완료 → 근무자 {len(fixed)}명, 제외자 {len(excluded_fixed)}명")

    excluded_text = st.text_area("🚫 근무 제외자", "\n".join(st.session_state.get("excluded_auto", [])), height=120)
    excluded_set = {normalize_name(x) for x in excluded_text.splitlines() if x.strip()}

    st.markdown("### 🌅 오전 근무자 (수정 가능)")
    morning_text = st.text_area("오전 근무자", "\n".join(st.session_state.get("m_names_raw", [])), height=220)
    m_list = [x.strip() for x in morning_text.splitlines() if x.strip()]

    early_leave = st.session_state.get("early_leave", [])
    late_start  = st.session_state.get("late_start", [])
    m_norms = {normalize_name(x) for x in m_list} - excluded_set

    st.markdown("### 🚗 오전 근무 배정")
    if st.button("📋 오전 배정 생성"):
        try:
            key_order = st.session_state["key_order"]
            gyoyang_order = st.session_state["gyoyang_order"]
            sudong_order = st.session_state["sudong_order"]
            veh1_map = st.session_state["veh1"]
            veh2_map = st.session_state["veh2"]
            repair_cars = st.session_state["repair_cars"]
            sudong_count = st.session_state["sudong_count"]

            # 🔑 열쇠 순번
            today_key = ""
            if key_order:
                norm_list = [normalize_name(x) for x in key_order if normalize_name(x) not in excluded_set]
                prev_norm = normalize_name(prev_key)
                if prev_norm in norm_list:
                    idx = (norm_list.index(prev_norm) + 1) % len(norm_list)
                    today_key = [x for x in key_order if normalize_name(x) == norm_list[idx]][0]
                elif norm_list:
                    today_key = [x for x in key_order if normalize_name(x) == norm_list[0]][0]

            # 🧑‍🏫 교양 1·2교시
            def pick_next_from_cycle(cycle, last, allowed_norms: set):
                if not cycle: return None
                cycle_norm = [normalize_name(x) for x in cycle]
                last_norm = normalize_name(last)
                start = (cycle_norm.index(last_norm)+1)%len(cycle) if last_norm in cycle_norm else 0
                for i in range(len(cycle)*2):
                    cand = cycle[(start+i)%len(cycle)]
                    if normalize_name(cand) in allowed_norms:
                        return cand
                return None

            gy1 = pick_next_from_cycle(gyoyang_order, prev_gyoyang5, m_norms)
            if gy1 and not can_attend_period_morning(gy1,1,late_start):
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

            # 🚗 2종 자동
            sud_norms = {normalize_name(x) for x in sud_m}
            auto_m = [x for x in m_list if normalize_name(x) in (m_norms - sud_norms)]

            # 차량 배정 (정비랜덤)
            assigned_cars_1, assigned_cars_2 = set(), set()
            st.session_state.morning_assigned_cars_1 = []
            st.session_state.morning_assigned_cars_2 = []

            for nm in sud_m:
                car = assign_vehicle_with_repair_check(nm, veh1_map, repair_cars, assigned_cars_1)
                st.session_state.morning_assigned_cars_1.append(car)

            for nm in auto_m:
                car = assign_vehicle_with_repair_check(nm, veh2_map, repair_cars, assigned_cars_2)
                st.session_state.morning_assigned_cars_2.append(car)

            st.session_state.morning_auto_names = auto_m + sud_m

            # === 출력 ===
            lines = []
            if today_key: lines.append(f"열쇠: {today_key}\n")
            if gy1: lines.append(f"1교시: {gy1}")
            if gy2: lines.append(f"2교시: {gy2}\n")

            for i, nm in enumerate(sud_m):
                lines.append(f"1종수동: {st.session_state.morning_assigned_cars_1[i]} {nm}")
            if auto_m:
                lines.append("\n1종자동:")
                for i, nm in enumerate(auto_m):
                    lines.append(f" {st.session_state.morning_assigned_cars_2[i]} {nm}")

            lines.append("\n코스점검:")
            for c in ["A","B"]:
                passed = [r["name"] for r in st.session_state.get("course_records",[]) if r["course"]==f"{c}코스" and r["result"]=="합격"]
                failed = [r["name"] for r in st.session_state.get("course_records",[]) if r["course"]==f"{c}코스" and r["result"]=="불합격"]
                if passed: lines.append(f" • {c}코스 합격: {', '.join(passed)}")
                if failed: lines.append(f" • {c}코스 불합격: {', '.join(failed)}")

            am_text = "\n".join(lines)
            st.markdown("#### 📋 오전 결과")
            st.code(am_text, language="text")
            clipboard_copy_button("📋 복사", am_text)

        except Exception as e:
            st.error(f"오전 오류: {e}")
# =====================================
# 🌇 오후 근무 탭
# =====================================
with tab2:
    st.markdown("<h4>2️⃣ 오후 근무표 업로드 & OCR</h4>", unsafe_allow_html=True)
    a_file = st.file_uploader("📸 오후 근무표 업로드", type=["png","jpg","jpeg"], key="a_upload")

    if st.button("오후 GPT 인식"):
        if not a_file:
            st.warning("오후 이미지를 업로드하세요.")
        else:
            with st.spinner("🧩 GPT 이미지 분석 중..."):
                names, _, excluded, early, late = gpt_extract(
                    a_file.read(), want_early=True, want_late=True, want_excluded=True
                )
                fixed = [correct_name_v2(n, employee_list) for n in names]
                excluded_fixed = [correct_name_v2(n, employee_list) for n in excluded]
                for e in early: e["name"] = correct_name_v2(e.get("name",""), employee_list)
                for l in late:  l["name"] = correct_name_v2(l.get("name",""), employee_list)

                st.session_state.a_names_raw = fixed
                st.session_state.excluded_auto_pm = excluded_fixed
                st.session_state.early_leave_pm = [e for e in early if e.get("time")]
                st.session_state.late_start_pm = [l for l in late if l.get("time")]
                st.success(f"오후 인식 완료 → 근무자 {len(fixed)}명, 제외자 {len(excluded_fixed)}명")

    st.markdown("### 🌇 오후 근무자 (수정 가능)")
    afternoon_text = st.text_area("오후 근무자", "\n".join(st.session_state.get("a_names_raw", [])), height=220)
    a_list = [x.strip() for x in afternoon_text.splitlines() if x.strip()]

    # 제외자 (오전 자동추출 유지)
    excluded_set = {normalize_name(x) for x in st.session_state.get("excluded_auto", [])}
    a_norms = {normalize_name(x) for x in a_list} - excluded_set

    save_check = st.checkbox("전일근무자(열쇠·5교시·1종수동) 자동 저장", value=True)

    st.markdown("### 🚘 오후 근무 배정")
    if st.button("📋 오후 배정 생성"):
        try:
            gyoyang_order = st.session_state["gyoyang_order"]
            sudong_order  = st.session_state["sudong_order"]
            veh1_map      = st.session_state["veh1"]
            veh2_map      = st.session_state["veh2"]
            sudong_count  = st.session_state["sudong_count"]
            repair_cars   = st.session_state["repair_cars"]

            today_key = st.session_state.get("today_key", prev_key)
            gy_start  = st.session_state.get("gyoyang_base_for_pm", prev_gyoyang5) or (gyoyang_order[0] if gyoyang_order else "")
            sud_base  = st.session_state.get("sudong_base_for_pm", prev_sudong)

            early_leave = st.session_state.get("early_leave", [])

            # 🧑‍🏫 교양 3~5교시 (조퇴 반영)
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

            # 🚚 1종 수동 (정비랜덤 보정 적용은 아래 차량 배정 단계에서)
            sud_a, last = [], sud_base
            for _ in range(sudong_count):
                pick = pick_next_from_cycle(sudong_order, last, a_norms)
                if not pick: break
                sud_a.append(pick); last = pick

            # 🚗 2종 자동 (1종 제외)
            sud_a_norms = {normalize_name(x) for x in sud_a}
            auto_a = [x for x in a_list if normalize_name(x) in (a_norms - sud_a_norms)]

            # === 차량 배정 (정비 차량 랜덤 대체) ===
            assigned_cars_1, assigned_cars_2 = set(), set()
            pm_cars_1, pm_cars_2 = [], []

            for nm in sud_a:
                car = assign_vehicle_with_repair_check(nm, veh1_map, repair_cars, assigned_cars_1)
                pm_cars_1.append(car)

            for nm in auto_a:
                car = assign_vehicle_with_repair_check(nm, veh2_map, repair_cars, assigned_cars_2)
                pm_cars_2.append(car)

            # === 출력 블록 1: 열쇠~미배정차량까지 ===
            lines1 = []
            if today_key: lines1.append(f"열쇠: {today_key}\n")
            if gy3: lines1.append(f"3교시: {gy3}")
            if gy4: lines1.append(f"4교시: {gy4}")
            if gy5: lines1.append(f"5교시: {gy5}\n")

            # 1종 수동 (차량 먼저 → 이름)
            if sud_a:
                for i, nm in enumerate(sud_a):
                    lines1.append(f"1종수동: {pm_cars_1[i]} {nm}")
                if sudong_count == 2 and len(sud_a) < 2:
                    lines1.append("※ 수동 가능 인원이 1명입니다.")
            else:
                lines1.append("1종수동: (배정자 없음)")
            lines1.append("")

            # 1종 자동(있으면)
            if pm_cars_1:
                # 이미 위에서 개별 표기했으므로 목록만 별도 필요 없다면 생략 가능
                pass

            # 2종 자동 (차량 먼저 → 이름)
            if auto_a:
                lines1.append("2종자동:")
                for i, nm in enumerate(auto_a):
                    lines1.append(f" {pm_cars_2[i]} {nm}")
                lines1.append("")

            # 🚫 미배정 차량 (오전 → 오후 빠진 차량만)
            am_c1 = set(st.session_state.get("morning_assigned_cars_1", []))
            am_c2 = set(st.session_state.get("morning_assigned_cars_2", []))
            pm_c1_set = set([c for c in pm_cars_1 if c])
            pm_c2_set = set([c for c in pm_cars_2 if c])
            un1 = sorted([c for c in am_c1 if c and c not in pm_c1_set])
            un2 = sorted([c for c in am_c2 if c and c not in pm_c2_set])
            if un1 or un2:
                lines1.append("🚫 미배정 차량:")
                if un1:
                    lines1.append(" [1종 수동]")
                    for c in un1: lines1.append(f"  • {c} 마감")
                if un2:
                    lines1.append(" [2종 자동]")
                    for c in un2: lines1.append(f"  • {c} 마감")

            pm_text_block1 = "\n".join(lines1).rstrip()
            st.markdown("#### 🌇 오후 결과 (1/2: 배정 + 미배정)")
            st.code(pm_text_block1, language="text")
            clipboard_copy_button("📋 복사 (오후 결과 1/2)", pm_text_block1)

            # === 출력 블록 2: 오전 대비 비교 + 신규 ===
            lines2 = ["🔍 오전 대비 비교:"]
            morning_auto_names = set(st.session_state.get("morning_auto_names", []))
            afternoon_auto_names = set(auto_a)
            afternoon_sudong_norms = {normalize_name(x) for x in sud_a}

            added   = sorted(list(afternoon_auto_names - morning_auto_names))
            missing = []
            for nm in morning_auto_names:
                n_norm = normalize_name(nm)
                if n_norm not in {normalize_name(x) for x in afternoon_auto_names} and n_norm not in afternoon_sudong_norms:
                    missing.append(nm)

            newly_joined = sorted([
                x for x in a_list
                if normalize_name(x) not in {normalize_name(y) for y in st.session_state.get("morning_auto_names", [])}
            ])

            if added:        lines2.append(" • 추가 인원: " + ", ".join(added))
            if missing:      lines2.append(" • 빠진 인원: " + ", ".join(missing))
            if newly_joined: lines2.append(" • 신규 도로주행 인원: " + ", ".join(newly_joined))

            pm_text_block2 = "\n".join(lines2).rstrip()
            st.markdown("#### 🌇 오후 결과 (2/2: 비교)")
            st.code(pm_text_block2, language="text")
            clipboard_copy_button("📋 복사 (오후 결과 2/2)", pm_text_block2)

            # ✅ 전일 저장
            if save_check:
                save_json(PREV_FILE, {
                    "열쇠": today_key,
                    "교양_5교시": gy5 or gy4 or gy3 or prev_gyoyang5,
                    "1종수동": (sud_a[-1] if sud_a else prev_sudong)
                })
                st.success("전일근무.json 업데이트 완료 ✅")

        except Exception as e:
            st.error(f"오후 오류: {e}")
