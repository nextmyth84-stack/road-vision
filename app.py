# =====================================
# app.py — 도로주행 근무자동배정 v7.31 (패치 완전본)
# =====================================
import streamlit as st
from openai import OpenAI
import base64, re, json, os, difflib

# -----------------------
# 페이지 설정
# -----------------------
st.set_page_config(page_title="도로주행 근무자동배정 v7.31", layout="wide")
st.markdown("<h3 style='text-align:center; font-size:22px;'>🚗 도로주행 근무자동배정 v7.31</h3>", unsafe_allow_html=True)

# -----------------------
# OpenAI API 연결
# -----------------------
try:
    client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
except Exception:
    st.error("⚠️ OPENAI_API_KEY가 설정되지 않았습니다.")
    st.stop()

MODEL_NAME = "gpt-4o"

# -----------------------
# JSON 유틸
# -----------------------
def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"저장 실패: {e}")

# -----------------------
# 전일 기준 데이터
# -----------------------
PREV_FILE = "전일근무.json"
prev = load_json(PREV_FILE, {"열쇠": "", "교양_5교시": "", "1종수동": ""})
prev_key = prev.get("열쇠", "")
prev_gy5 = prev.get("교양_5교시", "")
prev_sud = prev.get("1종수동", "")

# -----------------------
# 클립보드 복사 버튼 (코드 노출 방지)
# -----------------------
def clipboard_copy_button(label, text):
    btn = f"btn_{abs(hash(label + text))}"
    safe = (text.replace("\\", "\\\\")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t")
                .replace("`", "\\`")
                .replace('"', '\\"'))
    html = f"""
    <button id="{btn}" style="background:#2563eb;color:white;border:none;
    padding:6px 12px;border-radius:8px;cursor:pointer;margin-top:6px;">
    {label}</button>
    <script>
    (function() {{
      const hook = () => {{
        const b = document.getElementById("{btn}");
        if (!b) return;
        b.onclick = () => {{
          navigator.clipboard.writeText("{safe}");
          const t = b.innerText;
          b.innerText = "✅ 복사됨!";
          setTimeout(() => b.innerText = t, 1500);
        }};
      }};
      if (document.readyState === "loading") {{
        document.addEventListener("DOMContentLoaded", hook);
      }} else {{
        hook();
      }}
    }})();
    </script>
    """
    st.components.v1.html(html, height=45)

# -----------------------
# 이름/차량/순번 관련 함수
# -----------------------
def normalize_name(s):
    return re.sub(r"[^가-힣]", "", re.sub(r"\(.*?\)", "", s or ""))

def get_vehicle(name, veh):
    n = normalize_name(name)
    for c, nm in veh.items():
        if normalize_name(nm) == n:
            return c
    return ""

def mark_car(car, repairs):
    return f"{car}{' (정비)' if car in repairs else ''}" if car else ""

def pick_next_from_cycle(cycle, last, allowed: set):
    if not cycle:
        return None
    ncy = [normalize_name(x) for x in cycle]
    ln = normalize_name(last)
    s = (ncy.index(ln) + 1) % len(cycle) if ln in ncy else 0
    for i in range(len(cycle) * 2):
        cand = cycle[(s + i) % len(cycle)]
        if normalize_name(cand) in allowed:
            return cand
    return None

def correct_name_v2(name, elist, cut=0.6):
    n = normalize_name(name)
    if not n:
        return name
    best, score = None, 0
    for c in elist:
        r = difflib.SequenceMatcher(None, normalize_name(c), n).ratio()
        if r > score:
            best, score = c, r
    return best if best and score >= cut else name

