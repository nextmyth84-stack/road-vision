# =====================================
# app.py — 도로주행 근무자동배정 v7.14.6 (완전본)
# =====================================
import streamlit as st
from openai import OpenAI
import base64, re, json, os

# =====================================
# 기본 설정
# =====================================
st.set_page_config(page_title="도로주행 근무자동배정 v7.14.6", layout="wide")
st.markdown("<h3 style='text-align:center; font-size:22px;'>🚗 도로주행 근무자동배정 v7.14.6</h3>", unsafe_allow_html=True)

# =====================================
# OpenAI 초기화
# =====================================
try:
    client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
except Exception:
    st.error("⚠️ OPENAI_API_KEY 설정 필요")
    st.stop()
MODEL_NAME = "gpt-4o"

# =====================================
# JSON 저장/로드 유틸
# =====================================
def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_json(path, default=None):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default or {}

# =====================================
# 전일 기준 불러오기
# =====================================
PREV_FILE = "전일근무.json"
prev = load_json(PREV_FILE, {"열쇠": "", "교양_5교시": "", "1종수동": ""})
prev_key, prev_gyoyang5, prev_sudong = prev["열쇠"], prev["교양_5교시"], prev["1종수동"]
st.info(f"전일 불러옴 → 열쇠:{prev_key or '-'}, 교양5:{prev_gyoyang5 or '-'}, 1종:{prev_sudong or '-'}")

# =====================================
# 사이드바 입력
# =====================================
st.sidebar.header("순번표 / 차량표 / 옵션")

def _list(s): return [x.strip() for x in s.splitlines() if x.strip()]

# 🔹 순번표 파일 로드
SEQ_FILE = "순번표.json"
default_seq = {
    "열쇠": """권한솔
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
조정래""",
    "교양": """권한솔
김남균
김면정
김병욱
김성연
김주현
김지은
안유미
이호석
조정래""",
    "1종수동": """권한솔
김남균
김성연
김주현
이호석
조정래"""
}
if not os.path.exists(SEQ_FILE): save_json(SEQ_FILE, default_seq)
seq_data = load_json(SEQ_FILE, default_seq)

with st.sidebar.expander("🗝️ 순번표 보기/수정", expanded=False):
    key_text = st.text_area("열쇠 순번", seq_data["열쇠"], height=160)
    gy_text = st.text_area("교양 순번", seq_data["교양"], height=160)
    sud_text = st.text_area("1종 수동 순번", seq_data["1종수동"], height=160)
if st.sidebar.button("💾 순번표 저장"):
    seq_data["열쇠"], seq_data["교양"], seq_data["1종수동"] = key_text, gy_text, sud_text
    save_json(SEQ_FILE, seq_data)
    st.sidebar.success("✅ 순번표.json 저장 완료")

key_order = _list(seq_data["열쇠"])
gyoyang_order = _list(seq_data["교양"])
sudong_order = _list(seq_data["1종수동"])

# 🔹 차량표 파일 로드
VEH_FILE = "차량표.json"
default_veh = {
    "1종수동": """2호 조정래
5호 권한솔
7호 김남균
8호 이호석
9호 김주현
10호 김성연""",
    "2종자동": """4호 김남균
5호 김병욱
6호 김지은
12호 안유미
14호 김면정
15호 이호석
17호 김성연
18호 권한솔
19호 김주현
22호 조정래"""
}
if not os.path.exists(VEH_FILE): save_json(VEH_FILE, default_veh)
veh_data = load_json(VEH_FILE, default_veh)

with st.sidebar.expander("🚗 차량표 보기/수정", expanded=False):
    v1_text = st.text_area("1종 수동 차량표", veh_data["1종수동"], height=120)
    v2_text = st.text_area("2종 자동 차량표", veh_data["2종자동"], height=180)
if st.sidebar.button("💾 차량표 저장"):
    veh_data["1종수동"], veh_data["2종자동"] = v1_text, v2_text
    save_json(VEH_FILE, veh_data)
    st.sidebar.success("✅ 차량표.json 저장 완료")

def parse_vehicle_map(text):
    m = {}
    for line in text.splitlines():
        p = line.strip().split()
        if len(p) >= 2:
            car, name = p[0], " ".join(p[1:])
            m[name] = car
    return m
veh1, veh2 = parse_vehicle_map(veh_data["1종수동"]), parse_vehicle_map(veh_data["2종자동"])

# 옵션
sudong_count = st.sidebar.radio("1종 수동 인원수", [1, 2], index=0)
excluded = {x.strip() for x in st.sidebar.text_area("휴가/교육자 (한 줄당 한 명)").splitlines() if x.strip()}
repair_cars = [x.strip() for x in st.sidebar.text_input("정비 차량 (쉼표로 구분)").split(",") if x.strip()]

