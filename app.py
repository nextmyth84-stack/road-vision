# app.py — 도로주행 근무자동배정 v7.14.4 (완전본)
# 기능 요약:
# ✅ 교양 순번 오전/오후 순환 (전일 5교시 기준)
# ✅ 코스점검 (A합/B불 등) 자동 인식
# ✅ 복사 버튼 (클립보드 복사, 코드 표시 안됨)
# ✅ 기본 순번 자동 생성 / JSON 연동
# ✅ txt 저장 제거

import streamlit as st
from openai import OpenAI
import streamlit.components.v1 as components
import base64, re, json, os

# =====================================
# 페이지 설정
# =====================================
st.set_page_config(page_title="도로주행 근무자동배정", layout="wide")
st.markdown("<h3 style='text-align:center; font-size:22px;'>🚗 도로주행 근무자동배정 v7.14.4</h3>", unsafe_allow_html=True)

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
# 기본 순번 자동 생성
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
with st.sidebar.expander("📚 교양 순번 보기/수정", expanded=False):
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
# 복사 버튼 함수 (JS)
# =====================================
def clipboard_copy_button(text: str, label="📋 결과 복사"):
    b64 = base64.b64encode(text.encode("utf-8")).decode()
    html = f"""
    <button onclick="(async () => {{
        try {{
            const b = '{b64}';
            const bin = atob(b);
            const bytes = new Uint8Array([...bin].map(c => c.charCodeAt(0)));
            const dec = new TextDecoder('utf-8').decode(bytes);
            await navigator.clipboard.writeText(dec);
            alert('✅ 결과가 클립보드에 복사되었습니다.');
        }} catch (e) {{
            alert('복사 실패: ' + e);
        }}
    }})()" style="
        background-color:#4CAF50;color:white;border:none;padding:8px 14px;
        border-radius:6px;cursor:pointer;">{label}</button>
    """
    components.html(html, height=60)

