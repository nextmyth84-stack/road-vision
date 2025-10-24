# app.py — 도로주행 근무자동배정 v7.15 (완전본)
import streamlit as st
from openai import OpenAI
import base64, re, json, os
from difflib import get_close_matches

st.set_page_config(page_title="도로주행 근무자동배정", layout="wide")
st.markdown("<h3 style='text-align:center;'>🚗 도로주행 근무자동배정 v7.15</h3>", unsafe_allow_html=True)

# =====================================
# 파일 경로
# =====================================
PREV_FILE = "전일근무.json"
KEY_FILE = "열쇠순번.json"
GY_FILE = "교양순번.json"
SUD_FILE = "1종순번.json"
VEH1_FILE = "1종차량표.json"
VEH2_FILE = "2종차량표.json"
COURSE_FILE = "코스점검.json"
NAME_FILE = "근무자명단.json"

# =====================================
# 유틸 함수
# =====================================
def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return default
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def normalize_name(s):
    return re.sub(r"[^가-힣]", "", re.sub(r"\(.*?\)", "", s or ""))

def parse_vehicle_map(text):
    m = {}
    for line in text.splitlines():
        p = line.strip().split()
        if len(p) >= 2:
            car, name = p[0], " ".join(p[1:])
            m[name] = car
    return m

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
# 기본 데이터 (최초 실행 시 저장)
# =====================================
default_key = """권한솔
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
조정래"""
default_gy = """권한솔
김남균
김면정
김병욱
김성연
김주현
김지은
안유미
이호석
조정래"""
default_sd = """권한솔
김남균
김성연
김주현
이호석
조정래"""
default_veh1 = """2호 조정래
5호 권한솔
7호 김남균
8호 이호석
9호 김주현
10호 김성연"""
default_veh2 = """4호 김남균
5호 김병욱
6호 김지은
12호 안유미
14호 김면정
15호 이호석
17호 김성연
18호 권한솔
19호 김주현
22호 조정래"""
default_names = default_key.splitlines()

for path, data in [
    (KEY_FILE, default_key.splitlines()),
    (GY_FILE, default_gy.splitlines()),
    (SUD_FILE, default_sd.splitlines()),
    (NAME_FILE, default_names),
]:
    if not os.path.exists(path):
        save_json(path, data)

# =====================================
# 사이드바 - 순번/차량표/근무자명단
# =====================================
st.sidebar.header("📋 순번표 / 차량표 / 근무자명단")

with st.sidebar.expander("열쇠 순번", expanded=False):
    key_text = st.text_area("열쇠 순번", "\n".join(load_json(KEY_FILE, [])), height=150)
    if st.button("열쇠 순번 저장"): save_json(KEY_FILE, [x for x in key_text.splitlines() if x.strip()]); st.success("저장 완료")

with st.sidebar.expander("교양 순번", expanded=False):
    gy_text = st.text_area("교양 순번", "\n".join(load_json(GY_FILE, [])), height=150)
    if st.button("교양 순번 저장"): save_json(GY_FILE, [x for x in gy_text.splitlines() if x.strip()]); st.success("저장 완료")

with st.sidebar.expander("1종 수동 순번", expanded=False):
    sd_text = st.text_area("1종 순번", "\n".join(load_json(SUD_FILE, [])), height=150)
    if st.button("1종 순번 저장"): save_json(SUD_FILE, [x for x in sd_text.splitlines() if x.strip()]); st.success("저장 완료")

with st.sidebar.expander("1종 차량표", expanded=False):
    t1 = st.text_area("1종 차량표", default_veh1, height=100)
    if st.button("1종 차량표 저장"): save_json(VEH1_FILE, t1.splitlines()); st.success("저장 완료")

with st.sidebar.expander("2종 차량표", expanded=False):
    t2 = st.text_area("2종 차량표", default_veh2, height=150)
    if st.button("2종 차량표 저장"): save_json(VEH2_FILE, t2.splitlines()); st.success("저장 완료")

with st.sidebar.expander("근무자명단", expanded=False):
    n_text = st.text_area("근무자명단", "\n".join(load_json(NAME_FILE, [])), height=150)
    if st.button("근무자명단 저장"): save_json(NAME_FILE, [x for x in n_text.splitlines() if x.strip()]); st.success("저장 완료")