# -----------------------
# OCR (이름/코스/제외자/지각/조퇴)
# -----------------------
def gpt_extract(img_bytes, want_early=False, want_late=False, want_excluded=False):
    b64 = base64.b64encode(img_bytes).decode()
    prompt = (
        "도로주행 근무표입니다.\n"
        "‘학과, 기능, PC’ 제외하고 도로주행 근무자만 추출.\n"
        "괄호의 A/B 및 합/불은 코스점검 결과로 표시.\n"
        "‘휴가, 교육, 출장, 공가, 연가, 연차, 돌봄’은 excluded로.\n"
        "‘조퇴’는 early_leave로, ‘10시 출근’ 등은 late_start로.\n"
        "JSON으로 출력."
        "반드시 하나의 JSON만 출력하세요. 텍스트 설명 절대 넣지 마세요.",

    )
    try:
        res = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "표에서 이름과 메타 정보를 JSON으로 추출"},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]}
            ]
        )
       raw = res.choices[0].message.content or ""
        m = re.search(r"\{.*\}", raw, re.S)
        js = {}
        if m:
            try:
                js = json.loads(m.group(0))
            except json.JSONDecodeError:
                parts = re.findall(r"\{[^\}]*\}", raw)
                js = json.loads(parts[0]) if parts else {}
        if not isinstance(js, dict):
            js = {}



        names, courses = [], []
        for n in js.get("names", []):
            m2 = re.search(r"([가-힣]+)\s*\(([^)]*)\)", n)
            if m2:
                nm = m2.group(1)
                det = re.sub(r"[^A-Za-z가-힣]", "", m2.group(2)).upper()
                crs = "A" if "A" in det else ("B" if "B" in det else None)
                resu = "합격" if "합" in det else ("불합격" if "불" in det else None)
                if crs and resu:
                    courses.append({"name": nm, "course": f"{crs}코스", "result": resu})
                names.append(nm)
            else:
                names.append(n.strip())
        exc = js.get("excluded", []) if want_excluded else []
        early = js.get("early_leave", []) if want_early else []
        late = js.get("late_start", []) if want_late else []
        for e in early:
            try: e["time"] = float(e.get("time"))
            except: e["time"] = None
        for l in late:
            try: l["time"] = float(l.get("time"))
            except: l["time"] = None
        return names, courses, exc, early, late
    except Exception as e:
        st.error(f"OCR 실패: {e}")
        return [], [], [], [], []

# -----------------------
# 교양 시간 제한
# -----------------------
def can_attend_period_morning(name, period, late_list):
    nn = normalize_name(name)
    tmap = {1: 9.0, 2: 10.5}
    for l in late_list or []:
        if normalize_name(l.get("name", "")) == nn:
            t = float(l.get("time", 99) or 99)
            return t <= tmap[period]
    return True

def can_attend_period_afternoon(name, period, early_list):
    nn = normalize_name(name)
    tmap = {3: 13.0, 4: 14.5, 5: 16.0}
    for e in early_list or []:
        if normalize_name(e.get("name", "")) == nn:
            t = float(e.get("time", 0) or 0)
            return t > tmap[period]
    return True

# -----------------------
# 기본 데이터 파일 로드
# -----------------------
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
files = {
    "열쇠": "열쇠순번.json",
    "교양": "교양순번.json",
    "1종": "1종순번.json",
    "veh1": "1종차량표.json",
    "veh2": "2종차량표.json",
    "employees": "전체근무자.json"
}
for k, v in files.items():
    files[k] = os.path.join(DATA_DIR, v)
# -----------------------
# 기본값 생성 (없으면)
# -----------------------
default_data = {
    "열쇠": ["권한솔","김남균","김면정","김성연","김지은","안유미","윤여헌","윤원실","이나래","이호석","조윤영","조정래"],
    "교양": ["권한솔","김남균","김면정","김병욱","김성연","김주현","김지은","안유미","이호석","조정래"],
    "1종":  ["권한솔","김남균","김성연","김주현","이호석","조정래"],
    "veh1": {"2호":"조정래","5호":"권한솔","7호":"김남균","8호":"이호석","9호":"김주현","10호":"김성연"},
    "veh2": {"4호":"김남균","5호":"김병욱","6호":"김지은","12호":"안유미","14호":"김면정","15호":"이호석","17호":"김성연","18호":"권한솔","19호":"김주현","22호":"조정래"},
    "employees": ["권한솔","김남균","김면정","김성연","김지은","안유미","윤여헌","윤원실","이나래","이호석","조윤영","조정래","김병욱","김주현"]
}
for k,v in files.items():
    if not os.path.exists(v):
        save_json(v, default_data[k])

