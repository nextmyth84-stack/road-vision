# =====================================
# app.py — 도로주행 근무자동배정 v7.23 (완전본)
# =====================================
import streamlit as st
from openai import OpenAI
import base64, re, json, os, difflib

# -----------------------
# 페이지 설정
# -----------------------
st.set_page_config(page_title="도로주행 근무자동배정 v7.23", layout="wide")
st.markdown("<h3 style='text-align:center; font-size:22px;'>🚗 도로주행 근무자동배정 v7.23</h3>", unsafe_allow_html=True)

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
# 공용 JSON 유틸
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
# 전일 기준 데이터
# -----------------------
PREV_FILE = "전일근무.json"
prev_data = load_json(PREV_FILE, {"열쇠": "", "교양_5교시": "", "1종수동": ""})
prev_key = prev_data.get("열쇠", "")
prev_gyoyang5 = prev_data.get("교양_5교시", "")
prev_sudong = prev_data.get("1종수동", "")

# -----------------------
# 클립보드 복사 버튼 (코드 노출 방지)
# -----------------------
def clipboard_copy_button(label, text):
    btn_id = f"btn_{abs(hash(label+text))}"
    safe_text = text.replace("\\", "\\\\").replace("`", "\\`").replace('"', '\\"')
    html = f"""
    <button id="{btn_id}" style="background:#2563eb;color:white;border:none;
    padding:6px 12px;border-radius:8px;cursor:pointer;margin-top:6px;">
    {label}</button>
    <script>
    const b = document.getElementById("{btn_id}");
    if (b) {{
        b.onclick = () => {{
            navigator.clipboard.writeText("{safe_text}");
            const t=b.innerText; b.innerText="✅ 복사됨!";
            setTimeout(()=>b.innerText=t,1500);
        }};
    }}
    </script>
    """
    st.components.v1.html(html, height=45)

# -----------------------
# 이름/차량/순번/교정 함수
# -----------------------
def normalize_name(s):
    """괄호·공백·특수문자 제거 → 순수 한글 이름"""
    return re.sub(r"[^가-힣]", "", re.sub(r"\(.*?\)", "", s or ""))

def get_vehicle(name, veh_map):
    """veh_map={차량번호:이름} → 이름으로 차량번호 찾기"""
    nkey = normalize_name(name)
    for car, nm in veh_map.items():
        if normalize_name(nm) == nkey:
            return car
    return ""

def mark_car(car, repair_cars):
    return f"{car}{' (정비)' if car in repair_cars else ''}" if car else ""

def pick_next_from_cycle(cycle, last, allowed_norms: set):
    """순번 회전 (allowed_norms 내에서만 선택)"""
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
# OCR 인식 (코스 분리)
# -----------------------
def gpt_extract(img_bytes):
    """
    반환: (names_without_paren, course_records)
    course_records = [{name, course: 'A코스'/'B코스', result: '합격'/'불합격'}]
    """
    b64 = base64.b64encode(img_bytes).decode()
    prompt = (
        "이 이미지는 도로주행 근무표입니다.\n"
        "1) '학과','기능','PC','초소' 등은 제외하고 도로주행 근무자만 추출.\n"
        "2) 괄호 속 'A-합','B-불','A합','B불' 등은 코스점검 결과로 해석.\n"
        "3) JSON으로 반환: {\"names\": [\"김성연(B합)\",\"김병욱(A불)\"]}"
    )
    try:
        res = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "표에서 이름을 JSON으로 추출"},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]}
            ]
        )
        raw = res.choices[0].message.content
        js = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        raw_names = js.get("names", [])

        names, course_records = [], []
        for n in raw_names:
            m = re.search(r"([가-힣]+)\s*\(([^)]*)\)", n)
            if m:
                name = m.group(1).strip()
                detail = re.sub(r"[^A-Za-z가-힣]", "", m.group(2)).upper()  # 특수문자 제거 후 A/B 인지만
                course = "A" if "A" in detail else ("B" if "B" in detail else None)
                result = "합격" if "합" in detail else ("불합격" if "불" in detail else None)
                if course and result:
                    course_records.append({"name": name, "course": f"{course}코스", "result": result})
                names.append(name)  # 순번용: 괄호 제거된 이름만
            else:
                names.append(n.strip())
        return names, course_records
    except Exception as e:
        st.error(f"OCR 실패: {e}")
        return [], []