sudong_count = st.sidebar.radio("1종 수동 인원수", [1, 2], index=0)

# =====================================
# 전일 근무자 확인/수정
# =====================================
_prev = load_json(PREV_FILE, {"열쇠": "", "교양_5교시": "", "1종수동": ""})
prev_key, prev_gyoyang5, prev_sudong = _prev["열쇠"], _prev["교양_5교시"], _prev["1종수동"]

st.sidebar.markdown("---")
st.sidebar.subheader("🗓 전일 근무자 확인/수정")
prev_key = st.sidebar.text_input("전일 열쇠", value=prev_key)
prev_gyoyang5 = st.sidebar.text_input("전일 교양5", value=prev_gyoyang5)
prev_sudong = st.sidebar.text_input("전일 1종수동", value=prev_sudong)
if st.sidebar.button("💾 전일값 저장"):
    save_json(PREV_FILE, {"열쇠": prev_key, "교양_5교시": prev_gyoyang5, "1종수동": prev_sudong})
    st.sidebar.success("저장 완료")

# =====================================
# 2️⃣ 유틸 & 최근 파일 재로딩 (사이드바 저장 반영)
# =====================================
def mark_car(car):
    return f"{car}" if car else ""

def get_vehicle(name, veh_map):
    nkey = normalize_name(name)
    for k, v in veh_map.items():
        if normalize_name(k) == nkey:
            return v
    return ""

def pick_next_from_cycle(cycle, last, allowed_norms: set):
    """전일(last) 다음 순번에서 allowed 안에 있는 첫 후보"""
    if not cycle:
        return None
    cyl_norm = [normalize_name(x) for x in cycle]
    last_norm = normalize_name(last)
    start = (cyl_norm.index(last_norm) + 1) % len(cycle) if last_norm in cyl_norm else 0
    for i in range(len(cycle) * 2):
        cand = cycle[(start + i) % len(cycle)]
        if normalize_name(cand) in allowed_norms:
            return cand
    return None

def clipboard_copy_button(text):
    st.markdown(
        f"""
        <button onclick="navigator.clipboard.writeText(`{text}`)"
        style="padding:8px 16px;border:none;background:#4CAF50;color:white;border-radius:6px;cursor:pointer;">
        📋 결과 복사하기</button>
        """, unsafe_allow_html=True
    )

# 최신 파일 반영 (사이드바에서 수정/저장한 값 즉시 사용)
key_order     = load_json(KEY_FILE, default_key.splitlines())
gyoyang_order = load_json(GY_FILE, default_gy.splitlines())
sudong_order  = load_json(SUD_FILE, default_sd.splitlines())
veh1_lines    = load_json(VEH1_FILE, default_veh1.splitlines())
veh2_lines    = load_json(VEH2_FILE, default_veh2.splitlines())
veh1 = parse_vehicle_map("\n".join(veh1_lines))
veh2 = parse_vehicle_map("\n".join(veh2_lines))

# 전일 값 재로딩 (사이드바에서 수정했을 수 있으므로)
_prev = load_json(PREV_FILE, {"열쇠": "", "교양_5교시": "", "1종수동": ""})
prev_key = _prev.get("열쇠", "")
prev_gyoyang5 = _prev.get("교양_5교시", "")
prev_sudong = _prev.get("1종수동", "")