# -----------------------
# 데이터 로드
# -----------------------
key_order   = load_json(files["열쇠"])
gyoyang_ord = load_json(files["교양"])
sudong_ord  = load_json(files["1종"])
veh1_map    = load_json(files["veh1"])
veh2_map    = load_json(files["veh2"])
employee_ls = load_json(files["employees"])

# -----------------------
# 사이드바 (숨김형 편집 UI)
# -----------------------
st.sidebar.header("📂 데이터 관리")
with st.sidebar.expander("🔑 열쇠 순번", expanded=False):
    t = st.text_area("열쇠 순번", "\n".join(key_order), height=180)
    if st.button("저장 (열쇠 순번)"):
        save_json(files["열쇠"], [x.strip() for x in t.splitlines() if x.strip()])
        key_order = load_json(files["열쇠"]); st.success("열쇠 순번 저장 완료")

with st.sidebar.expander("📘 교양 순번", expanded=False):
    t = st.text_area("교양 순번", "\n".join(gyoyang_ord), height=180)
    if st.button("저장 (교양 순번)"):
        save_json(files["교양"], [x.strip() for x in t.splitlines() if x.strip()])
        gyoyang_ord = load_json(files["교양"]); st.success("교양 순번 저장 완료")

with st.sidebar.expander("🧰 1종 수동 순번", expanded=False):
    t = st.text_area("1종 수동 순번", "\n".join(sudong_ord), height=180)
    if st.button("저장 (1종 수동 순번)"):
        save_json(files["1종"], [x.strip() for x in t.splitlines() if x.strip()])
        sudong_ord = load_json(files["1종"]); st.success("1종 수동 순번 저장 완료")

with st.sidebar.expander("🚗 1종 수동 차량표", expanded=False):
    t = "\n".join([f"{car} {nm}" for car, nm in veh1_map.items()])
    t_new = st.text_area("1종 수동 차량표 (차량 공백 이름)", t, height=180)
    if st.button("저장 (1종 차량표)"):
        new_map = {}
        for line in t_new.splitlines():
            p = line.strip().split()
            if len(p) >= 2:
                new_map[p[0]] = " ".join(p[1:])
        save_json(files["veh1"], new_map)
        veh1_map = load_json(files["veh1"]); st.success("1종 수동 차량표 저장 완료")

with st.sidebar.expander("🚘 2종 자동 차량표", expanded=False):
    t = "\n".join([f"{car} {nm}" for car, nm in veh2_map.items()])
    t_new = st.text_area("2종 자동 차량표 (차량 공백 이름)", t, height=180)
    if st.button("저장 (2종 차량표)"):
        new_map = {}
        for line in t_new.splitlines():
            p = line.strip().split()
            if len(p) >= 2:
                new_map[p[0]] = " ".join(p[1:])
        save_json(files["veh2"], new_map)
        veh2_map = load_json(files["veh2"]); st.success("2종 자동 차량표 저장 완료")

with st.sidebar.expander("👥 전체 근무자 명단", expanded=False):
    t = st.text_area("전체 근무자 명단", "\n".join(employee_ls), height=200)
    if st.button("저장 (전체 근무자)"):
        save_json(files["employees"], [x.strip() for x in t.splitlines() if x.strip()])
        employee_ls = load_json(files["employees"]); st.success("전체 근무자 저장 완료")

sudong_count = st.sidebar.radio("1종 수동 인원수", [1, 2], index=0)
repair_cars  = [x.strip() for x in st.sidebar.text_input("정비 차량 (쉼표 구분)", value="").split(",") if x.strip()]
cutoff       = st.sidebar.slider("OCR 오타교정 컷오프 (낮을수록 공격적)", 0.4, 0.9, 0.6, 0.05)
st.sidebar.info(f"전일 기준 → 열쇠:{prev_key or '-'}, 교양5:{prev_gy5 or '-'}, 1종:{prev_sud or '-'}")