# =====================================
# 유틸 함수
# =====================================
def normalize_name(s): return re.sub(r"[^가-힣]", "", re.sub(r"\(.*?\)", "", s or ""))
def mark_car(car): return f"{car}{' (정비)' if car in repair_cars else ''}" if car else ""
def get_vehicle(name, veh_map):
    nkey = normalize_name(name)
    for k, v in veh_map.items():
        if normalize_name(k) == nkey: return v
    return ""

def pick_next_from_cycle(cycle, last, allowed):
    if not cycle: return None
    c_norm, last_norm = [normalize_name(x) for x in cycle], normalize_name(last)
    start = (c_norm.index(last_norm) + 1) % len(cycle) if last_norm in c_norm else 0
    for i in range(len(cycle) * 2):
        cand = cycle[(start + i) % len(cycle)]
        if normalize_name(cand) in allowed: return cand
    return None

def clipboard_copy_button(text):
    st.markdown(
        f"""
        <button onclick="navigator.clipboard.writeText(`{text}`)"
        style="padding:8px 16px; border:none; background:#4CAF50; color:white; border-radius:6px; cursor:pointer;">
        📋 결과 복사하기</button>
        """, unsafe_allow_html=True)

# =====================================
# GPT OCR (코스점검 분리, 순번 영향 X)
# =====================================
def gpt_extract(img_bytes):
    b64 = base64.b64encode(img_bytes).decode()
    user = (
        "이 이미지는 운전면허시험 근무표입니다.\n"
        "1) 도로주행 근무자 이름을 JSON으로 추출하세요.\n"
        "2) 이름 옆 괄호에 (A-합), (B-불) 등이 있으면 그대로 포함하세요.\n"
        "3) '지원','인턴','연수' 포함자는 제외하세요.\n"
        '반환 예시: {"names": ["김면정(A-합)","김성연(B-불)"]}'
    )
    try:
        res = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "표에서 이름과 코스점검 정보를 JSON으로 추출"},
                {"role": "user", "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]}
            ],
        )
        raw = res.choices[0].message.content
        js = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        full = [n.strip() for n in js.get("names", []) if not re.search(r"(지원|인턴|연수)", n)]

        course_info, names = [], []
        for n in full:
            m = re.search(r"(A[-–]?\s*합|B[-–]?\s*불)", n)
            if m:
                course_info.append({
                    "name": re.sub(r"\(.*?\)", "", n).strip(),
                    "course": m.group(1).replace(" ", "")
                })
            names.append(re.sub(r"\(.*?\)", "", n).strip())
        return names, course_info
    except Exception as e:
        st.error(f"OCR 실패: {e}")
        return [], []

# =====================================
# 오전 근무 OCR + 배정
# =====================================
st.markdown("<h4>1️⃣ 오전 근무표 업로드</h4>", unsafe_allow_html=True)
m_file = st.file_uploader("📸 오전 근무표", type=["png", "jpg", "jpeg"])
if st.button("🧠 오전 GPT 인식"):
    if not m_file:
        st.warning("오전 이미지를 업로드하세요.")
    else:
        with st.spinner("GPT 분석 중..."):
            m_names, course_info = gpt_extract(m_file.read())
            st.session_state.m_names_raw = m_names
            st.session_state.course_info = course_info
            st.success(f"오전 인식 완료: {len(m_names)}명")
        st.rerun()

morning = st.text_area("오전 근무자 (수정 가능)", "\n".join(st.session_state.get("m_names_raw", [])), height=150)
m_list = [x.strip() for x in morning.splitlines() if x.strip()]
m_norms = {normalize_name(x) for x in m_list} - {normalize_name(x) for x in excluded}

if st.button("📋 오전 배정 생성"):
    try:
        lines = []
        # 열쇠
        key_filtered = [x for x in key_order if normalize_name(x) not in {normalize_name(e) for e in excluded}]
        today_key = pick_next_from_cycle(key_filtered, prev_key, m_norms)
        st.session_state.today_key = today_key

        # 교양 1·2교시
        gy1 = pick_next_from_cycle(gyoyang_order, prev_gyoyang5, m_norms)
        gy2 = pick_next_from_cycle(gyoyang_order, gy1 or prev_gyoyang5, m_norms - {normalize_name(gy1)} if gy1 else m_norms)
        st.session_state.gyoyang_base_for_pm = gy2 or prev_gyoyang5

        # 1종 수동
        sud_m, last = [], prev_sudong
        for _ in range(sudong_count):
            pick = pick_next_from_cycle(sudong_order, last, m_norms - {normalize_name(x) for x in sud_m})
            if not pick: break
            sud_m.append(pick)
            last = pick
        st.session_state["sudong_base_for_pm"] = sud_m[-1] if sud_m else prev_sudong

        # 2종 자동
        sud_norms = {normalize_name(x) for x in sud_m}
        auto_m = [x for x in m_list if normalize_name(x) in (m_norms - sud_norms)]

        lines.append(f"열쇠: {today_key}")
        if gy1: lines.append(f"1교시(교양): {gy1}")
        if gy2: lines.append(f"2교시(교양): {gy2}")
        for nm in sud_m:
            lines.append(f"1종수동: {nm} {mark_car(get_vehicle(nm, veh1))}")
        if auto_m:
            lines.append("2종 자동:")
            for nm in auto_m:
                lines.append(f" • {nm} {mark_car(get_vehicle(nm, veh2))}")

        # ✅ 코스점검 출력
        course_info = st.session_state.get("course_info", [])
        if course_info:
            a_list = [x["name"] for x in course_info if x["course"].startswith("A")]
            b_list = [x["name"] for x in course_info if x["course"].startswith("B")]
            lines.append("\n코스점검:")
            if a_list: lines.append(f" A합 → {', '.join(a_list)}")
            if b_list: lines.append(f" B불 → {', '.join(b_list)}")

        result_text = "\n".join(lines)
        st.markdown("### 📋 오전 결과")
        st.code(result_text, language="text")
        clipboard_copy_button(result_text)

    except Exception as e:
        st.error(f"오전 오류: {e}")