# =====================================
# 2️⃣-1. GPT OCR (근무자 + 코스점검 + 근무제외자 자동추출)
# =====================================
def gpt_extract(img_bytes, detect_excluded=False):
    """
    - names: 근무자 (괄호 제거된 순수 이름)
    - course_info: [{"name":이름, "course":"A합"/"B불"}]  → 파일 저장(COURSE_FILE)
    - excluded: ["휴가/교육/출장/공가/연가/연차/돌봄" 라인에서 추출된 이름]
    """
    b64 = base64.b64encode(img_bytes).decode()
    user = (
        "이 이미지는 운전면허시험 근무표입니다.\n"
        "1) 도로주행 근무자 이름을 JSON으로 추출하세요.\n"
        "2) 이름 옆 괄호에 (A-합), (B-불) 등이 있으면 그대로 포함하세요.\n"
        "3) '지원','인턴','연수' 포함자는 제외하세요.\n"
    )
    if detect_excluded:
        user += (
            "4) 이미지 상단 등에서 '휴가','교육','출장','공가','연가','연차','돌봄' 단어가 포함된 줄에 있는 이름을 찾아 "
            "'excluded' 배열로 함께 반환하세요.\n"
        )
    user += '반환 예시: {"names": ["김면정(A-합)","김성연(B-불)"], "excluded": ["안유미","김성연"]}'

    try:
        res = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "표에서 이름과 제외자, 코스점검 정보를 JSON으로 추출"},
                {"role": "user", "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]}
            ],
        )
        raw = res.choices[0].message.content
        js = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))

        # 근무자명 처리
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

        # 근무제외자 처리
        excluded = js.get("excluded", []) if detect_excluded else []

        # 코스결과는 파일 저장 (rerun/새로고침에도 유지)
        save_json(COURSE_FILE, course_info)
        return names, course_info, excluded

    except Exception as e:
        st.error(f"OCR 실패: {e}")
        return [], [], []

# =====================================
# 2️⃣-2. 오전 근무 OCR + 근무제외자 자동추출 UI
# =====================================
st.markdown("<h4>1️⃣ 오전 근무표 업로드</h4>", unsafe_allow_html=True)
m_file = st.file_uploader("📸 오전 근무표", type=["png", "jpg", "jpeg"], key="m_upl")

if st.button("🧠 오전 GPT 인식"):
    if not m_file:
        st.warning("오전 이미지를 업로드하세요.")
    else:
        with st.spinner("오전 근무표 분석 중..."):
            m_names, _course, excl = gpt_extract(m_file.read(), detect_excluded=True)
            st.session_state.m_names_raw = m_names
            st.session_state.excluded_auto = excl
            st.success(f"오전 인식 완료: 근무자 {len(m_names)}명, 근무제외 {len(excl)}명 (코스 결과 저장)")
        st.rerun()

# 근무제외자: 자동추출 후 수정 가능
st.markdown("### 🚫 근무제외자 (자동추출 후 수정 가능)")
excluded_text = st.text_area(
    "자동 인식된 근무제외자",
    "\n".join(st.session_state.get("excluded_auto", [])),
    height=100
)
excluded = {x.strip() for x in excluded_text.splitlines() if x.strip()}

# 오전 근무자 확인/수정
morning = st.text_area(
    "오전 근무자 (필요 시 수정)",
    "\n".join(st.session_state.get("m_names_raw", [])),
    height=150
)
m_list = [x.strip() for x in morning.splitlines() if x.strip()]
m_allowed = {normalize_name(x) for x in m_list} - {normalize_name(x) for x in excluded}

