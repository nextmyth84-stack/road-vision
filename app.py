# =====================================
# app.py — 도로주행 근무 자동 배정 v7.41+
# =====================================
import streamlit as st
from openai import OpenAI
import base64, re, json, os, difflib, html  # [PATCH] html 추가

st.set_page_config(layout="wide")
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
# 클립보드 복사 (버튼 UI, 모바일 호환)
# -----------------------
def clipboard_copy_button(label, text):
    btn_id = f"btn_{abs(hash(label+text))}"
    safe = (text or "").replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
    html_js = f"""
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
    }} )();
    </script>
    """
    st.components.v1.html(html_js, height=52)


# -----------------------
# 이름 정규화 / 차량 / 교정 / 순번
# -----------------------
def normalize_name(s):
    """괄호·공백·특수문자 제거 → 순수 한글 이름"""
    return re.sub(r"[^가-힣]", "", re.sub(r"\(.*?\)", "", s or ""))

def get_vehicle(name, veh_map):
    nkey = normalize_name(name)
    for car, nm in veh_map.items():
        if normalize_name(nm) == nkey:
            return car
    return ""
    
def _norm_car_id(s: str) -> str:
    """차량 아이디 비교용 정규화: 공백 제거, 전각/반각 공백 제거"""
    if not s:
        return ""
    return re.sub(r"\s+", "", str(s)).strip()
    
def mark_car(car, repair_cars):
    """
    차량아이디 표기 + (정비중) 태그
    - 차량 아이디를 정규화해서 리스트와 비교 (공백/표기차 무시)
    """
    if not car:
        return ""
    car_norm = _norm_car_id(car)
    repairs_norm = {_norm_car_id(x) for x in (repair_cars or [])}
    return f"{car}{' (정비중)' if car_norm in repairs_norm else ''}"

# [PATCH] 차량 번호 정렬용 키 (작은 수 → 큰 수)
def car_num_key(car_id: str):
    m = re.search(r"(\d+)", car_id or "")
    return int(m.group(1)) if m else 10**9

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
    """전체 근무자와 유사도 비교로 OCR 오타 교정"""
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
# 교양 시간 제한 규칙
# -----------------------
def can_attend_period_morning(name_pure: str, period:int, late_list):
    """오전 교양: 1=9:00~10:30, 2=10:30~12:00. 10시 이후 출근자는 1교시 불가."""
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
    """오후 교양: 3=13:00, 4=14:30, 5=16:00. 해당 시각 이전 조퇴면 해당 교시 불가."""
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
    "1종": "1종순번.json",
    "veh1": "1종차량표.json",
    "veh2": "2종차량표.json",
    "employees": "전체근무자.json",
    "1종자동": "1종자동순번.json",  # NEW
    "repair": "정비차량.json",       # [PATCH]
}
for k, v in files.items():
    files[k] = os.path.join(DATA_DIR, v)

default_data = {
    "열쇠": ["권한솔","김남균","김면정","김성연","김지은","안유미","윤여헌","윤원실","이나래","이호석","조윤영","조정래"],
    "교양": ["권한솔","김남균","김면정","김병욱","김성연","김주현","김지은","안유미","이호석","조정래"],
    "1종":  ["권한솔","김남균","김성연","김주현","이호석","조정래"],
    "veh1": {"2호":"조정래","5호":"권한솔","7호":"김남균","8호":"이호석","9호":"김주현","10호":"김성연"},
    "veh2": {"4호":"김남균","5호":"김병욱","6호":"김지은","12호":"안유미","14호":"김면정","15호":"이호석","17호":"김성연","18호":"권한솔","19호":"김주현","22호":"조정래"},
    "employees": ["권한솔","김남균","김면정","김성연","김지은","안유미","윤여헌","윤원실","이나래","이호석","조정래","김병욱","김주현"],
    "1종자동": ["21호", "22호", "23호", "24호"],
    "repair": {"1종수동": [], "1종자동": [], "2종자동": []},  # [PATCH]
}
for k, v in files.items():
    if not os.path.exists(v):
        try:
            with open(v, "w", encoding="utf-8") as f:
                json.dump(default_data[k], f, ensure_ascii=False, indent=2)
        except Exception as e:
            st.error(f"{v} 초기화 실패: {e}")

