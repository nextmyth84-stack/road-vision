# app.py — 도로주행 근무자동배정 v7.16 (완전본)
import streamlit as st
from openai import OpenAI
import base64, re, json, os, difflib
from difflib import SequenceMatcher, get_close_matches

# =====================================
# 페이지 설정
# =====================================
st.set_page_config(page_title="도로주행 근무자동배정", layout="wide")
st.markdown("<h3 style='text-align:center; font-size:22px;'>🚗 도로주행 근무자동배정</h3>", unsafe_allow_html=True)

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
# 경로 설정
# =====================================
PREV_FILE = "전일근무.json"
EMP_FILE = "근무자명단.json"
COURSE_FILE = "코스점검결과.json"

# =====================================
# JSON 유틸
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

# =====================================
# 이름 정규화 및 교정
# =====================================
def normalize_name(s): 
    return re.sub(r"[^가-힣]", "", re.sub(r"\(.*?\)", "", s or ""))

def _sim(a, b): 
    return SequenceMatcher(None, a, b).ratio()

def _apply_ocr_fixups(s):
    fixes = {"군":"균","용":"영","니":"미","졍":"정","섲":"석"}
    for k, v in fixes.items():
        s = s.replace(k, v)
    return s

def correct_name(name, valid_names, cutoff=0.55):
    """OCR 교정 — 근무자명단 기반 근사 교정"""
    if not valid_names:
        return name

    norm_map = {normalize_name(v): v for v in valid_names}
    n0 = normalize_name(name)
    if n0 in norm_map:
        return norm_map[n0]

    # 1차 근사 매칭
    m = get_close_matches(n0, list(norm_map.keys()), n=1, cutoff=cutoff)
    if m:
        return norm_map[m[0]]

    # 2차: 경미한 OCR 보정 후 재시도
    n1 = normalize_name(_apply_ocr_fixups(name))
    if n1 in norm_map:
        return norm_map[n1]
    m2 = get_close_matches(n1, list(norm_map.keys()), n=1, cutoff=cutoff - 0.02)
    if m2:
        return norm_map[m2[0]]

    # 3차: 직접 유사도 비교
    best, score = name, 0.0
    for c in norm_map:
        sc = _sim(n1, c)
        if sc > score:
            best, score = c, sc
    if score >= cutoff - 0.05:
        return norm_map[best]

    return name

# =====================================
# 복사 버튼 (JS 안전 렌더링)
# =====================================
def clipboard_copy_button(label, text):
    """코드로 보이지 않게 안전한 클립보드 복사 버튼"""
    safe_text = text.replace("\\", "\\\\").replace("`", "\\`").replace("\n", "\\n")
    js = f"""
    <button onclick="navigator.clipboard.writeText(`{safe_text}`); alert('복사되었습니다 ✅');"
        style="background-color:#4CAF50;color:white;border:none;border-radius:6px;
        padding:6px 14px;cursor:pointer;font-size:14px;">
        {label}
    </button>
    """
    st.markdown(js, unsafe_allow_html=True)

# =====================================
# 2/3 — 순번·차량표 파일/사이드바 + OCR + 오전 배정
# =====================================

# ▼ 순번/차량표 파일경로
KEY_FILE   = "열쇠순번.json"
GY_FILE    = "교양순번.json"
SUD_FILE   = "1종수동순번.json"
VEH1_FILE  = "1종수동차량.json"
VEH2_FILE  = "2종자동차량.json"

# ▼ 기본값
default_key = ["권한솔","김남균","김면정","김성연","김지은","안유미","윤여헌","윤원실","이나래","이호석","조윤영","조정래"]
default_gy  = ["권한솔","김남균","김면정","김병욱","김성연","김주현","김지은","안유미","이호석","조정래"]
default_sd  = ["권한솔","김남균","김성연","김주현","이호석","조정래"]
default_veh1 = ["2호 조정래","5호 권한솔","7호 김남균","8호 이호석","9호 김주현","10호 김성연"]
default_veh2 = ["4호 김남균","5호 김병욱","6호 김지은","12호 안유미","14호 김면정","15호 이호석",
                "17호 김성연","18호 권한솔","19호 김주현","22호 조정래"]