# 최신 상태 저장
st.session_state.update({
    "key_order": key_order, "gyoyang_order": gyoyang_ord, "sudong_order": sudong_ord,
    "veh1": veh1_map, "veh2": veh2_map, "employee_list": employee_ls,
    "sudong_count": sudong_count, "repair_cars": repair_cars, "cutoff": cutoff,
})

# -----------------------
# 1️⃣ 이미지 업로드 & OCR
# -----------------------
st.markdown("<h4 style='margin-top:6px;'>1️⃣ 근무표 이미지 업로드 & OCR</h4>", unsafe_allow_html=True)
col1, col2 = st.columns(2)
with col1:
    m_file = st.file_uploader("📸 오전 근무표", type=["png","jpg","jpeg"])
with col2:
    a_file = st.file_uploader("📸 오후 근무표", type=["png","jpg","jpeg"])

b1, b2 = st.columns(2)
with b1:
    if st.button("🧠 오전 GPT 인식"):
        if not m_file:
            st.warning("오전 이미지를 업로드하세요.")
        else:
            names, courses, excluded, early, late = gpt_extract(
                m_file.read(), want_early=True, want_late=True, want_excluded=True
            )
            # 이름 교정
            fixed = [correct_name_v2(n, employee_ls, cut=cutoff) for n in names]
            for r in courses:
                r["name"] = correct_name_v2(r.get("name",""), employee_ls, cut=cutoff)
            excluded_fixed = [correct_name_v2(n, employee_ls, cut=cutoff) for n in excluded]
            for e in early: e["name"] = correct_name_v2(e.get("name",""), employee_ls, cut=cutoff)
            for l in late:  l["name"] = correct_name_v2(l.get("name",""), employee_ls, cut=cutoff)

            st.session_state.m_names_raw = fixed
            st.session_state.course_records = courses
            st.session_state.excluded_auto = excluded_fixed
            st.session_state.early_leave = [e for e in early if e.get("time") is not None]
            st.session_state.late_start = [l for l in late if l.get("time") is not None]
            st.success(f"오전 인식 → 근무자 {len(fixed)}명, 제외자 {len(excluded_fixed)}명, 코스 {len(courses)}건, 조퇴 {len(st.session_state.early_leave)}건, 지각 {len(st.session_state.late_start)}건")

with b2:
    if st.button("🧠 오후 GPT 인식"):
        if not a_file:
            st.warning("오후 이미지를 업로드하세요.")
        else:
            names, _, excluded, early, late = gpt_extract(
                a_file.read(), want_early=True, want_late=True, want_excluded=True
            )
            fixed = [correct_name_v2(n, employee_ls, cut=cutoff) for n in names]
            excluded_fixed = [correct_name_v2(n, employee_ls, cut=cutoff) for n in excluded]
            for e in early: e["name"] = correct_name_v2(e.get("name",""), employee_ls, cut=cutoff)
            for l in late:  l["name"] = correct_name_v2(l.get("name",""), employee_ls, cut=cutoff)

            st.session_state.a_names_raw = fixed
            st.session_state.excluded_auto_pm = excluded_fixed
            st.session_state.early_leave_pm = [e for e in early if e.get("time") is not None]
            st.session_state.late_start_pm = [l for l in late if l.get("time") is not None]
            st.success(f"오후 인식 → 근무자 {len(fixed)}명 (보조 제외자 {len(excluded_fixed)})")

# -----------------------
# 제외자/오전/오후 텍스트 입력(스크롤)
# -----------------------
st.markdown("<h4 style='font-size:16px; margin-top:8px;'>🚫 근무 제외자 (자동 추출 후 수정 가능)</h4>", unsafe_allow_html=True)
excluded_text = st.text_area("제외자", "\n".join(st.session_state.get("excluded_auto", [])), height=120)
excluded_set = {normalize_name(x) for x in excluded_text.splitlines() if x.strip()}