# -----------------------
# JSON 기반 순번 / 차량 / 근무자 관리 (파일)
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

# 로드
key_order = load_json(files["열쇠"])
gyoyang_order = load_json(files["교양"])
sudong_order = load_json(files["1종"])
veh1_map = load_json(files["veh1"])
veh2_map = load_json(files["veh2"])
employee_list = load_json(files["employees"])

# -----------------------
# 사이드바: 파일 기반 관리 UI (기본 숨김)
# -----------------------
st.sidebar.header("📂 데이터 관리")
with st.sidebar.expander("🔑 열쇠 순번", expanded=False):
    t = st.text_area("열쇠 순번", "\n".join(key_order), height=180)
    if st.button("저장 (열쇠 순번)"):
        save_json(files["열쇠"], [x.strip() for x in t.splitlines() if x.strip()])
        key_order = load_json(files["열쇠"]); st.success("열쇠 순번 저장 완료")

with st.sidebar.expander("📘 교양 순번", expanded=False):
    t = st.text_area("교양 순번", "\n".join(gyoyang_order), height=180)
    if st.button("저장 (교양 순번)"):
        save_json(files["교양"], [x.strip() for x in t.splitlines() if x.strip()])
        gyoyang_order = load_json(files["교양"]); st.success("교양 순번 저장 완료")

with st.sidebar.expander("🧰 1종 수동 순번", expanded=False):
    t = st.text_area("1종 수동 순번", "\n".join(sudong_order), height=180)
    if st.button("저장 (1종 수동 순번)"):
        save_json(files["1종"], [x.strip() for x in t.splitlines() if x.strip()])
        sudong_order = load_json(files["1종"]); st.success("1종 수동 순번 저장 완료")

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
    t = st.text_area("전체 근무자 명단", "\n".join(employee_list), height=200)
    if st.button("저장 (전체 근무자)"):
        save_json(files["employees"], [x.strip() for x in t.splitlines() if x.strip()])
        employee_list = load_json(files["employees"]); st.success("전체 근무자 저장 완료")

sudong_count = st.sidebar.radio("1종 수동 인원수", [1, 2], index=0)
repair_cars = [x.strip() for x in st.sidebar.text_input("정비 차량 (쉼표로 구분)", value="").split(",") if x.strip()]
st.sidebar.info(f"전일 기준 → 열쇠:{prev_key or '-'}, 교양5:{prev_gyoyang5 or '-'}, 1종:{prev_sudong or '-'}")

# 세션 상태
st.session_state.key_order = key_order
st.session_state.gyoyang_order = gyoyang_order
st.session_state.sudong_order = sudong_order
st.session_state.veh1 = veh1_map
st.session_state.veh2 = veh2_map
st.session_state.employee_list = employee_list
st.session_state.sudong_count = sudong_count
st.session_state.repair_cars = repair_cars
st.session_state.prev_key = prev_key
st.session_state.prev_gyoyang5 = prev_gyoyang5
st.session_state.prev_sudong = prev_sudong

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
            names, course = gpt_extract(m_file.read())
            fixed = [correct_name_v2(n, employee_list, cutoff=0.6) for n in names]
            st.session_state.m_names_raw = fixed         # 괄호 제거된 이름
            st.session_state.course_records = course     # 코스 점검 기록
            st.success(f"오전 인식 → 근무자 {len(fixed)}명, 코스기록 {len(course)}건")

with b2:
    if st.button("🧠 오후 GPT 인식"):
        if not a_file:
            st.warning("오후 이미지를 업로드하세요.")
        else:
            names, _ = gpt_extract(a_file.read())
            fixed = [correct_name_v2(n, employee_list, cutoff=0.6) for n in names]
            st.session_state.a_names_raw = fixed
            st.success(f"오후 인식 → 근무자 {len(fixed)}명")
# -----------------------
# 2️⃣ 오전 근무자 입력 + 오전 배정 (바로 아래 배치)
# -----------------------
st.markdown("<h4 style='font-size:18px;'>🌅 오전 근무자 (수정 가능)</h4>", unsafe_allow_html=True)
morning_text = st.text_area("오전 근무자",
                            "\n".join(st.session_state.get("m_names_raw", [])),
                            height=220)