# 로드
key_order     = load_json(files["열쇠"])
gyoyang_order = load_json(files["교양"])
sudong_order  = load_json(files["1종"])
veh1_map      = load_json(files["veh1"])
veh2_map      = load_json(files["veh2"])
employee_list = load_json(files["employees"])
auto1_order   = load_json(files["1종자동"])  # NEW

# [PATCH] 정비 차량 로드 (하위호환: list ⇒ 3종 공통)
_repair_raw = load_json(files["repair"])
if isinstance(_repair_raw, dict):
    repair_saved = {
        "1종수동": _repair_raw.get("1종수동", []),
        "1종자동": _repair_raw.get("1종자동", []),
        "2종자동": _repair_raw.get("2종자동", []),
    }
elif isinstance(_repair_raw, list):
    repair_saved = {"1종수동": _repair_raw, "1종자동": _repair_raw, "2종자동": _repair_raw}
else:
    repair_saved = {"1종수동": [], "1종자동": [], "2종자동": []}
# 합산 보기(읽기 전용)
repair_union = sorted(set(repair_saved["1종수동"] + repair_saved["1종자동"] + repair_saved["2종자동"]), key=car_num_key)

# -----------------------
# 전일 근무자 로드
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

prev_data = load_prev_data()
prev_key = prev_data.get("열쇠", "")
prev_gyoyang5 = prev_data.get("교양_5교시", "")
prev_sudong = prev_data.get("1종수동", "")
prev_auto1 = prev_data.get("1종자동", "")
# =====================================
# 💄 사이드바 디자인 개선
# =====================================

st.sidebar.markdown("""
<style>
/* === 사이드바 최소/고정 폭 설정 === */
section[data-testid="stSidebar"] {
    background-color: #f8fafc;
    padding: 10px;
    border-right: 1px solid #e5e7eb;

    /* ▼ 핵심: 최소/기본 폭 지정 */
    min-width: 340px;     /* ← 원하는 최소 폭(px)로 변경 */
    width: 340px;         /* 기본 폭 */
    flex: 0 0 340px;      /* 부모 flex 레이아웃에서 폭 고정 */
}

/* 화면 크기에 따라 유연하게 */
@media (min-width: 1200px) {
  section[data-testid="stSidebar"] { width: 360px; flex: 0 0 360px; }
}
@media (min-width: 992px) and (max-width: 1199px) {
  section[data-testid="stSidebar"] { width: 340px; flex: 0 0 340px; }
}
@media (max-width: 991px) {
  /* 모바일/태블릿: 너무 크게 고정하지 않도록 */
  section[data-testid="stSidebar"] { min-width: 280px; width: 85vw; flex: 0 0 auto; }
}

/* 이하 기존 스타일 유지 */
.streamlit-expanderHeader { font-weight: 700 !important; color: #1e3a8a !important; font-size: 15px !important; }
textarea, input { font-size: 14px !important; }
div.stButton > button { background-color: #2563eb; color: white; border: none; border-radius: 8px; padding: 6px 12px; margin-top: 6px; font-weight: 600; }
div.stButton > button:hover { background-color: #1d4ed8; }
.sidebar-subtitle { font-weight: 600; color: #334155; margin-top: 10px; margin-bottom: 4px; }
.repair-box { border: 1px solid #fdba74; background: #fff7ed; padding: 8px 10px; border-radius: 8px; color: #7c2d12; font-size: 13px; }
/* (있다면) .big-label, .btn-desc 등 다른 커스텀 클래스도 그대로 둠 */


/* 결과 박스 */
.repair-box {
    border: 1px solid #fdba74;
    background: #fff7ed;
    padding: 8px 10px;
    border-radius: 8px;
    color: #7c2d12;
    font-size: 13px;

.btn-desc{
    font-size: 13px;
    color: #475569;   /* slate-600 */
    margin-top: 6px;
    line-height: 1.5;
}

</style>
""", unsafe_allow_html=True)