st.markdown("<h4 style='font-size:18px;'>🌅 오전 근무자 (수정 가능)</h4>", unsafe_allow_html=True)
morning_text = st.text_area("오전 근무자", "\n".join(st.session_state.get("m_names_raw", [])), height=220)
m_list = [x.strip() for x in morning_text.splitlines() if x.strip()]

st.markdown("<h4 style='font-size:18px;'>🌇 오후 근무자 (수정 가능)</h4>", unsafe_allow_html=True)
afternoon_text = st.text_area("오후 근무자", "\n".join(st.session_state.get("a_names_raw", [])), height=220)
a_list = [x.strip() for x in afternoon_text.splitlines() if x.strip()]

early_leave = st.session_state.get("early_leave", [])
late_start  = st.session_state.get("late_start", [])

m_norms = {normalize_name(x) for x in m_list} - excluded_set
a_norms = {normalize_name(x) for x in a_list} - excluded_set

# -----------------------
# 2️⃣ 오전 배정
# -----------------------
st.markdown("### 📋 오전 근무 배정")
if st.button("🚗 오전 배정 생성"):
    try:
        key_order   = st.session_state.get("key_order", [])
        gyoyang_ord = st.session_state.get("gyoyang_order", [])
        sudong_ord  = st.session_state.get("sudong_order", [])
        veh1_map    = st.session_state.get("veh1", {})
        veh2_map    = st.session_state.get("veh2", {})
        sudong_count= st.session_state.get("sudong_count", 1)
        repairs     = st.session_state.get("repair_cars", [])

        # 🔑 열쇠 (제외자 반영 + 역매핑 안전화)
        today_key = ""
        if key_order:
            valid_keys = [x for x in key_order if normalize_name(x) not in excluded_set]
            norm_list  = [normalize_name(x) for x in valid_keys]
            prev_norm  = normalize_name(prev_key)
            pick_norm  = None
            if prev_norm in norm_list:
                pick_norm = norm_list[(norm_list.index(prev_norm)+1) % len(norm_list)]
            elif norm_list:
                pick_norm = norm_list[0]
            if pick_norm:
                found = [x for x in valid_keys if normalize_name(x) == pick_norm]
                today_key = found[0] if found else (valid_keys[0] if valid_keys else "")
        st.session_state.today_key = today_key

        # 🧑‍🏫 교양 1·2교시 (지각 반영해 1교시 제한)
        gy1 = pick_next_from_cycle(gyoyang_ord, prev_gy5, m_norms)
        if gy1 and not can_attend_period_morning(gy1, 1, late_start):
            gy1 = pick_next_from_cycle(gyoyang_ord, gy1, m_norms)
        used_norm = {normalize_name(gy1)} if gy1 else set()
        gy2 = pick_next_from_cycle(gyoyang_ord, gy1 or prev_gy5, m_norms - used_norm)
        st.session_state.gy_start_pm = gy2 if gy2 else prev_gy5

        # 🔧 1종 수동
        sud_m, last = [], prev_sud
        for _ in range(sudong_count):
            pick = pick_next_from_cycle(sudong_ord, last, m_norms - {normalize_name(x) for x in sud_m})
            if not pick: break
            sud_m.append(pick); last = pick
        st.session_state.sud_base_pm = sud_m[-1] if sud_m else prev_sud

        # 🚗 2종 자동 (오전 전체 - 1종)
        sud_norms = {normalize_name(x) for x in sud_m}
        auto_m = [x for x in m_list if normalize_name(x) in (m_norms - sud_norms)]

        # 오전 차량 기록 (오후 비교용)
        st.session_state.morning_assigned_cars_1 = [get_vehicle(x, veh1_map) for x in sud_m if get_vehicle(x, veh1_map)]
        st.session_state.morning_assigned_cars_2 = [get_vehicle(x, veh2_map) for x in auto_m if get_vehicle(x, veh2_map)]
        st.session_state.morning_auto_names = auto_m + sud_m

        # === 출력 ===
        lines = []
        if today_key: lines.append(f"열쇠: {today_key}")
        if gy1: lines.append(f"1교시: {gy1}")
        if gy2: lines.append(f"2교시: {gy2}")

        if sud_m:
            for nm in sud_m:
                lines.append(f"1종수동: {nm} {mark_car(get_vehicle(nm, veh1_map), repairs)}")
            if sudong_count == 2 and len(sud_m) < 2:
                lines.append("※ 수동 가능 인원이 1명입니다.")
        else:
            lines.append("1종수동: (배정자 없음)")
            if sudong_count >= 1:
                lines.append("※ 수동 가능 인원이 0명입니다.")

        if auto_m:
            lines.append("2종자동:")
            for nm in auto_m:
                lines.append(f" • {nm} {mark_car(get_vehicle(nm, veh2_map), repairs)}")

        # 🧭 코스점검 결과 (오전)
        course_records = st.session_state.get("course_records", [])
        if course_records:
            lines.append("")
            lines.append("🧭 코스점검 결과:")
            for c in ["A","B"]:
                passed = [r["name"] for r in course_records if r["course"]==f"{c}코스" and r["result"]=="합격"]
                failed = [r["name"] for r in course_records if r["course"]==f"{c}코스" and r["result"]=="불합격"]
                if passed: lines.append(f" • {c}코스 합격: {', '.join(passed)}")
                if failed: lines.append(f" • {c}코스 불합격: {', '.join(failed)}")

        am_text = "\n".join(lines)
        st.markdown("#### 📋 오전 결과")
        st.code(am_text, language="text")
        clipboard_copy_button("📋 결과 복사하기", am_text)

    except Exception as e:
        st.error(f"오전 오류: {e}")
