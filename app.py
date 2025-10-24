# app.py — 도로주행 근무자동배정 v7.14.3 (완전본, 복사버전)
# 기능 요약:
# ✅ JSON 기반 순번 관리 (없을 시 기본 자동생성)
# ✅ 전일값 저장 및 불러오기
# ✅ GPT OCR 이름 + 코스점검(A/B)
# ✅ 오전/오후 근무 자동배정
# ✅ 결과 복사 버튼만 제공 (파일 저장 없음)

import streamlit as st
from openai import OpenAI
import base64, re, json, os

# =====================================
# 페이지 설정
# =====================================
st.set_page_config(page_title="도로주행 근무자동배정", layout="wide")
st.markdown("<h3 style='text-align:center; font-size:22px;'>🚗 도로주행 근무자동배정 v7.14.3</h3>", unsafe_allow_html=True)

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
# 파일 로드/저장
# =====================================
SEQ_FILE = "순번데이터.json"
PREV_FILE = "전일근무.json"

def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# =====================================
# 기본 순번 데이터 (파일 없을 시 자동 생성)
# =====================================
default_seq = {
    "열쇠": [
        "권한솔", "김남균", "김면정", "김성연", "김지은", "안유미",
        "윤여헌", "윤원실", "이나래", "이호석", "조윤영", "조정래"
    ],
    "교양": [
        "권한솔", "김남균", "김면정", "김병욱", "김성연", "김주현",
        "김지은", "안유미", "이호석", "조정래"
    ],
    "1종수동": [
        "권한솔", "김남균", "김성연", "김주현", "이호석", "조정래"
    ]
}

if not os.path.exists(SEQ_FILE):
    save_json(SEQ_FILE, default_seq)
    st.sidebar.info("📄 순번데이터.json 파일이 없어서 기본 순번으로 새로 생성했습니다.")

seq_data = load_json(SEQ_FILE, default_seq)
prev_data = load_json(PREV_FILE, {"열쇠": "", "교양_5교시": "", "1종수동": ""})

prev_key = prev_data.get("열쇠", "")
prev_gyoyang5 = prev_data.get("교양_5교시", "")
prev_sudong = prev_data.get("1종수동", "")
st.info(f"전일 불러옴 → 열쇠:{prev_key or '-'}, 5교시:{prev_gyoyang5 or '-'}, 1종:{prev_sudong or '-'}")

# =====================================
# 사이드바: 순번/차량표/옵션
# =====================================
st.sidebar.header("🧾 순번표 관리 (JSON 저장)")

with st.sidebar.expander("🔑 열쇠 순번 보기/수정", expanded=False):
    key_text = st.text_area("열쇠 순번", "\n".join(seq_data.get("열쇠", [])), height=150)
with st.sidebar.expander("📚 교양 순번 보기/수정 (현재 배정 미사용)", expanded=False):
    gyo_text = st.text_area("교양 순번", "\n".join(seq_data.get("교양", [])), height=150)
with st.sidebar.expander("🧰 1종 수동 순번 보기/수정", expanded=False):
    sud_text = st.text_area("1종 수동 순번", "\n".join(seq_data.get("1종수동", [])), height=150)

if st.sidebar.button("💾 순번 저장"):
    seq_data["열쇠"] = [x.strip() for x in key_text.splitlines() if x.strip()]
    seq_data["교양"] = [x.strip() for x in gyo_text.splitlines() if x.strip()]
    seq_data["1종수동"] = [x.strip() for x in sud_text.splitlines() if x.strip()]
    save_json(SEQ_FILE, seq_data)
    st.sidebar.success("✅ 순번데이터.json 저장 완료")

key_order = seq_data.get("열쇠", [])
gyoyang_order = seq_data.get("교양", [])
sudong_order = seq_data.get("1종수동", [])

st.sidebar.markdown("---")
st.sidebar.subheader("🚗 차량표 / 옵션")

def parse_vehicle_map(text):
    m = {}
    for line in text.splitlines():
        p = line.strip().split()
        if len(p) >= 2:
            car = p[0]
            name = " ".join(p[1:])
            m[name] = car
    return m

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

veh1 = parse_vehicle_map(st.sidebar.text_area("1종 수동 차량표", default_cha1, height=120))
veh2 = parse_vehicle_map(st.sidebar.text_area("2종 자동 차량표", default_cha2, height=180))