st.sidebar.markdown("<h3 style='text-align:center; color:#1e3a8a;'>⚙️ 근무자 설정 </h3>", unsafe_allow_html=True)

# =====================================
# 🗓 전일 근무자 (1종자동 포함 저장)
# =====================================
with st.sidebar.expander("🗓 전일 근무자", expanded=True):
    prev_key = st.text_input("🔑 전일 열쇠 담당", prev_key)
    prev_gyoyang5 = st.text_input("🧑‍🏫 전일 교양(5교시)", prev_gyoyang5)
    prev_sudong = st.text_input("🚚 전일 1종 수동", prev_sudong)
    prev_auto1 = st.text_input("🚗 전일 1종 자동", prev_auto1)  # NEW

    if st.button("💾 전일 근무자 저장", key="btn_prev_save"):
        save_json(PREV_FILE, {
            "열쇠": prev_key,
            "교양_5교시": prev_gyoyang5,
            "1종수동": prev_sudong,
            "1종자동": prev_auto1,
        })
        st.sidebar.success("전일근무.json 저장 완료 ✅")

# =====================================
# 📂 데이터 관리 (그룹) — 내부에 3개 메뉴 묶기
# =====================================
with st.sidebar.expander("📂 데이터 관리", expanded=False):

    # 🔢 순번표 관리
    with st.expander("🔢 순번표 관리", expanded=False):
        st.markdown("<div class='sidebar-subtitle'>열쇠 순번</div>", unsafe_allow_html=True)
        t1 = st.text_area("", "\n".join(key_order), height=150)
        st.markdown("<div class='sidebar-subtitle'>교양 순번</div>", unsafe_allow_html=True)
        t2 = st.text_area("", "\n".join(gyoyang_order), height=150)
        st.markdown("<div class='sidebar-subtitle'>1종 수동 순번</div>", unsafe_allow_html=True)
        t3 = st.text_area("", "\n".join(sudong_order), height=120)
        st.markdown("<div class='sidebar-subtitle'>1종 자동 순번</div>", unsafe_allow_html=True)
        t4 = st.text_area("", "\n".join(auto1_order or []), height=100)

        if st.button("💾 순번표 저장", key="btn_save_orders"):
            save_json(files["열쇠"], [x.strip() for x in t1.splitlines() if x.strip()])
            save_json(files["교양"], [x.strip() for x in t2.splitlines() if x.strip()])
            save_json(files["1종"], [x.strip() for x in t3.splitlines() if x.strip()])
            save_json(files["1종자동"], [x.strip() for x in (t4.splitlines() if t4 else []) if x.strip()])
            key_order[:] = load_json(files["열쇠"])
            gyoyang_order[:] = load_json(files["교양"])
            sudong_order[:] = load_json(files["1종"])
            auto1_order[:] = load_json(files["1종자동"])
            st.success("순번표 저장 완료 ✅")

    # 🚘 차량 담당 관리
    with st.expander("🚘 차량 담당 관리", expanded=False):
        def parse_vehicle_map(text):
            m = {}
            for line in text.splitlines():
                p = line.strip().split()
                if len(p) >= 2:
                    m[p[0]] = " ".join(p[1:])  # car -> name
            return m

        st.markdown("<div class='sidebar-subtitle'>1종 수동 차량표</div>", unsafe_allow_html=True)
        t1v = st.text_area("", "\n".join([f"{car} {nm}" for car, nm in veh1_map.items()]), height=130)
        st.markdown("<div class='sidebar-subtitle'>2종 자동 차량표</div>", unsafe_allow_html=True)
        t2v = st.text_area("", "\n".join([f"{car} {nm}" for car, nm in veh2_map.items()]), height=160)

        if st.button("💾 차량표 저장", key="btn_save_veh"):
            veh1_new, veh2_new = {}, {}
            for line in t1v.splitlines():
                p = line.strip().split()
                if len(p) >= 2: veh1_new[p[0]] = " ".join(p[1:])
            for line in t2v.splitlines():
                p = line.strip().split()
                if len(p) >= 2: veh2_new[p[0]] = " ".join(p[1:])
            save_json(files["veh1"], veh1_new)
            save_json(files["veh2"], veh2_new)
            veh1_map = load_json(files["veh1"])
            veh2_map = load_json(files["veh2"])
            st.success("차량표 저장 완료 ✅")

    # 👥 전체 근무자
    with st.expander("👥 전체 근무자", expanded=False):
        st.markdown("<div class='sidebar-subtitle'>근무자 목록</div>", unsafe_allow_html=True)
        t_emp = st.text_area("", "\n".join(employee_list), height=180)
        if st.button("💾 근무자 저장", key="btn_save_emp"):
            save_json(files["employees"], [x.strip() for x in t_emp.splitlines() if x.strip()])
            employee_list = load_json(files["employees"])
            st.success("근무자 명단 저장 완료 ✅")