# ▼ 파일 없으면 생성
if not os.path.exists(KEY_FILE):  save_json(KEY_FILE, default_key)
if not os.path.exists(GY_FILE):   save_json(GY_FILE,  default_gy)
if not os.path.exists(SUD_FILE):  save_json(SUD_FILE, default_sd)
if not os.path.exists(VEH1_FILE): save_json(VEH1_FILE, default_veh1)
if not os.path.exists(VEH2_FILE): save_json(VEH2_FILE, default_veh2)
if not os.path.exists(PREV_FILE): save_json(PREV_FILE, {"열쇠":"", "교양_5교시":"", "1종수동":""})
if not os.path.exists(COURSE_FILE): save_json(COURSE_FILE, [])

# ▼ 현재 값 로드
key_order     = load_json(KEY_FILE, default_key)
gyoyang_order = load_json(GY_FILE,  default_gy)
sudong_order  = load_json(SUD_FILE, default_sd)
veh1_lines    = load_json(VEH1_FILE, default_veh1)
veh2_lines    = load_json(VEH2_FILE, default_veh2)
employees     = load_json(EMP_FILE, employees if 'employees' in globals() else [])
_prev         = load_json(PREV_FILE, {"열쇠":"", "교양_5교시":"", "1종수동":""})
prev_key, prev_gyoyang5, prev_sudong = _prev.get("열쇠",""), _prev.get("교양_5교시",""), _prev.get("1종수동","")

st.info(f"전일 불러옴 → 열쇠:{prev_key or '-'}, 교양5:{prev_gyoyang5 or '-'}, 1종:{prev_sudong or '-'}")

# ---------- 사이드바(숨김 편집) ----------
st.sidebar.header("📋 순번표 / 차량표 / 전일값 / 근무자명단")

def _list(s): return [x.strip() for x in s.splitlines() if x.strip()]

with st.sidebar.expander("🔑 열쇠 순번", expanded=False):
    key_text = st.text_area("열쇠 순번", "\n".join(key_order), height=180, key="key_text")
    if st.button("💾 열쇠순번 저장"):
        save_json(KEY_FILE, _list(key_text)); st.sidebar.success("저장 완료"); st.rerun()

with st.sidebar.expander("📘 교양 순번", expanded=False):
    gy_text = st.text_area("교양 순번", "\n".join(gyoyang_order), height=180, key="gy_text")
    if st.button("💾 교양순번 저장"):
        save_json(GY_FILE, _list(gy_text)); st.sidebar.success("저장 완료"); st.rerun()

with st.sidebar.expander("🔧 1종 수동 순번", expanded=False):
    sd_text = st.text_area("1종 수동 순번", "\n".join(sudong_order), height=150, key="sd_text")
    st.session_state["sudong_count"] = st.radio("1종 수동 인원수", [1, 2], index=0, horizontal=True, key="sudong_count_radio")
    if st.button("💾 1종 순번 저장"):
        save_json(SUD_FILE, _list(sd_text)); st.sidebar.success("저장 완료"); st.rerun()

with st.sidebar.expander("🚗 차량표 (1종 수동)", expanded=False):
    v1_text = st.text_area("1종 수동 차량표", "\n".join(veh1_lines), height=150, key="v1_text")
    if st.button("💾 1종 차량표 저장"):
        save_json(VEH1_FILE, _list(v1_text)); st.sidebar.success("저장 완료"); st.rerun()

with st.sidebar.expander("🚘 차량표 (2종 자동)", expanded=False):
    v2_text = st.text_area("2종 자동 차량표", "\n".join(veh2_lines), height=180, key="v2_text")
    if st.button("💾 2종 차량표 저장"):
        save_json(VEH2_FILE, _list(v2_text)); st.sidebar.success("저장 완료"); st.rerun()