sudong_count = st.sidebar.radio("1종 수동 인원수", [1, 2], index=0)
excluded = {x.strip() for x in st.sidebar.text_area("휴가/교육자 (한 줄당 한 명)", height=100).splitlines() if x.strip()}
repair_cars = [x.strip() for x in st.sidebar.text_input("정비 차량 (쉼표로 구분)", value="").split(",") if x.strip()]

# 전일값 직접 수정/저장
st.sidebar.markdown("---")
st.sidebar.subheader("🗓 전일값 확인/수정")
prev_key = st.sidebar.text_input("전일 열쇠", value=prev_key)
prev_gyoyang5 = st.sidebar.text_input("전일 교양5", value=prev_gyoyang5)
prev_sudong = st.sidebar.text_input("전일 1종수동", value=prev_sudong)
if st.sidebar.button("💾 전일값 저장"):
    save_json(PREV_FILE, {"열쇠": prev_key, "교양_5교시": prev_gyoyang5, "1종수동": prev_sudong})
    st.sidebar.success("✅ 전일근무.json 저장 완료")

# =====================================
# 유틸 함수
# =====================================
def normalize_name(s):
    return re.sub(r"[^가-힣]", "", re.sub(r"\(.*?\)", "", s or ""))

def pick_next_from_cycle(cycle, last, allowed_norms: set):
    if not cycle:
        return None
    cycle_norm = [normalize_name(x) for x in cycle]
    last_norm = normalize_name(last)
    start = 0
    if last_norm in cycle_norm:
        start = (cycle_norm.index(last_norm) + 1) % len(cycle)
    for i in range(len(cycle) * 2):
        cand = cycle[(start + i) % len(cycle)]
        if normalize_name(cand) in allowed_norms:
            return cand
    return None

def mark_car(car):
    return f"{car}{' (정비)' if car in repair_cars else ''}" if car else ""

def get_vehicle(name, veh_map):
    nkey = normalize_name(name)
    for k, v in veh_map.items():
        if normalize_name(k) == nkey:
            return v
    return ""

# =====================================
# GPT OCR (오전: 이름+코스 분리 저장)
# =====================================
def gpt_extract(img_bytes):
    b64 = base64.b64encode(img_bytes).decode()
    user = (
        "이 이미지는 운전면허시험 근무표입니다.\n"
        "1) '학과', '기능장', '초소'를 제외한 도로주행 근무자 이름만 추출하세요.\n"
        "2) 괄호안 정보(A-합, B-불 등)는 유지하되, 괄호에 '지원','인턴','연수' 포함자는 제외하세요.\n"
        "반환 예시: {\"names\": [\"김면정(A-합)\",\"김성연(B-불)\"]}"
    )
    try:
        res = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "표에서 이름을 JSON으로 추출"},
                {"role": "user", "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]}
            ],
        )
        raw = res.choices[0].message.content
        js = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        full_names = [n.strip() for n in js.get("names", []) if not re.search(r"(지원|인턴|연수)", n)]
        course_info, pure_names = [], []
        for n in full_names:
            m = re.search(r"\((A|B)\s*-\s*(합|불)\)", n)
            if m:
                course_info.append({"name": re.sub(r"\(.*?\)", "", n).strip(), "course": f"{m.group(1)}-{m.group(2)}"})
            pure_names.append(re.sub(r"\(.*?\)", "", n).strip())
        return pure_names, course_info
    except Exception as e:
        st.error(f"OCR 실패: {e}")
        return [], []

# =====================================
# 복사 버튼 함수
# =====================================
def clipboard_copy_button(text: str, label="📋 결과 복사"):
    escaped_text = text.replace("`", "\\`").replace("$", "\\$")
    script = f"""
    <script>
    async function copyToClipboard() {{
        await navigator.clipboard.writeText(`{escaped_text}`);
        alert("✅ 결과가 클립보드에 복사되었습니다.");
    }}
    </script>
    <button onclick="copyToClipboard()" style="background-color:#4CAF50;color:white;border:none;padding:8px 14px;border-radius:6px;cursor:pointer;">{label}</button>
    """
    st.markdown(script, unsafe_allow_html=True)