# -----------------------
# 4️⃣ 오후 근무 배정 (조퇴 반영) + 오전 대비 비교 + 저장
# -----------------------
st.markdown("<h4 style='font-size:18px;'>4️⃣ 오후 근무 배정</h4>", unsafe_allow_html=True)
save_check = st.checkbox("이 결과를 전일근무.json 에 저장", value=True)

if st.button("🌇 오후 배정 생성"):
    try:
        gyoyang_ord = st.session_state.get("gyoyang_order", [])
        sudong_ord  = st.session_state.get("sudong_order", [])
        veh1_map    = st.session_state.get("veh1", {})
        veh2_map    = st.session_state.get("veh2", {})
        sudong_count= st.session_state.get("sudong_count", 1)
        repairs     = st.session_state.get("repair_cars", [])

        today_key = st.session_state.get("today_key", prev_key)
        gy_start  = st.session_state.get("gy_start_pm", prev_gy5) or prev_gy5
        sud_base  = st.session_state.get("sud_base_pm", prev_sud)
        excluded_set = {normalize_name(x) for x in st.session_state.get("excluded_auto", [])}

        # 오후 근무자 / 제외 반영
        a_list = [x.strip() for x in st.session_state.get("a_names_raw", [])]
        a_norms = {normalize_name(x) for x in a_list} - excluded_set

        # 조퇴(오전 인식값 재사용; 필요시 pm 값과 병합 가능)
        early_leave = st.session_state.get("early_leave", [])

        # 🧑‍🏫 교양 3~5교시 (조퇴 반영)
        used=set(); gy3=gy4=gy5=None; last_ptr=gy_start
        for period in [3,4,5]:
            while True:
                pick = pick_next_from_cycle(gyoyang_ord, last_ptr, a_norms - used)
                if not pick: break
                last_ptr = pick
                if can_attend_period_afternoon(pick, period, early_leave):
                    if period==3: gy3=pick
                    elif period==4: gy4=pick
                    else: gy5=pick
                    used.add(normalize_name(pick))
                    break

        # 🔧 오후 1종 수동
        sud_a,last=[],sud_base
        for _ in range(sudong_count):
            pick=pick_next_from_cycle(sudong_ord,last,a_norms)  # 교양자도 허용
            if not pick: break
            sud_a.append(pick); last=pick

        # 🚗 오후 2종 자동 (1종 제외)
        sud_a_norms={normalize_name(x) for x in sud_a}
        auto_a=[x for x in a_list if normalize_name(x) in (a_norms - sud_a_norms)]

        # === 출력 ===
        lines=[]
        if today_key: lines.append(f"열쇠: {today_key}")
        if gy3: lines.append(f"3교시: {gy3}")
        if gy4: lines.append(f"4교시: {gy4}")
        if gy5: lines.append(f"5교시: {gy5}")

        if sud_a:
            for nm in sud_a:
                lines.append(f"1종수동: {nm} {mark_car(get_vehicle(nm, veh1_map), repairs)}")
            if sudong_count==2 and len(sud_a)<2:
                lines.append("※ 수동 가능 인원이 1명입니다.")
        else:
            lines.append("1종수동: (배정자 없음)")

        if auto_a:
            lines.append("2종자동:")
            for nm in auto_a:
                lines.append(f" • {nm} {mark_car(get_vehicle(nm, veh2_map), repairs)}")

        # === 오전 대비 비교 ===
        lines.append("")
        lines.append("🔍 오전 대비 비교:")
        morning_auto_names=set(st.session_state.get("morning_auto_names", []))
        afternoon_auto_names=set(auto_a)
        afternoon_sudong_norms={normalize_name(x) for x in sud_a}

        added=sorted(list(afternoon_auto_names - morning_auto_names))
        missing=[]
        for nm in morning_auto_names:
            n_norm=normalize_name(nm)
            if n_norm not in {normalize_name(x) for x in auto_a} and n_norm not in afternoon_sudong_norms:
                missing.append(nm)

        newly_joined=sorted([
            x for x in a_list
            if normalize_name(x) not in {normalize_name(y) for y in st.session_state.get("morning_auto_names", [])}
        ])

        if added:        lines.append(" • 추가 인원: " + ", ".join(added))
        if missing:      lines.append(" • 빠진 인원: " + ", ".join(missing))
        if newly_joined: lines.append(" • 신규 도로주행 인원: " + ", ".join(newly_joined))

        # === 미배정 차량 (오전 → 오후 빠진 차량만)
        am_c1=set(st.session_state.get("morning_assigned_cars_1", []))
        am_c2=set(st.session_state.get("morning_assigned_cars_2", []))
        pm_c1={get_vehicle(x,veh1_map) for x in sud_a if get_vehicle(x,veh1_map)}
        pm_c2={get_vehicle(x,veh2_map) for x in auto_a if get_vehicle(x,veh2_map)}
        un1=sorted([c for c in am_c1 if c and c not in pm_c1])
        un2=sorted([c for c in am_c2 if c and c not in pm_c2])
        if un1 or un2:
            lines.append("")
            lines.append("🚫 미배정 차량:")
            if un1:
                lines.append(" [1종 수동]")
                for c in un1: lines.append(f"  • {c} 마감")
            if un2:
                lines.append(" [2종 자동]")
                for c in un2: lines.append(f"  • {c} 마감")

        pm_text="\n".join(lines)
        st.markdown("#### 🌇 오후 결과")
        st.code(pm_text, language="text")
        clipboard_copy_button("📋 결과 복사하기", pm_text)

        # ✅ 전일 저장
        if save_check:
            best_gy = gy5 or gy4 or gy3 or prev_gy5
            save_json(PREV_FILE, {
                "열쇠": today_key,
                "교양_5교시": best_gy,
                "1종수동": (sud_a[-1] if sud_a else prev_sud)
            })
            st.success("전일근무.json 업데이트 완료")

    except Exception as e:
        st.error(f"오후 오류: {e}")