with st.sidebar.expander("🗓 전일 값 확인/수정", expanded=False):
    p_key  = st.text_input("전일 열쇠", value=prev_key)
    p_gy5  = st.text_input("전일 교양5", value=prev_gyoyang5)
    p_sd   = st.text_input("전일 1종수동", value=prev_sudong)
    if st.button("💾 전일값 저장"):
        save_json(PREV_FILE, {"열쇠": p_key, "교양_5교시": p_gy5, "1종수동": p_sd})
        st.sidebar.success("저장 완료")

with st.sidebar.expander("👥 전체 근무자명단 (OCR 교정용)", expanded=False):
    emp_text = st.text_area("근무자명단 (한 줄당 한 명)", "\n".join(employees), height=200, key="emp_text")
    if st.button("💾 근무자명단 저장"):
        new_emps = _list(emp_text)
        save_json(EMP_FILE, new_emps); st.sidebar.success("저장 완료"); st.rerun()

# ---------- 차량표 파싱 ----------
def parse_vehicle_map_from_lines(lines):
    text = "\n".join(lines)
    m = {}
    for line in text.splitlines():
        p = line.strip().split()
        if len(p) >= 2:
            car = p[0]
            name = " ".join(p[1:])
            m[name] = car
    return m

veh1 = parse_vehicle_map_from_lines(veh1_lines)
veh2 = parse_vehicle_map_from_lines(veh2_lines)

def get_vehicle(name, veh_map):
    nkey = normalize_name(name)
    for k, v in veh_map.items():
        if normalize_name(k) == nkey:
            return v
    return ""

def pick_next_from_cycle(cycle, last, allowed_norms: set):
    if not cycle: return None
    cyl_norm = [normalize_name(x) for x in cycle]
    last_norm = normalize_name(last)
    start = (cyl_norm.index(last_norm) + 1) % len(cycle) if last_norm in cyl_norm else 0
    for i in range(len(cycle) * 2):
        cand = cycle[(start + i) % len(cycle)]
        if normalize_name(cand) in allowed_norms:
            return cand
    return None

# ---------- GPT OCR (교정 + 근무제외 + 코스점검 A/B 합불) ----------
def gpt_extract(img_bytes, detect_excluded=True):
    b64 = base64.b64encode(img_bytes).decode()
    user = (
        "이 이미지는 운전면허시험 근무표입니다.\n"
        "1) 도로주행 근무자 이름을 JSON으로 추출하세요.\n"
        "2) 이름 옆 괄호(A-합/B-불 등)는 그대로 포함해 반환하세요.\n"
        "3) '지원','인턴','연수' 포함자는 제외하세요.\n"
    )
    if detect_excluded:
        user += "4) 상단의 '휴가','출장','교육','공가','연가','연차','돌봄' 줄의 이름을 'excluded' 배열로 반환하세요.\n"
    user += '반환 예시: {"names": ["김지은(A-합)","조윤영(B 불)","이호석"], "excluded": ["안유미"]}'

    try:
        res = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "표에서 근무자/코스/제외자를 JSON으로 추출"},
                {"role": "user", "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]}
            ],
        )
        raw = (res.choices[0].message.content or "").strip()
        js = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))

        full = [n.strip() for n in js.get("names", []) if not re.search(r"(지원|인턴|연수)", n)]
        names, course_info = [], []

        for n in full:
            # 괄호에서 A/B + 합/불 판정 (특수문자·공백 제거 후 A/B만 기준)
            m = re.search(r"\(([A-Za-z가-힣\- ]+)\)", n)
            pure = re.sub(r"\(.*?\)", "", n).strip()   # 순번용 이름
            corrected = correct_name(pure, employees)  # 정식 표기로 교정

            if m:
                text = m.group(1).replace("-", "").replace(" ", "").upper()
                course_type  = "A" if "A" in text else "B" if "B" in text else None
                result_type  = "합격" if "합" in text else "불합격" if "불" in text else None
                if course_type and result_type:
                    course_info.append({"name": corrected, "course": f"{course_type}코스 {result_type}"})

            names.append(corrected)

        excluded = js.get("excluded", []) if detect_excluded else []
        excluded = [correct_name(x, employees) for x in excluded]

        save_json(COURSE_FILE, course_info)  # 오전 출력용 저장
        return names, course_info, excluded

    except Exception as e:
        st.error(f"OCR 실패: {e}")
        return [], [], []