# =====================================
# 2️⃣-3. 오전 배정 생성
# =====================================
if st.button("📋 오전 배정 생성"):
    try:
        lines = []

        # 🔑 열쇠 (전일 다음 + 참석자 범위 내)
        today_key = pick_next_from_cycle(key_order, prev_key, m_allowed) if key_order else ""
        st.session_state.today_key = today_key

        # 🧑‍🏫 교양 1·2교시 (전일 5교시 기준)
        gy1 = pick_next_from_cycle(gyoyang_order, prev_gyoyang5, m_allowed) if gyoyang_order else None
        gy1_norm = normalize_name(gy1) if gy1 else None
        gy2 = pick_next_from_cycle(
            gyoyang_order,
            gy1 or prev_gyoyang5,
            m_allowed - ({gy1_norm} if gy1_norm else set())
        ) if gyoyang_order else None
        # 오후 시작 포인터 저장
        st.session_state.gyoyang_base_for_pm = gy2 or gy1 or prev_gyoyang5

        # 🔧 1종 수동
        sud_m, last = [], prev_sudong
        for _ in range(st.session_state.get("sudong_count_override", None) or 0):  # 안전용 (없으면 아래로)
            pass
        # 실제 인원수는 사이드바 라디오 값을 사용
        for _ in range(st.session_state.get("sudong_count", None) or 0):
            pass
        # 위 안전용 무시하고 실제 지정값 사용
        for _ in range(sudong_count):
            pick = pick_next_from_cycle(
                sudong_order,
                last,
                m_allowed - {normalize_name(x) for x in sud_m}
            )
            if not pick:
                break
            sud_m.append(pick)
            last = pick
        st.session_state["sudong_base_for_pm"] = sud_m[-1] if sud_m else prev_sudong

        # 🚗 2종 자동 (오전; 1종 제외)
        sud_norms_m = {normalize_name(x) for x in sud_m}
        auto_m = [x for x in m_list if normalize_name(x) in (m_allowed - sud_norms_m)]

        # 오후 비교용 저장
        st.session_state.morning_auto_names = auto_m + sud_m
        st.session_state.morning_cars_1 = [get_vehicle(x, veh1) for x in sud_m if get_vehicle(x, veh1)]
        st.session_state.morning_cars_2 = [get_vehicle(x, veh2) for x in auto_m if get_vehicle(x, veh2)]

        # === 출력(오전) ===
        if today_key: lines.append(f"열쇠: {today_key}")
        if gy1: lines.append(f"1교시(교양): {gy1}")
        if gy2: lines.append(f"2교시(교양): {gy2}")

        if sud_m:
            for nm in sud_m:
                lines.append(f"1종수동: {nm} {mark_car(get_vehicle(nm, veh1))}")
            if sudong_count == 2 and len(sud_m) < 2:
                lines.append("※ 수동 가능 인원이 1명입니다.")
        else:
            lines.append("1종수동: (배정자 없음)")

        if auto_m:
            lines.append("2종 자동:")
            for nm in auto_m:
                lines.append(f" • {nm} {mark_car(get_vehicle(nm, veh2))}")
        else:
            lines.append("2종 자동: (배정자 없음)")

        # ✅ 코스점검 결과 (파일에서 불러와 오전에만 출력)
        course_info = load_json(COURSE_FILE, [])
        if course_info:
            a_names = [x["name"] for x in course_info if "A" in x.get("course", "")]
            b_names = [x["name"] for x in course_info if "B" in x.get("course", "")]
            lines.append("")
            lines.append("코스점검 결과:")
            if a_names:
                lines.append(" • A코스(합격): " + ", ".join(a_names))
            if b_names:
                lines.append(" • B코스(불합격): " + ", ".join(b_names))

        # 표시 + 복사
        result_text = "\n".join(lines)
        st.markdown("### 📋 오전 결과")
        st.code(result_text, language="text")
        clipboard_copy_button(result_text)

    except Exception as e:
        st.error(f"오전 오류: {e}")

# =====================================
# 3️⃣ 오후 근무 배정 및 비교
# =====================================
st.markdown("<h4>2️⃣ 오후 근무표 업로드</h4>", unsafe_allow_html=True)
a_file = st.file_uploader("📸 오후 근무표", type=["png","jpg","jpeg"], key="a_upl")

if st.button("🧠 오후 GPT 인식"):
    if not a_file:
        st.warning("오후 이미지를 업로드하세요.")
    else:
        with st.spinner("오후 근무표 분석 중..."):
            a_names, _, _ = gpt_extract(a_file.read(), detect_excluded=False)
            st.session_state.a_names_raw = a_names
            st.success(f"오후 인식 완료: 근무자 {len(a_names)}명")
        st.rerun()

# 오후 근무자 확인/수정
afternoon = st.text_area(
    "오후 근무자 (필요 시 수정)",
    "\n".join(st.session_state.get("a_names_raw", [])),
    height=150
)
a_list = [x.strip() for x in afternoon.splitlines() if x.strip()]
a_allowed = {normalize_name(x) for x in a_list} - {normalize_name(x) for x in excluded}