# =====================================
# ⚙️ 추가 설정 + 정비차량 그룹
# =====================================
st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ 추가 설정")
sudong_count = st.sidebar.radio("1종 수동 인원 수", [1, 2], index=0)



st.sidebar.caption("정비차량 추가/삭제는 아래 ‘정비 차량 목록’에서 관리하세요.")

# === 🛠 정비 차량 목록 (그룹으로 한 번 더 묶기) ===
# 옵션 (숫자 오름차순)
opt_1s = sorted(list((veh1_map or {}).keys()), key=car_num_key)                                    # 1종 수동
opt_1a = sorted(list((st.session_state.get("auto1_order") or auto1_order or [])), key=car_num_key)  # 1종 자동
opt_2a = sorted(list((veh2_map or {}).keys()), key=car_num_key)                                    # 2종 자동

def _defaults(saved_list, opts):
    s = set(saved_list or [])
    return [x for x in opts if x in s]

with st.sidebar.expander("🛠 정비 차량 목록", expanded=False):
    with st.expander(" 1종 수동 정비", expanded=False):
        sel_1s = st.multiselect("정비 차량 (1종 수동)", options=opt_1s,
                                default=_defaults(repair_saved["1종수동"], opt_1s), key="repair_sel_1s")
    with st.expander(" 1종 자동 정비", expanded=False):
        sel_1a = st.multiselect("정비 차량 (1종 자동)", options=opt_1a,
                                default=_defaults(repair_saved["1종자동"], opt_1a), key="repair_sel_1a")
    with st.expander(" 2종 자동 정비", expanded=False):
        sel_2a = st.multiselect("정비 차량 (2종 자동)", options=opt_2a,
                                default=_defaults(repair_saved["2종자동"], opt_2a), key="repair_sel_2a")

    payload = {
        "1종수동": sorted(set(sel_1s or []), key=car_num_key),
        "1종자동": sorted(set(sel_1a or []), key=car_num_key),
        "2종자동": sorted(set(sel_2a or []), key=car_num_key),
    }
    if st.button("💾 정비 차량 저장", key="repair_save_btn"):
        save_json(files["repair"], payload)
        repair_saved = payload
        st.session_state["repair_1s"] = payload["1종수동"]
        st.session_state["repair_1a"] = payload["1종자동"]
        st.session_state["repair_2a"] = payload["2종자동"]
        st.session_state["repair_cars"] = sorted(
            set(payload["1종수동"] + payload["1종자동"] + payload["2종자동"]), key=car_num_key
        )
        st.success("정비 차량 저장 완료 ✅")

    st.markdown(
        f"""<div class="repair-box">
        <b>현재 정비 차량</b><br>
        [1종 수동] {", ".join(repair_saved["1종수동"]) if repair_saved["1종수동"] else "없음"}<br>
        [1종 자동] {", ".join(repair_saved["1종자동"]) if repair_saved["1종자동"] else "없음"}<br>
        [2종 자동] {", ".join(repair_saved["2종자동"]) if repair_saved["2종자동"] else "없음"}
        </div>""",
        unsafe_allow_html=True
    )