# ---------- 오전 이미지/OCR ----------
st.markdown("<h4>1️⃣ 오전 근무표 업로드</h4>", unsafe_allow_html=True)
m_file = st.file_uploader("📸 오전 근무표", type=["png","jpg","jpeg"], key="m_file")

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

# ---------- 근무제외자/오전명단 확인 ----------
st.markdown("### 🚫 근무제외자 (자동추출 후 수정 가능)")
excluded_text = st.text_area("자동 인식된 근무제외자", "\n".join(st.session_state.get("excluded_auto", [])), height=90)
excluded = {x.strip() for x in excluded_text.splitlines() if x.strip()}

morning_text = st.text_area("오전 근무자 (필요 시 수정)", "\n".join(st.session_state.get("m_names_raw", [])), height=150)
m_list = [x.strip() for x in morning_text.splitlines() if x.strip()]
m_allowed = {normalize_name(x) for x in m_list} - {normalize_name(x) for x in excluded}

# ---------- 오전 배정 ----------
def morning_assign():
    lines = []
    sudong_count = st.session_state.get("sudong_count_radio", 1)

    # 🔑 열쇠
    today_key = pick_next_from_cycle(key_order, prev_key, m_allowed) if key_order else ""
    st.session_state.today_key = today_key

    # 🧑‍🏫 교양 1·2
    gy1 = pick_next_from_cycle(gyoyang_order, prev_gyoyang5, m_allowed) if gyoyang_order else None
    gy1_norm = normalize_name(gy1) if gy1 else None
    gy2 = pick_next_from_cycle(gyoyang_order, gy1 or prev_gyoyang5, m_allowed - ({gy1_norm} if gy1_norm else set())) if gyoyang_order else None
    st.session_state.gyoyang_base_for_pm = gy2 or gy1 or prev_gyoyang5

    # 🔧 1종 수동
    sud_m, last = [], prev_sudong
    for _ in range(sudong_count):
        pick = pick_next_from_cycle(sudong_order, last, m_allowed - {normalize_name(x) for x in sud_m})
        if not pick: break
        sud_m.append(pick); last = pick
    st.session_state.sudong_base_for_pm = sud_m[-1] if sud_m else prev_sudong

    # 🚗 2종 자동
    sud_norms_m = {normalize_name(x) for x in sud_m}
    auto_m = [x for x in m_list if normalize_name(x) in (m_allowed - sud_norms_m)]

    # 오후 대비/미배정 차량 계산용 저장
    st.session_state.morning_auto_names = auto_m + sud_m   # 오전 운전 전체(1+2)
    st.session_state.morning_cars_1 = [get_vehicle(x, veh1) for x in sud_m if get_vehicle(x, veh1)]
    st.session_state.morning_cars_2 = [get_vehicle(x, veh2) for x in auto_m if get_vehicle(x, veh2)]

    # === 출력(오전)
    if today_key: lines.append(f"열쇠: {today_key}")
    if gy1: lines.append(f"1교시(교양): {gy1}")
    if gy2: lines.append(f"2교시(교양): {gy2}")

    if sud_m:
        for nm in sud_m:
            lines.append(f"1종수동: {nm} {get_vehicle(nm, veh1) or ''}")
        if sudong_count == 2 and len(sud_m) < 2:
            lines.append("※ 수동 가능 인원이 1명입니다.")
    else:
        lines.append("1종수동: (배정자 없음)")

    if auto_m:
        lines.append("2종 자동:")
        for nm in auto_m:
            lines.append(f" • {nm} {get_vehicle(nm, veh2) or ''}")
    else:
        lines.append("2종 자동: (배정자 없음)")

    # ✅ 코스점검 (오전만 출력)
    course_info = load_json(COURSE_FILE, [])
    if course_info:
        lines.append("")
        lines.append("코스점검 결과:")
        a_pass = [x["name"] for x in course_info if "A코스 합격" in x.get("course","")]
        a_fail = [x["name"] for x in course_info if "A코스 불합격" in x.get("course","")]
        b_pass = [x["name"] for x in course_info if "B코스 합격" in x.get("course","")]
        b_fail = [x["name"] for x in course_info if "B코스 불합격" in x.get("course","")]
        if a_pass: lines.append(" • A코스 합격: " + ", ".join(a_pass))
        if a_fail: lines.append(" • A코스 불합격: " + ", ".join(a_fail))
        if b_pass: lines.append(" • B코스 합격: " + ", ".join(b_pass))
        if b_fail: lines.append(" • B코스 불합격: " + ", ".join(b_fail))

    result_text = "\n".join(lines)
    st.markdown("### 📋 오전 결과")
    st.code(result_text, language="text")
    clipboard_copy_button("📋 결과 복사하기", result_text)