m_list = [x.strip() for x in morning_text.splitlines() if x.strip()]

st.markdown("### 📋 오전 근무 배정")
if st.button("🚗 오전 배정 생성"):
    try:
        key_order = st.session_state.get("key_order", [])
        gyoyang_order = st.session_state.get("gyoyang_order", [])
        sudong_order = st.session_state.get("sudong_order", [])
        veh1_map = st.session_state.get("veh1", {})
        veh2_map = st.session_state.get("veh2", {})
        sudong_count = st.session_state.get("sudong_count", 1)
        repair_cars = st.session_state.get("repair_cars", [])

        # 🔑 열쇠 회전
        today_key = ""
        if key_order:
            norm_list = [normalize_name(x) for x in key_order]
            prev_norm = normalize_name(prev_key)
            if prev_norm in norm_list:
                idx = (norm_list.index(prev_norm) + 1) % len(key_order)
                today_key = key_order[idx]
            else:
                today_key = key_order[0]
        st.session_state.today_key = today_key

        m_norms = {normalize_name(x) for x in m_list}

        # 🧑‍🏫 교양 1·2교시
        gy1 = pick_next_from_cycle(gyoyang_order, prev_gyoyang5, m_norms)
        gy2 = pick_next_from_cycle(gyoyang_order, gy1 or prev_gyoyang5, m_norms - ({normalize_name(gy1)} if gy1 else set()))
        st.session_state.gyoyang_base_for_pm = gy2 if gy2 else prev_gyoyang5

        # 🔧 1종 수동
        sud_m, last = [], prev_sudong
        for _ in range(sudong_count):
            pick = pick_next_from_cycle(sudong_order, last, m_norms - {normalize_name(x) for x in sud_m})
            if not pick: break
            sud_m.append(pick); last = pick
        st.session_state.sudong_base_for_pm = sud_m[-1] if sud_m else prev_sudong

        # 🚗 2종 자동 = 오전 전체 - 1종
        sud_norms = {normalize_name(x) for x in sud_m}
        auto_m = [x for x in m_list if normalize_name(x) in (m_norms - sud_norms)]

        # 오전 차량 기록(오후 비교용)
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
                lines.append(f"1종수동: {nm} {mark_car(get_vehicle(nm, veh1_map), repair_cars)}")
            if sudong_count == 2 and len(sud_m) < 2:
                lines.append("※ 수동 가능 인원이 1명입니다.")
        else:
            lines.append("1종수동: (배정자 없음)")
            if sudong_count >= 1:
                lines.append("※ 수동 가능 인원이 0명입니다.")

        if auto_m:
            lines.append("2종자동:")
            for nm in auto_m:
                lines.append(f" • {nm} {mark_car(get_vehicle(nm, veh2_map), repair_cars)}")

        # 🧭 코스점검 결과 (오전만)
        course_records = st.session_state.get("course_records", [])
        if course_records:
            lines.append("")
            lines.append("🧭 코스점검 결과:")
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

# -----------------------
# 3️⃣ 오후 근무자 입력
# -----------------------
st.markdown("<h4 style='font-size:18px;'>🌇 오후 근무자 (수정 가능)</h4>", unsafe_allow_html=True)
afternoon_text = st.text_area("오후 근무자",
                              "\n".join(st.session_state.get("a_names_raw", [])),
                              height=220)
a_list = [x.strip() for x in afternoon_text.splitlines() if x.strip()]
# -----------------------
# 4️⃣ 오후 근무 배정 + 오전 대비 비교 + 저장
# -----------------------
st.markdown("<h4 style='font-size:18px;'>4️⃣ 오후 근무 배정</h4>", unsafe_allow_html=True)
save_check = st.checkbox("이 결과를 전일근무.json 에 저장", value=True)