# =====================================
# 3️⃣-1. 오후 배정 생성
# =====================================
if st.button("📋 오후 배정 생성"):
    try:
        lines = []
        today_key = st.session_state.get("today_key", prev_key)
        gy_start = st.session_state.get("gyoyang_base_for_pm", prev_gyoyang5)
        base_sudong = st.session_state.get("sudong_base_for_pm", prev_sudong)

        # 🧑‍🏫 오후 교양 3~5교시
        used = set()
        gy3 = pick_next_from_cycle(gyoyang_order, gy_start, a_allowed)
        if gy3: used.add(normalize_name(gy3))
        gy4 = pick_next_from_cycle(gyoyang_order, gy3 or gy_start, a_allowed - used)
        if gy4: used.add(normalize_name(gy4))
        gy5 = pick_next_from_cycle(gyoyang_order, gy4 or gy3 or gy_start, a_allowed - used)

        # 🔧 1종 수동 (교양 중복 허용)
        sud_a = []
        last = base_sudong
        for _ in range(sudong_count):
            pick = pick_next_from_cycle(sudong_order, last, a_allowed)
            if not pick:
                continue
            sud_a.append(pick)
            last = pick
        sud_norms_a = {normalize_name(x) for x in sud_a}

        # 🚗 2종 자동 (1종 제외)
        auto_a = [x for x in a_list if normalize_name(x) in (a_allowed - sud_norms_a)]

        # === 출력 (오후) ===
        if today_key: lines.append(f"열쇠: {today_key}")
        if gy3: lines.append(f"3교시(교양): {gy3}")
        if gy4: lines.append(f"4교시(교양): {gy4}")
        if gy5: lines.append(f"5교시(교양): {gy5}")

        if sud_a:
            for nm in sud_a:
                lines.append(f"1종수동: {nm} {mark_car(get_vehicle(nm, veh1))}")
        else:
            lines.append("1종수동: (배정자 없음)")

        if auto_a:
            lines.append("2종 자동:")
            for nm in auto_a:
                lines.append(f" • {nm} {mark_car(get_vehicle(nm, veh2))}")
        else:
            lines.append("2종 자동: (배정자 없음)")

        # 오전 대비 비교
        lines.append("")
        lines.append("오전 대비 비교:")

        morning_auto_names = set(st.session_state.get("morning_auto_names", []))
        afternoon_auto_names = set(auto_a)
        afternoon_sudong_norms = {normalize_name(x) for x in sud_a}

        # 오전에 2종이었지만 오후엔 빠진 인원 (단, 1종 전환자는 제외)
        missing = []
        for nm in morning_auto_names:
            n_norm = normalize_name(nm)
            if n_norm not in {normalize_name(x) for x in afternoon_auto_names} and n_norm not in afternoon_sudong_norms:
                missing.append(nm)
        added = sorted(list(afternoon_auto_names - morning_auto_names))
        if added:
            lines.append(" • 추가 인원: " + ", ".join(added))
        if missing:
            lines.append(" • 빠진 인원: " + ", ".join(missing))

        # 미배정 차량 계산
        morning_cars_1 = set(st.session_state.get("morning_cars_1", []))
        morning_cars_2 = set(st.session_state.get("morning_cars_2", []))
        afternoon_cars_1 = {get_vehicle(x, veh1) for x in sud_a if get_vehicle(x, veh1)}
        afternoon_cars_2 = {get_vehicle(x, veh2) for x in auto_a if get_vehicle(x, veh2)}

        unassigned_1 = sorted([c for c in morning_cars_1 if c not in afternoon_cars_1])
        unassigned_2 = sorted([c for c in morning_cars_2 if c not in afternoon_cars_2])

        if unassigned_1 or unassigned_2:
            lines.append("")
            lines.append("미배정 차량:")
            if unassigned_1:
                lines.append(" [1종 수동]")
                for c in unassigned_1:
                    lines.append(f"  • {c} 마감")
            if unassigned_2:
                lines.append(" [2종 자동]")
                for c in unassigned_2:
                    lines.append(f"  • {c} 마감")

        # 표시 + 복사
        result_text = "\n".join(lines)
        st.markdown("### 📋 오후 결과")
        st.code(result_text, language="text")
        clipboard_copy_button(result_text)

        # ✅ 전일 저장 (자동 업데이트)
        data = {
            "열쇠": today_key,
            "교양_5교시": gy5 or gy4 or gy3 or prev_gyoyang5,
            "1종수동": (sud_a[-1] if sud_a else prev_sudong)
        }
        save_json(PREV_FILE, data)
        st.success("전일근무.json 업데이트 완료 ✅")

    except Exception as e:
        st.error(f"오후 오류: {e}")