# 버튼
if st.button("📋 오전 배정 생성"):
    try:
        morning_assign()
    except Exception as e:
        st.error(f"오전 오류: {e}")

# =====================================
# 3/3 — 오후 OCR/배정 + 신규투입/빠진인원 + 미배정차량 + 전일저장
# =====================================

st.markdown("<h4>2️⃣ 오후 근무표 업로드</h4>", unsafe_allow_html=True)
a_file = st.file_uploader("📸 오후 근무표", type=["png","jpg","jpeg"], key="a_file")

if st.button("🧠 오후 GPT 인식"):
    if not a_file:
        st.warning("오후 이미지를 업로드하세요.")
    else:
        with st.spinner("오후 근무표 분석 중..."):
            a_names, _course, _ = gpt_extract(a_file.read(), detect_excluded=False)
            st.session_state.a_names_raw = a_names
            st.success(f"오후 인식 완료: 근무자 {len(a_names)}명")
        st.rerun()

afternoon_text = st.text_area("오후 근무자 (필요 시 수정)", "\n".join(st.session_state.get("a_names_raw", [])), height=150)
a_list = [x.strip() for x in afternoon_text.splitlines() if x.strip()]

# 제외자 세이프가드 (오전 OCR 생략 시 대비)
excluded_norms = {normalize_name(x) for x in st.session_state.get("excluded_auto", [])}

save_check = st.checkbox("이 결과를 전일근무.json으로 저장", value=True)