# =====================================
# 1) 오전 근무표 OCR 인식
# =====================================
st.markdown("<h4 style='font-size:18px;'>1️⃣ 오전 근무표 OCR 인식</h4>", unsafe_allow_html=True)
m_file = st.file_uploader("📸 오전 근무표 업로드", type=["png", "jpg", "jpeg"])
if st.button("🧠 오전 GPT 인식"):
    if not m_file:
        st.warning("오전 이미지를 업로드하세요.")
    else:
        with st.spinner("오전 GPT 분석 중..."):
            m_names, course_info = gpt_extract(m_file.read())
            st.session_state.m_names_raw = m_names
            st.session_state.course_info = course_info
            st.success(f"오전 인식 완료: {len(m_names)}명 (코스점검 {len(course_info)}명)")
        st.rerun()

# =====================================
# 2) 오전 근무 배정
# =====================================
st.markdown("<h4 style='font-size:18px;'>2️⃣ 오전 근무 배정</h4>", unsafe_allow_html=True)
morning = st.text_area("오전 근무자 (필요 시 수정)", "\n".join(st.session_state.get("m_names_raw", [])), height=150)
m_list = [x.strip() for x in morning.splitlines() if x.strip()]

if st.button("📋 오전 배정 생성"):
    try:
        lines = []
        allowed_m = {normalize_name(x) for x in m_list} - {normalize_name(x) for x in excluded}

        # 🔑 열쇠
        today_key = pick_next_from_cycle(key_order, prev_key, allowed_m) if key_order else ""
        st.session_state.today_key = today_key

        # 🔧 1종 수동(오전)
        sud_m, last_m = [], prev_sudong
        for _ in range(sudong_count):
            pick = pick_next_from_cycle(sudong_order, last_m, allowed_m - {normalize_name(x) for x in sud_m})
            if pick:
                sud_m.append(pick)
                last_m = pick
        st.session_state["sudong_base_for_pm"] = sud_m[-1] if sud_m else prev_sudong

        # ⚠️ 인원 경고
        if sudong_count == 2 and len(sud_m) < 2:
            lines.append("※ 수동 가능 인원이 1명입니다.")
        if sudong_count >= 1 and len(sud_m) == 0:
            lines.append("※ 수동 가능 인원이 0명입니다.")

        # 🚗 2종 자동(오전)
        sud_norms_m = {normalize_name(x) for x in sud_m}
        auto_m = [x for x in m_list if normalize_name(x) in (allowed_m - sud_norms_m)]

        # 🚗 오전 실제 배정 차량 기록
        st.session_state.morning_cars_1 = [get_vehicle(x, veh1) for x in sud_m if get_vehicle(x, veh1)]
        st.session_state.morning_cars_2 = [get_vehicle(x, veh2) for x in auto_m if get_vehicle(x, veh2)]
        st.session_state.morning_auto_names = auto_m + sud_m

        # ✅ 코스점검 (A-합/B-불)
        course_info = st.session_state.get("course_info", [])
        a_list = [x["name"] for x in course_info if x["course"] == "A-합"]
        b_list = [x["name"] for x in course_info if x["course"] == "B-불"]

        # === 출력(오전) ===
        if today_key: lines.append(f"열쇠: {today_key}")
        if sud_m:
            for nm in sud_m:
                lines.append(f"1종수동: {nm} {mark_car(get_vehicle(nm, veh1))}")
        else:
            lines.append("1종수동: (배정자 없음)")
        if auto_m:
            lines.append("2종 자동:")
            for nm in auto_m:
                lines.append(f" • {nm} {mark_car(get_vehicle(nm, veh2))}")
        else:
            lines.append("2종 자동: (배정자 없음)")

        if a_list or b_list:
            lines.append("코스점검:")
            if a_list:
                lines.append(" A-합 → " + ", ".join(a_list))
            if b_list:
                lines.append(" B-불 → " + ", ".join(b_list))

        result_text = "\n".join(lines)
        st.markdown("### 📋 오전 결과")
        st.code(result_text, language="text")
        clipboard_copy_button(result_text)

    except Exception as e:
        st.error(f"오전 오류: {e}")