cutoff = st.sidebar.slider("OCR 오타교정 컷오프 (낮을수록 공격적 교정)", 0.4, 0.9, 0.6, 0.05)

st.sidebar.markdown("""
<p style='text-align:center; font-size:8px; color:#94a3b8;'>
    powered by <b>wook</b>
</p>
""", unsafe_allow_html=True)

# 세션 최신화
st.session_state.update({
    "key_order": key_order, "gyoyang_order": gyoyang_order, "sudong_order": sudong_order,
    "veh1": veh1_map, "veh2": veh2_map, "employee_list": employee_list,
    "sudong_count": sudong_count,
    # 종별 정비 목록 + 합산(호환용)
    "repair_1s": repair_saved["1종수동"],
    "repair_1a": repair_saved["1종자동"],
    "repair_2a": repair_saved["2종자동"],
    "repair_cars": repair_union,
    "cutoff": cutoff,
    "auto1_order": auto1_order,  # NEW
})

# -----------------------
# 탭 UI 구성 (오전 / 오후)
# -----------------------
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
    /* [PATCH] 결과 미리보기(색상 강조) */
    .result-pre {
        white-space: pre-wrap;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
        background: #0b1021;
        color: #e5e7eb;
        border-radius: 8px;
        padding: 12px;
        border: 1px solid #1f2937;
    }
    .repair-tag { color: #ef4444; font-weight: 700; }
    .btn-desc{
        font-size: 13px;
        color: #475569;   /* slate-600 */
        margin-top: 6px;
        line-height: 1.5;
    }
    </style>
""", unsafe_allow_html=True)

# [PATCH] (정비중) 강조 렌더 함수
def render_result_with_repair_color(text: str) -> str:
    esc = html.escape(text or "")
    esc = esc.replace("(정비중)", "<span class='repair-tag'>(정비중)</span>")
    return f"<pre class='result-pre'>{esc}</pre>"
# =====================================
# 🌅 오전 근무 탭
# =====================================
with tab1:
    st.markdown("<h4 style='margin-top:6px;'>1️⃣ 오전 근무표 업로드 & OCR</h4>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        m_file = st.file_uploader("📸 오전 근무표 업로드", type=["png","jpg","jpeg"], key="m_upload")
    with col2:
        pass

    # --- OCR 버튼 + 설명 (가로 배치) ---
    col_btn, col_desc = st.columns([1, 4])
    with col_btn:
        run_m = st.button(
            "오전 GPT 인식",
            key="btn_m_ocr",
            help="근무표에서 도로주행 근무자/제외자를 추출합니다."
        )
    with col_desc:
        st.markdown(
            """<div class='btn-desc'>
            GPT 인식 버튼을 누르고 <b>실제 근무자와 비교합니다.</b><br>
            실제와 다르면 <b>꼭! 수정하세요.(근무자인식불가 OR 오타)</b>
            </div>""",
            unsafe_allow_html=True
        )

    if run_m:
        if not m_file:
            st.warning("오전 이미지를 업로드하세요.")
        else:
            with st.spinner("🧩 GPT 이미지 분석 중..."):
                names, course, excluded, early, late = gpt_extract(
                    m_file.read(), want_early=True, want_late=True, want_excluded=True
                )
                fixed = [correct_name_v2(n, st.session_state["employee_list"], cutoff=st.session_state["cutoff"]) for n in names]
                excluded_fixed = [correct_name_v2(n, st.session_state["employee_list"], cutoff=st.session_state["cutoff"]) for n in excluded]
                for e in early:
                    e["name"] = correct_name_v2(e.get("name",""), st.session_state["employee_list"], cutoff=st.session_state["cutoff"])
                for l in late:
                    l["name"] = correct_name_v2(l.get("name",""), st.session_state["employee_list"], cutoff=st.session_state["cutoff"])

                st.session_state.m_names_raw = fixed
                st.session_state.course_records = course
                st.session_state.excluded_auto = excluded_fixed
                st.session_state.early_leave = [e for e in early if e.get("time") is not None]
                st.session_state.late_start = [l for l in late if l.get("time") is not None]
                st.success(f"오전 인식 완료 → 근무자 {len(fixed)}명, 제외자 {len(excluded_fixed)}명, 코스 {len(course)}건")

    st.markdown("<h4 style='font-size:16px;'>🚫 근무 제외자 (실제와 비교 필수!)</h4>", unsafe_allow_html=True)
    excluded_text = st.text_area("근무 제외자", "\n".join(st.session_state.get("excluded_auto", [])), height=120)
    excluded_set = {normalize_name(x) for x in excluded_text.splitlines() if x.strip()}

    st.markdown("<h4 style='font-size:18px;'>🌅 오전 근무자 (실제와 비교 필수!)</h4>", unsafe_allow_html=True)
    morning_text = st.text_area("오전 근무자", "\n".join(st.session_state.get("m_names_raw", [])), height=220)
    m_list = [x.strip() for x in morning_text.splitlines() if x.strip()]

    early_leave = st.session_state.get("early_leave", [])
    late_start = st.session_state.get("late_start", [])
    m_norms = {normalize_name(x) for x in m_list} - excluded_set

    st.markdown("<h4 style='font-size:18px;'>🚗 오전 근무 배정</h4>", unsafe_allow_html=True)
    if st.button("📋 오전 배정 생성"):
        try:
            key_order     = st.session_state.get("key_order", [])
            gyoyang_order = st.session_state.get("gyoyang_order", [])
            sudong_order  = st.session_state.get("sudong_order", [])
            veh1_map      = st.session_state.get("veh1", {})
            veh2_map      = st.session_state.get("veh2", {})
            sudong_count  = st.session_state.get("sudong_count", 1)
            # [PATCH] 종별 정비 목록
            repair_1s = st.session_state.get("repair_1s", [])
            repair_1a = st.session_state.get("repair_1a", [])
            repair_2a = st.session_state.get("repair_2a", [])
            auto1_order = st.session_state.get("auto1_order", [])

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

            # 🧑‍🏫 교양 1·2교시
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

            # 🔄 1종 자동 차량 순번 (하루 1회)
            today_auto1 = ""
            if auto1_order:
                if prev_auto1 in auto1_order:
                    idx = (auto1_order.index(prev_auto1) + 1) % len(auto1_order)
                    today_auto1 = auto1_order[idx]
                else:
                    today_auto1 = auto1_order[0]
            st.session_state.today_auto1 = today_auto1

            # 오전 차량 기록
            st.session_state.morning_assigned_cars_1 = [get_vehicle(x, veh1_map) for x in sud_m if get_vehicle(x, veh1_map)]
            st.session_state.morning_assigned_cars_2 = [get_vehicle(x, veh2_map) for x in auto_m if get_vehicle(x, veh2_map)]
            st.session_state.morning_auto_names = auto_m + sud_m

            # === 출력 ===
            lines = []
            if today_key:
                lines.append(f"열쇠: {today_key}")
                lines.append("")

            if gy1: lines.append(f"1교시: {gy1}")
            if gy2: lines.append(f"2교시: {gy2}")
            if gy1 or gy2: lines.append("")

            if sud_m:
                for nm in sud_m:
                    car = mark_car(get_vehicle(nm, veh1_map), repair_1s)
                    lines.append(f"1종수동: {car} {nm}" if car else f"1종수동: {nm}")
                if sudong_count == 2 and len(sud_m) < 2:
                    lines.append("※ 수동 가능 인원이 1명입니다.")
            else:
                lines.append("1종수동: (배정자 없음)")
                if sudong_count >= 1:
                    lines.append("※ 수동 가능 인원이 0명입니다.")

            # 1종 자동 (정비중 표기 반영)
            if st.session_state.get("today_auto1"):
                lines.append("")
                a1 = mark_car(st.session_state["today_auto1"], repair_1a)
                lines.append(f"1종자동: {a1}")
                lines.append("")

            if auto_m:
                lines.append("2종자동:")
                for nm in auto_m:
                    car = mark_car(get_vehicle(nm, veh2_map), repair_2a)
                    lines.append(f" • {car} {nm}" if car else f" • {nm}")

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
# 🌇 오후 근무 탭
# =====================================
with tab2:
    st.markdown("<h4 style='margin-top:6px;'>2️⃣ 오후 근무표 업로드 & OCR</h4>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        a_file = st.file_uploader("📸 오후 근무표 업로드", type=["png","jpg","jpeg"], key="a_upload")
    with col2:
        pass

    # --- OCR 버튼 + 설명 (가로 배치) ---
    col_btn, col_desc = st.columns([1, 4])
    with col_btn:
        run_a = st.button(
            "오전 GPT 인식",
            key="btn_a_ocr",
            help="근무표에서 도로주행 근무자를 추출합니다."
        )
    with col_desc:
        st.markdown(
            """<div class='btn-desc'>
            GPT 인식 버튼을 누르고 <b>실제 근무자와 비교합니다.</b><br>
            실제와 다르면 <b>꼭! 수정하세요.(근무자인식불가 OR 오타)</b>
            </div>""",
            unsafe_allow_html=True
        )
        
    if run_a:
        if not a_file:
            st.warning("오후 이미지를 업로드하세요.")
        else:
            with st.spinner("🧩 GPT 이미지 분석 중..."):
                names, _, excluded, early, late = gpt_extract(
                    a_file.read(), want_early=True, want_late=True, want_excluded=True
                )
                fixed = [correct_name_v2(n, st.session_state["employee_list"], cutoff=st.session_state["cutoff"]) for n in names]
                excluded_fixed = [correct_name_v2(n, st.session_state["employee_list"], cutoff=st.session_state["cutoff"]) for n in excluded]
                for e in early:
                    e["name"] = correct_name_v2(e.get("name",""), st.session_state["employee_list"], cutoff=st.session_state["cutoff"])
                for l in late:
                    l["name"] = correct_name_v2(l.get("name",""), st.session_state["employee_list"], cutoff=st.session_state["cutoff"])

                st.session_state.a_names_raw = fixed
                st.session_state.excluded_auto_pm = excluded_fixed
                st.session_state.early_leave_pm = [e for e in early if e.get("time") is not None]
                st.session_state.late_start_pm = [l for l in late if l.get("time") is not None]
                st.success(f"오후 인식 완료 → 근무자 {len(fixed)}명, 제외자 {len(excluded_fixed)}명")
                
    st.markdown("<h4 style='font-size:18px;'>🌇 오후 근무자 (실제와 비교 필수!)</h4>", unsafe_allow_html=True)
    afternoon_text = st.text_area("오후 근무자", "\n".join(st.session_state.get("a_names_raw", [])), height=220)
    a_list = [x.strip() for x in afternoon_text.splitlines() if x.strip()]

    # 오후도 오전 제외자 그대로 사용
    excluded_set = {normalize_name(x) for x in st.session_state.get("excluded_auto", [])}
    a_norms = {normalize_name(x) for x in a_list} - excluded_set

    save_check = st.checkbox("전일근무자 자동 저장", value=True)
    st.caption("(열쇠, 5교시교양, 1종수동, 1종자동")

    st.markdown("<h4 style='font-size:18px;'>🚘 오후 근무 배정</h4>", unsafe_allow_html=True)
    if st.button("📋 오후 배정 생성"):
        try:
            gyoyang_order = st.session_state.get("gyoyang_order", [])
            sudong_order  = st.session_state.get("sudong_order", [])
            veh1_map      = st.session_state.get("veh1", {})
            veh2_map      = st.session_state.get("veh2", {})
            sudong_count  = st.session_state.get("sudong_count", 1)
            # 종별 정비 목록
            repair_1s = st.session_state.get("repair_1s", [])
            repair_1a = st.session_state.get("repair_1a", [])
            repair_2a = st.session_state.get("repair_2a", [])

            today_key = st.session_state.get("today_key", prev_key)
            gy_start  = st.session_state.get("gyoyang_base_for_pm", prev_gyoyang5) or (gyoyang_order[0] if gyoyang_order else "")
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

            # 🚚 1종 수동
            sud_a, last = [], sud_base
            for _ in range(sudong_count):
                pick = pick_next_from_cycle(sudong_order, last, a_norms)
                if not pick: break
                sud_a.append(pick); last = pick

            # 🚗 2종 자동(사람)
            sud_a_norms = {normalize_name(x) for x in sud_a}
            auto_a = [x for x in a_list if normalize_name(x) in (a_norms - sud_a_norms)]

            # === 출력 ===
            lines = []
            if today_key:
                lines.append(f"열쇠: {today_key}")
                lines.append("")
            if gy3: lines.append(f"3교시: {gy3}")
            if gy4: lines.append(f"4교시: {gy4}")
            if gy5:
                lines.append(f"5교시: {gy5}")
                lines.append("")

            if sud_a:
                for nm in sud_a:
                    car = mark_car(get_vehicle(nm, veh1_map), repair_1s)
                    lines.append(f"1종수동: {car} {nm}" if car else f"1종수동: {nm}")
                    lines.append("")
                if sudong_count == 2 and len(sud_a) < 2:
                    lines.append("※ 수동 가능 인원이 1명입니다.")
            else:
                lines.append("1종수동: (배정자 없음)")
                if sudong_count >= 1:
                    lines.append("※ 수동 가능 인원이 0명입니다.")

            # 1종 자동 (정비중 표기 반영)
            if st.session_state.get("today_auto1"):
                a1 = mark_car(st.session_state["today_auto1"], repair_1a)
                lines.append(f"1종자동: {a1}")
                lines.append("")

            if auto_a:
                lines.append("2종자동:")
                for nm in auto_a:
                    car = mark_car(get_vehicle(nm, veh2_map), repair_2a)
                    lines.append(f" • {car} {nm}" if car else f" • {nm}")

            # 🚫 마감 차량 (오전→오후)
            am_c1 = set(st.session_state.get("morning_assigned_cars_1", []))
            am_c2 = set(st.session_state.get("morning_assigned_cars_2", []))
            pm_c1 = {get_vehicle(x, veh1_map) for x in sud_a if get_vehicle(x, veh1_map)}
            pm_c2 = {get_vehicle(x, veh2_map) for x in auto_a if get_vehicle(x, veh2_map)}
            un1 = sorted([c for c in am_c1 if c and c not in pm_c1], key=car_num_key)
            un2 = sorted([c for c in am_c2 if c and c not in pm_c2], key=car_num_key)
            if un1 or un2:
                lines.append("")
                lines.append("🚫 마감 차량:")
                if un1:
                    lines.append(" [1종 수동]")
                    for c in un1: lines.append(f"  • {c} 마감")
                if un2:
                    lines.append(" [2종 자동]")
                    for c in un2: lines.append(f"  • {c} 마감")

            # 🔍 오전 대비 비교
            lines.append("")
            lines.append("🔍 오전 대비 비교:")
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
            pm_result_text = "\n".join(lines)

            st.markdown("#### 🌇 오후 근무 결과")
            st.code(pm_result_text, language="text")
            clipboard_copy_button("📋 결과 복사하기", pm_result_text)

        except Exception as e:
            st.error(f"오후 오류: {e}")