def afternoon_assign():
    lines = []
    sudong_count = st.session_state.get("sudong_count_radio", 1)

    today_key = st.session_state.get("today_key", prev_key)
    gy_start  = st.session_state.get("gyoyang_base_for_pm", prev_gyoyang5)
    sud_base  = st.session_state.get("sudong_base_for_pm", prev_sudong)

    a_norms = {normalize_name(x) for x in a_list} - excluded_norms

    # 🧑‍🏫 교양 3·4·5
    used = set()
    gy3 = pick_next_from_cycle(gyoyang_order, gy_start, a_norms)
    if gy3: used.add(normalize_name(gy3))
    gy4 = pick_next_from_cycle(gyoyang_order, gy3 or gy_start, a_norms - used)
    if gy4: used.add(normalize_name(gy4))
    gy5 = pick_next_from_cycle(gyoyang_order, gy4 or gy3 or gy_start, a_norms - used)

    # 🔧 1종 수동 (교양과 중복 허용)
    sud_a, last = [], sud_base
    for _ in range(sudong_count):
        pick = pick_next_from_cycle(sudong_order, last, a_norms)
        if not pick: break
        sud_a.append(pick); last = pick

    # 🚗 2종 자동 (1종 제외)
    sud_norms_a = {normalize_name(x) for x in sud_a}
    auto_a = [x for x in a_list if normalize_name(x) in (a_norms - sud_norms_a)]

    # === 출력
    if today_key: lines.append(f"열쇠: {today_key}")
    if gy3: lines.append(f"3교시(교양): {gy3}")
    if gy4: lines.append(f"4교시(교양): {gy4}")
    if gy5: lines.append(f"5교시(교양): {gy5}")

    if sud_a:
        for nm in sud_a:
            lines.append(f"1종수동: {nm} {get_vehicle(nm, veh1) or ''}")
        if sudong_count == 2 and len(sud_a) < 2:
            lines.append("※ 수동 가능 인원이 1명입니다.")
    else:
        lines.append("1종수동: (배정자 없음)")

    if auto_a:
        lines.append("2종 자동:")
        for nm in auto_a:
            lines.append(f" • {nm} {get_vehicle(nm, veh2) or ''}")
    else:
        lines.append("2종 자동: (배정자 없음)")

    # === 오전 대비 비교 (오전 비근무 → 오후 근무 신규 투입 / 오전 근무 → 오후 비근무 빠짐)
    lines.append("")
    lines.append("오전 대비 비교:")

    morning_drivers   = st.session_state.get("morning_auto_names", [])  # 오전 운전 전체(1+2)
    morning_norms     = {normalize_name(x) for x in morning_drivers}
    afternoon_drivers = auto_a + sud_a
    afternoon_norms   = {normalize_name(x) for x in afternoon_drivers}

    new_joiners = sorted([nm for nm in afternoon_drivers if normalize_name(nm) not in morning_norms])
    missing     = sorted([nm for nm in morning_drivers  if normalize_name(nm) not in afternoon_norms])

    if new_joiners: lines.append(" • 신규 투입 인원: " + ", ".join(new_joiners))
    if missing:     lines.append(" • 빠진 인원: " + ", ".join(missing))
    if not new_joiners and not missing:
        lines.append(" • 변동 없음")

    # === 미배정 차량 (오전에 있었는데 오후에 없는 것만)
    m_cars_1 = set(st.session_state.get("morning_cars_1", []))
    m_cars_2 = set(st.session_state.get("morning_cars_2", []))
    a_cars_1 = {get_vehicle(x, veh1) for x in sud_a if get_vehicle(x, veh1)}
    a_cars_2 = {get_vehicle(x, veh2) for x in auto_a if get_vehicle(x, veh2)}

    unassigned_1 = sorted([c for c in m_cars_1 if c not in a_cars_1])
    unassigned_2 = sorted([c for c in m_cars_2 if c not in a_cars_2])

    if unassigned_1 or unassigned_2:
        lines.append("")
        lines.append("미배정 차량:")
        if unassigned_1:
            lines.append(" [1종 수동]")
            for c in unassigned_1: lines.append(f"  • {c} 마감")
        if unassigned_2:
            lines.append(" [2종 자동]")
            for c in unassigned_2: lines.append(f"  • {c} 마감")

    # 출력 + 복사
    result_text = "\n".join(lines)
    st.markdown("### 📋 오후 결과")
    st.code(result_text, language="text")
    clipboard_copy_button("📋 결과 복사하기", result_text)

    # 전일 저장
    if save_check:
        data = {
            "열쇠": today_key,
            "교양_5교시": gy5 or gy4 or gy3 or prev_gyoyang5,
            "1종수동": (sud_a[-1] if sud_a else prev_sudong)
        }
        save_json(PREV_FILE, data)
        st.success("전일근무.json 업데이트 완료 ✅")

# 버튼
if st.button("📋 오후 배정 생성"):
    try:
        afternoon_assign()
    except Exception as e:
        st.error(f"오후 오류: {e}")