# =====================================
# 3) 오후 근무 배정
# =====================================
st.markdown("<h4 style='font-size:18px;'>3️⃣ 오후 근무 배정</h4>", unsafe_allow_html=True)
afternoon = st.text_area("오후 근무자 (필요 시 입력)", "", height=150)
a_list = [x.strip() for x in afternoon.splitlines() if x.strip()]

save_check = st.checkbox("이 결과를 '전일 기준'으로 저장 (전일근무.json 갱신)", value=True)

if st.button("📋 오후 배정 생성"):
    try:
        lines = []
        allowed_a = {normalize_name(x) for x in a_list} - {normalize_name(x) for x in excluded}

        today_key = st.session_state.get("today_key", prev_key)
        sudong_prev = st.session_state.get("sudong_base_for_pm", prev_sudong)

        # 🔧 1종 수동(오후)
        sud_a_list, last_a = [], sudong_prev
        for _ in range(sudong_count):
            pick = pick_next_from_cycle(sudong_order, last_a, allowed_a)
            if pick:
                sud_a_list.append(pick)
                last_a = pick

        # 🚗 2종 자동(오후)
        sud_a_norms = {normalize_name(x) for x in sud_a_list}
        auto_a = [x for x in a_list if normalize_name(x) in (allowed_a - sud_a_norms)]

        # === 오전 대비 비교 ===
        morning_auto_names = set(st.session_state.get("morning_auto_names", []))
        afternoon_auto_names = set(auto_a)
        afternoon_sudong_norms = {normalize_name(x) for x in sud_a_list}

        morning_only = []
        for nm in morning_auto_names:
            n_norm = normalize_name(nm)
            if n_norm not in {normalize_name(x) for x in afternoon_auto_names} and n_norm not in afternoon_sudong_norms:
                morning_only.append(nm)

        added = sorted(list(afternoon_auto_names - morning_auto_names))
        missing = sorted(morning_only)

        # === 미배정 차량 ===
        morning_cars_1 = set(st.session_state.get("morning_cars_1", []))
        morning_cars_2 = set(st.session_state.get("morning_cars_2", []))
        afternoon_cars_1 = {get_vehicle(x, veh1) for x in sud_a_list if get_vehicle(x, veh1)}
        afternoon_cars_2 = {get_vehicle(x, veh2) for x in auto_a if get_vehicle(x, veh2)}

        unassigned_1 = sorted([c for c in morning_cars_1 if c not in afternoon_cars_1])
        unassigned_2 = sorted([c for c in morning_cars_2 if c not in afternoon_cars_2])

        # === 출력 ===
        if today_key: lines.append(f"열쇠: {today_key}")
        if sud_a_list:
            for nm in sud_a_list:
                lines.append(f"1종수동: {nm} {mark_car(get_vehicle(nm, veh1))}")
        else:
            lines.append("1종수동: (배정자 없음)")

        if auto_a:
            lines.append("2종 자동:")
            for nm in auto_a:
                lines.append(f" • {nm} {mark_car(get_vehicle(nm, veh2))}")
        else:
            lines.append("2종 자동: (배정자 없음)")

        # === 오전 대비 비교 ===
        lines.append("오전 대비 비교:")
        if added:
            lines.append(" • 추가 인원: " + ", ".join(added))
        if missing:
            lines.append(" • 빠진 인원: " + ", ".join(missing))

        # === 미배정 차량 ===
        if unassigned_1 or unassigned_2:
            lines.append("미배정 차량:")
            if unassigned_1:
                lines.append(" [1종 수동]")
                for c in unassigned_1:
                    lines.append(f"  • {c} 마감")
            if unassigned_2:
                lines.append(" [2종 자동]")
                for c in unassigned_2:
                    lines.append(f"  • {c} 마감")

        result_text = "\n".join(lines)
        st.markdown("### 📋 오후 결과")
        st.code(result_text, language="text")
        clipboard_copy_button(result_text)

        # ✅ 전일 데이터 저장
        if save_check:
            new_prev = {
                "열쇠": today_key,
                "교양_5교시": prev_gyoyang5,
                "1종수동": (sud_a_list[-1] if sud_a_list else prev_sudong)
            }
            save_json(PREV_FILE, new_prev)
            st.success("✅ 전일근무.json 업데이트 완료")

    except Exception as e:
        st.error(f"오후 오류: {e}")