# =====================================
# 오후 근무 배정
# =====================================
st.markdown("<h4>2️⃣ 오후 근무표 업로드</h4>", unsafe_allow_html=True)
a_file = st.file_uploader("📸 오후 근무표", type=["png", "jpg", "jpeg"])
if st.button("🧠 오후 GPT 인식"):
    if not a_file:
        st.warning("오후 이미지를 업로드하세요.")
    else:
        with st.spinner("GPT 분석 중..."):
            a_names, _ = gpt_extract(a_file.read())
            st.session_state.a_names_raw = a_names
            st.success(f"오후 인식 완료: {len(a_names)}명")
        st.rerun()

afternoon = st.text_area("오후 근무자 (수정 가능)", "\n".join(st.session_state.get("a_names_raw", [])), height=150)
a_list = [x.strip() for x in afternoon.splitlines() if x.strip()]
a_norms = {normalize_name(x) for x in a_list} - {normalize_name(x) for x in excluded}
save_check = st.checkbox("이 결과를 '전일 기준'으로 저장", value=True)

if st.button("📋 오후 배정 생성"):
    try:
        lines = []
        today_key = st.session_state.get("today_key", prev_key)
        gy_start = st.session_state.get("gyoyang_base_for_pm", prev_gyoyang5)
        if not gy_start: gy_start = gyoyang_order[0] if gyoyang_order else None

        used = set()
        gy3 = pick_next_from_cycle(gyoyang_order, gy_start, a_norms)
        gy4 = pick_next_from_cycle(gyoyang_order, gy3 or gy_start, a_norms - {normalize_name(gy3)} if gy3 else a_norms)
        gy5 = pick_next_from_cycle(gyoyang_order, gy4 or gy_start, a_norms - {normalize_name(x) for x in [gy3, gy4] if x})

        sud_a, last = [], st.session_state.get("sudong_base_for_pm", prev_sudong)
        for _ in range(sudong_count):
            pick = pick_next_from_cycle(sudong_order, last, a_norms)
            if pick:
                sud_a.append(pick)
                last = pick
        sud_norms = {normalize_name(x) for x in sud_a}
        auto_a = [x for x in a_list if normalize_name(x) in (a_norms - sud_norms)]

        lines.append(f"열쇠: {today_key}")
        if gy3: lines.append(f"3교시(교양): {gy3}")
        if gy4: lines.append(f"4교시(교양): {gy4}")
        if gy5: lines.append(f"5교시(교양): {gy5}")

        for nm in sud_a:
            lines.append(f"1종수동: {nm} {mark_car(get_vehicle(nm, veh1))}")
        if auto_a:
            lines.append("2종 자동:")
            for nm in auto_a:
                lines.append(f" • {nm} {mark_car(get_vehicle(nm, veh2))}")

        # 오전 대비 비교
        lines.append("\n오전 대비 비교:")
        morning_auto = set(st.session_state.get("m_names_raw", []))
        missing = [x for x in morning_auto if normalize_name(x) not in {normalize_name(y) for y in auto_a + sud_a}]
        added = [x for x in a_list if normalize_name(x) not in {normalize_name(y) for y in morning_auto}]
        if added: lines.append(" • 추가 인원: " + ", ".join(added))
        if missing: lines.append(" • 빠진 인원: " + ", ".join(missing))

        result_text = "\n".join(lines)
        st.markdown("### 📋 오후 결과")
        st.code(result_text, language="text")
        clipboard_copy_button(result_text)

        # 전일 저장
        if save_check:
            save_json(PREV_FILE, {
                "열쇠": today_key,
                "교양_5교시": gy5 or gy4 or gy3 or prev_gyoyang
            }