# =====================================
# GPT OCR (오전: 이름 + 코스점검 분리 저장)
# =====================================
def gpt_extract(img_bytes):
    b64 = base64.b64encode(img_bytes).decode()
    user = (
        "이 이미지는 운전면허시험 근무표입니다.\n"
        "1) '학과', '기능장', '초소'를 제외한 도로주행 근무자 이름만 추출하세요.\n"
        "2) 괄호안 정보(A-합/B-불 등)는 유지하되, 괄호에 '지원','인턴','연수'가 포함된 사람은 제외하세요.\n"
        '반환 예시: {"names": ["김면정(A-합)","김성연(B-불)"]}'
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
        # 유연한 코스 패턴: (A-합), A합, ( B - 불 ), A - 합, 등 다양한 표기 허용
        course_pat = re.compile(r"(?:[\(\[\{（【]?\s*)(A|B)\s*[-–]?\s*(합|불)(?:\s*[\)\]\}）】]?)")

        for n in full_names:
            m = course_pat.search(n)
            if m:
                # "A합"/"B불"로 정규화 저장
                course = f"{m.group(1)}{m.group(2)}"
                course_info.append({
                    "name": re.sub(r"\(.*?\)", "", n).strip(),  # 이름만
                    "course": course
                })
            # 항상 괄호 제거한 '순수 이름' 저장 (순번 매칭용)
            pure_names.append(re.sub(r"\(.*?\)", "", n).strip())
        return pure_names, course_info

    except Exception as e:
        st.error(f"OCR 실패: {e}")
        return [], []

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
# 2) 오전 근무 배정 (교양 1·2교시 포함)
# =====================================
st.markdown("<h4 style='font-size:18px;'>2️⃣ 오전 근무 배정</h4>", unsafe_allow_html=True)
morning = st.text_area("오전 근무자 (필요 시 수정)", "\n".join(st.session_state.get("m_names_raw", [])), height=150)
m_list = [x.strip() for x in morning.splitlines() if x.strip()]

if st.button("📋 오전 배정 생성"):
    try:
        lines = []
        allowed_m = {normalize_name(x) for x in m_list} - {normalize_name(x) for x in excluded}

        # 🔑 열쇠 (전일 열쇠의 다음 사람, 근무 가능자 안에서 선발)
        today_key = pick_next_from_cycle(key_order, prev_key, allowed_m) if key_order else ""
        st.session_state.today_key = today_key

        # 🧑‍🏫 교양 1·2교시 (전일 5교시 기준으로 순환)
        gy1 = pick_next_from_cycle(gyoyang_order, prev_gyoyang5, allowed_m) if gyoyang_order else None
        gy1_norm = normalize_name(gy1) if gy1 else None
        gy2 = pick_next_from_cycle(gyoyang_order, gy1 or prev_gyoyang5, allowed_m - ({gy1_norm} if gy1_norm else set())) if gyoyang_order else None
        # 오후 3·4·5교시의 시작 포인터로 저장
        st.session_state.gyoyang_base_for_pm = gy2 or gy1 or prev_gyoyang5

        # 🔧 1종 수동 (설정 인원수 반영)
        sud_m, last_m = [], prev_sudong
        for _ in range(sudong_count):
            pick = pick_next_from_cycle(sudong_order, last_m, allowed_m - {normalize_name(x) for x in sud_m})
            if pick:
                sud_m.append(pick)
                last_m = pick
        st.session_state["sudong_base_for_pm"] = sud_m[-1] if sud_m else prev_sudong

        # ⚠️ 수동 인원 안내
        if sudong_count == 2 and len(sud_m) < 2:
            lines.append("※ 수동 가능 인원이 1명입니다.")
        if sudong_count >= 1 and len(sud_m) == 0:
            lines.append("※ 수동 가능 인원이 0명입니다.")

        # 🚗 2종 자동 (오전; 1종 제외)
        sud_norms_m = {normalize_name(x) for x in sud_m}
        auto_m = [x for x in m_list if normalize_name(x) in (allowed_m - sud_norms_m)]

        # 🚗 오전 실제 배정 차량 기록 (오후 비교/미배정 계산용)
        st.session_state.morning_cars_1 = [get_vehicle(x, veh1) for x in sud_m if get_vehicle(x, veh1)]
        st.session_state.morning_cars_2 = [get_vehicle(x, veh2) for x in auto_m if get_vehicle(x, veh2)]
        st.session_state.morning_auto_names = auto_m + sud_m  # 비교용 (이름 기준)

        # ✅ 코스점검 출력 (A합/B불)
        course_info = st.session_state.get("course_info", [])
        a_list = [x["name"] for x in course_info if x.get("course") in ("A합", "A-합")]
        b_list = [x["name"] for x in course_info if x.get("course") in ("B불", "B-불")]

        # === 출력(오전) ===
        if today_key: lines.append(f"열쇠: {today_key}")
        if gy1: lines.append(f"1교시(교양): {gy1}")
        if gy2: lines.append(f"2교시(교양): {gy2}")

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
                lines.append(" A합 → " + ", ".join(a_list))
            if b_list:
                lines.append(" B불 → " + ", ".join(b_list))

        result_text = "\n".join(lines)
        st.markdown("### 📋 오전 결과")
        st.code(result_text, language="text")
        clipboard_copy_button(result_text)

    except Exception as e:
        st.error(f"오전 오류: {e}")

# =====================================
# 3️⃣ 오후 근무 배정 (교양 3·4·5교시 + 미배정차량 + 전일 저장)
# =====================================
st.markdown("<h4 style='font-size:18px;'>3️⃣ 오후 근무 배정</h4>", unsafe_allow_html=True)
a_file = st.file_uploader("📸 오후 근무표 업로드", type=["png","jpg","jpeg"])

if st.button("🧠 오후 GPT 인식"):
    if not a_file:
        st.warning("오후 이미지를 업로드하세요.")
    else:
        with st.spinner("오후 GPT 분석 중..."):
            a_names, _ = gpt_extract(a_file.read())
            st.session_state.a_names_raw = a_names
            st.success(f"오후 인식 완료: {len(a_names)}명")
        st.rerun()

afternoon = st.text_area("오후 근무자 (필요 시 수정)", "\n".join(st.session_state.get("a_names_raw", [])), height=150)
a_list = [x.strip() for x in afternoon.splitlines() if x.strip()]

save_check = st.checkbox("이 결과를 전일 기준으로 저장 (전일근무.json 덮어쓰기)", value=True)

if st.button("📋 오후 배정 생성"):
    try:
        lines = []
        allowed_a = {normalize_name(x) for x in a_list} - {normalize_name(x) for x in excluded}

        today_key = st.session_state.get("today_key", prev_key)
        if today_key:
            lines.append(f"열쇠: {today_key}")

        # 🧑‍🏫 교양 3·4·5교시 (오전 gy2 이후 순환)
        gy_start = st.session_state.get("gyoyang_base_for_pm", prev_gyoyang5) or (gyoyang_order[0] if gyoyang_order else None)
        used = set()
        gy3 = gy4 = gy5 = None
        if gyoyang_order:
            for period in [3, 4, 5]:
                pick = pick_next_from_cycle(gyoyang_order, gy_start, allowed_a - used)
                if not pick:
                    break
                if period == 3: gy3 = pick
                elif period == 4: gy4 = pick
                else: gy5 = pick
                used.add(normalize_name(pick))
                gy_start = pick
        if gy3: lines.append(f"3교시(교양): {gy3}")
        if gy4: lines.append(f"4교시(교양): {gy4}")
        if gy5: lines.append(f"5교시(교양): {gy5}")

        # 🔧 오후 1종 수동 (1명/2명 반영)
        sud_a, last_a = [], st.session_state.get("sudong_base_for_pm", prev_sudong)
        for _ in range(sudong_count):
            pick = pick_next_from_cycle(sudong_order, last_a, allowed_a)
            if pick:
                sud_a.append(pick)
                last_a = pick
        if sud_a:
            for nm in sud_a:
                lines.append(f"1종수동: {nm} {mark_car(get_vehicle(nm, veh1))}")
            if sudong_count == 2 and len(sud_a) < 2:
                lines.append("※ 수동 가능 인원이 1명입니다.")
        else:
            lines.append("1종수동: (배정자 없음)")

        # 🚗 2종 자동(오후): 1종 제외
        sud_a_norms = {normalize_name(x) for x in sud_a}
        auto_a = [x for x in a_list if normalize_name(x) in (allowed_a - sud_a_norms)]
        if auto_a:
            lines.append("2종 자동:")
            for nm in auto_a:
                lines.append(f" • {nm} {mark_car(get_vehicle(nm, veh2))}")
        else:
            lines.append("2종 자동: (배정자 없음)")

        # === 오전 대비 비교 ===
        lines.append("\n오전 대비 비교:")
        morning_auto = set(st.session_state.get("morning_auto_names", []))
        afternoon_auto = set(auto_a)
        afternoon_sudong = {normalize_name(x) for x in sud_a}

        # 오후 1종으로 전환된 인원은 빠진 인원에서 제외
        morning_only = []
        for nm in morning_auto:
            n_norm = normalize_name(nm)
            if n_norm not in {normalize_name(x) for x in afternoon_auto} and n_norm not in afternoon_sudong:
                morning_only.append(nm)

        added = sorted(list(afternoon_auto - morning_auto))
        missing = sorted(morning_only)

        if added:
            lines.append(" • 추가 인원: " + ", ".join(added))
        if missing:
            lines.append(" • 빠진 인원: " + ", ".join(missing))
        if not added and not missing:
            lines.append(" • 변화 없음")

        # === 미배정 차량 ===
        morning_cars_1 = set(st.session_state.get("morning_cars_1", []))
        morning_cars_2 = set(st.session_state.get("morning_cars_2", []))
        afternoon_cars_1 = {get_vehicle(x, veh1) for x in sud_a if get_vehicle(x, veh1)}
        afternoon_cars_2 = {get_vehicle(x, veh2) for x in auto_a if get_vehicle(x, veh2)}

        unassigned_1 = sorted([c for c in morning_cars_1 if c not in afternoon_cars_1])
        unassigned_2 = sorted([c for c in morning_cars_2 if c not in afternoon_cars_2])

        if unassigned_1 or unassigned_2:
            lines.append("\n미배정 차량:")
            if unassigned_1:
                lines.append(" [1종 수동]")
                for c in unassigned_1:
                    lines.append(f"  • {c} 마감")
            if unassigned_2:
                lines.append(" [2종 자동]")
                for c in unassigned_2:
                    lines.append(f"  • {c} 마감")

        # === 결과 표시 ===
        result_text = "\n".join(lines)
        st.markdown("### 📋 오후 결과")
        st.code(result_text, language="text")
        clipboard_copy_button(result_text)

        # ✅ 전일 저장
        if save_check:
            new_prev = {
                "열쇠": today_key,
                "교양_5교시": gy5 or gy4 or gy3 or prev_gyoyang5,
                "1종수동": (sud_a[-1] if sud_a else prev_sudong)
            }
            save_json(PREV_FILE, new_prev)
            st.success("✅ 전일근무.json 업데이트 완료")

    except Exception as e:
        st.error(f"오후 오류: {e}")