if st.button("🌇 오후 배정 생성"):
    try:
        gyoyang_order = st.session_state.get("gyoyang_order", [])
        sudong_order = st.session_state.get("sudong_order", [])
        veh1_map = st.session_state.get("veh1", {})
        veh2_map = st.session_state.get("veh2", {})
        sudong_count = st.session_state.get("sudong_count", 1)
        repair_cars = st.session_state.get("repair_cars", [])

        today_key = st.session_state.get("today_key", prev_key)
        gy_start = st.session_state.get("gyoyang_base_for_pm", prev_gyoyang5)
        if not gy_start and gyoyang_order:
            gy_start = gyoyang_order[0]
        sud_base = st.session_state.get("sudong_base_for_pm", prev_sudong)

        a_norms = {normalize_name(x) for x in a_list}

        # 🧑‍🏫 교양 3~5교시
        used = set()
        gy3 = pick_next_from_cycle(gyoyang_order, gy_start, a_norms)
        if gy3: used.add(normalize_name(gy3))
        gy4 = pick_next_from_cycle(gyoyang_order, gy3 or gy_start, a_norms - used)
        if gy4: used.add(normalize_name(gy4))
        gy5 = pick_next_from_cycle(gyoyang_order, gy4 or gy3 or gy_start, a_norms - used)

        # 🔧 오후 1종 수동
        sud_a, last = [], sud_base
        for _ in range(sudong_count):
            pick = pick_next_from_cycle(sudong_order, last, a_norms)  # 교양 배정자도 허용
            if not pick: break
            sud_a.append(pick); last = pick

        # 🚗 오후 2종 자동 (1종 제외)
        sud_a_norms = {normalize_name(x) for x in sud_a}
        auto_a = [x for x in a_list if normalize_name(x) in (a_norms - sud_a_norms)]

        # === 출력 ===
        lines = []
        if today_key: lines.append(f"열쇠: {today_key}")
        if gy3: lines.append(f"3교시: {gy3}")
        if gy4: lines.append(f"4교시: {gy4}")
        if gy5: lines.append(f"5교시: {gy5}")

        if sud_a:
            for nm in sud_a:
                lines.append(f"1종수동: {nm} {mark_car(get_vehicle(nm, veh1_map), repair_cars)}")
            if sudong_count == 2 and len(sud_a) < 2:
                lines.append("※ 수동 가능 인원이 1명입니다.")
        else:
            lines.append("1종수동: (배정자 없음)")

        if auto_a:
            lines.append("2종자동:")
            for nm in auto_a:
                lines.append(f" • {nm} {mark_car(get_vehicle(nm, veh2_map), repair_cars)}")

        # === 오전 대비 비교 ===
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
        if missing:      lines.append(" • 빠진 인원: " + ", ".join(missing))
        if newly_joined: lines.append(" • 신규 도로주행 인원: " + ", ".join(newly_joined))

        # === 미배정 차량 (오전 → 오후 빠진 차량만)
        am_c1 = set(st.session_state.get("morning_assigned_cars_1", []))
        am_c2 = set(st.session_state.get("morning_assigned_cars_2", []))
        pm_c1 = {get_vehicle(x, veh1_map) for x in sud_a if get_vehicle(x, veh1_map)}
        pm_c2 = {get_vehicle(x, veh2_map) for x in auto_a if get_vehicle(x, veh2_map)}
        un1 = sorted([c for c in am_c1 if c and c not in pm_c1])
        un2 = sorted([c for c in am_c2 if c and c not in pm_c2])
        if un1 or un2:
            lines.append("")
            lines.append("🚫 미배정 차량:")
            if un1:
                lines.append(" [1종 수동]")
                for c in un1: lines.append(f"  • {c} 마감")
            if un2:
                lines.append(" [2종 자동]")
                for c in un2: lines.append(f"  • {c} 마감")

        pm_text = "\n".join(lines)
        st.markdown("#### 🌇 오후 결과")
        st.code(pm_text, language="text")
        clipboard_copy_button("📋 결과 복사하기", pm_text)

        # ✅ 전일 저장
        if save_check:
            save_json(PREV_FILE, {
                "열쇠": today_key,
                "교양_5교시": gy5 or gy4 or gy3 or prev_gyoyang5,
                "1종수동": (sud_a[-1] if sud_a else prev_sudong)
            })
            st.success("전일근무.json 업데이트 완료")

    except Exception as e:
        st.error(f"오후 오류: {e}")
