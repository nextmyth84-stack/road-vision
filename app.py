# app.py — 도로주행 근무자동배정 v7.17 (자모+초성 교정 강화 완전본)
import streamlit as st
from openai import OpenAI
import base64, re, json, os

# =====================================
# 페이지 설정
# =====================================
st.set_page_config(page_title="도로주행 근무자동배정", layout="wide")
st.markdown("<h3 style='text-align:center; font-size:22px;'>🚗 도로주행 근무자동배정 v7.17</h3>", unsafe_allow_html=True)

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
# 파일 경로
# =====================================
KEY_FILE = "data_key.json"
GY_FILE = "data_gyoyang.json"
SUD_FILE = "data_sudong.json"
VEH1_FILE = "veh1.json"
VEH2_FILE = "veh2.json"
EMP_FILE = "employee_list.json"
PREV_FILE = "전일근무.json"
COURSE_FILE = "course_check.json"

# =====================================
# 파일 IO 함수
# =====================================
def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return default

def save_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# =====================================
# 문자열 유틸
# =====================================
def normalize_name(s):
    return re.sub(r"[^가-힣]", "", re.sub(r"\(.*?\)", "", s or ""))

# =====================================
# 복사 버튼 (JS)
# =====================================
def clipboard_copy_button(label, text):
    btn = st.button(label, key=f"copy_{hash(text)}")
    if btn:
        st.markdown(
            f"""
            <script>
            navigator.clipboard.writeText(`{text}`);
            alert("결과가 복사되었습니다!");
            </script>
            """,
            unsafe_allow_html=True
        )

# =====================================
# OCR 교정 알고리즘 (자모+초성 혼합)
# =====================================
def split_hangul(ch):
    """한글 초성/중성/종성 분리"""
    base = ord(ch) - 0xAC00
    cho = base // 588
    jung = (base % 588) // 28
    jong = base % 28
    return cho, jung, jong

CHO_LIST = [chr(c) for c in range(ord('ㄱ'), ord('ㅎ')+1)]

def hangul_similarity(a, b):
    """자모 단위 유사도 (0~1)"""
    if not a or not b: return 0
    score = 0
    total = max(len(a), len(b))
    for i in range(min(len(a), len(b))):
        ca, cb = a[i], b[i]
        if not ('가' <= ca <= '힣' and '가' <= cb <= '힣'):
            score += (1 if ca == cb else 0)
            continue
        try:
            cho_a, jung_a, jong_a = split_hangul(ca)
            cho_b, jung_b, jong_b = split_hangul(cb)
        except:
            continue
        s = 0
        if cho_a == cho_b: s += 0.4
        if jung_a == jung_b: s += 0.4
        if jong_a == jong_b: s += 0.2
        score += s
    return round(score / total, 3)

def cho_similarity(a, b):
    """초성 일치율"""
    def get_initials(word):
        res = []
        for ch in word:
            if '가' <= ch <= '힣':
                cho, _, _ = split_hangul(ch)
                res.append(CHO_LIST[cho])
        return ''.join(res)
    ia, ib = get_initials(a), get_initials(b)
    return sum(1 for x, y in zip(ia, ib) if x == y) / max(len(ia), len(ib), 1)

def combined_similarity(a, b):
    """자모 60% + 초성 40% 혼합"""
    return 0.6 * hangul_similarity(a, b) + 0.4 * cho_similarity(a, b)

def correct_name(name, ref_list, norm_to_original=None, initials_to_names=None):
    """OCR 결과 이름 → 근무자명단 기반 교정"""
    if not name: return name
    norm_name = normalize_name(name)
    best_match, best_score = name, 0
    for ref in ref_list:
        score = combined_similarity(norm_name, ref)
        if score > best_score:
            best_score = score
            best_match = ref
    if best_score >= 0.75 and best_match != name:
        return best_match
    return name

# =====================================
# 사이드바 입력
# =====================================
st.sidebar.header("순번표 / 차량표 / 옵션")

def _list(s): return [x.strip() for x in s.splitlines() if x.strip()]

# 기본값 (최초 실행 시 초기 데이터)
default_key = ["권한솔","김남균","김면정","김성연","김지은","안유미","윤여헌","윤원실","이나래","이호석","조윤영","조정래"]
default_gy = ["권한솔","김남균","김면정","김병욱","김성연","김주현","김지은","안유미","이호석","조정래"]
default_sd = ["권한솔","김남균","김성연","김주현","이호석","조정래"]
default_veh1 = ["2호 조정래","5호 권한솔","7호 김남균","8호 이호석","9호 김주현","10호 김성연"]
default_veh2 = ["4호 김남균","5호 김병욱","6호 김지은","12호 안유미","14호 김면정","15호 이호석","17호 김성연","18호 권한솔","19호 김주현","22호 조정래"]
default_emp = list({*default_key, *default_gy, *default_sd})

# 파일에서 불러오기
key_order = load_json(KEY_FILE, default_key)
gyoyang_order = load_json(GY_FILE, default_gy)
sudong_order = load_json(SUD_FILE, default_sd)
veh1_lines = load_json(VEH1_FILE, default_veh1)
veh2_lines = load_json(VEH2_FILE, default_veh2)
employee_list = load_json(EMP_FILE, default_emp)

# 사이드바 구성 (기본 숨김)
with st.sidebar.expander("🔑 열쇠 순번", expanded=False):
    key_edit = st.text_area("열쇠 순번", "\n".join(key_order), height=150)
    if st.button("💾 열쇠 저장"):
        save_json(KEY_FILE, _list(key_edit))
        st.sidebar.success("열쇠 순번 저장 완료")

with st.sidebar.expander("📘 교양 순번", expanded=False):
    gy_edit = st.text_area("교양 순번", "\n".join(gyoyang_order), height=150)
    if st.button("💾 교양 저장"):
        save_json(GY_FILE, _list(gy_edit))
        st.sidebar.success("교양 순번 저장 완료")

with st.sidebar.expander("🧰 1종 수동 순번", expanded=False):
    sd_edit = st.text_area("1종 수동 순번", "\n".join(sudong_order), height=150)
    if st.button("💾 1종 저장"):
        save_json(SUD_FILE, _list(sd_edit))
        st.sidebar.success("1종 순번 저장 완료")

with st.sidebar.expander("🚗 차량표", expanded=False):
    v1_edit = st.text_area("1종 수동", "\n".join(veh1_lines), height=120)
    v2_edit = st.text_area("2종 자동", "\n".join(veh2_lines), height=160)
    if st.button("💾 차량표 저장"):
        save_json(VEH1_FILE, _list(v1_edit))
        save_json(VEH2_FILE, _list(v2_edit))
        st.sidebar.success("차량표 저장 완료")

sudong_count = st.sidebar.radio("1종 수동 인원수", [1, 2], index=0)
repair_cars = [x.strip() for x in st.sidebar.text_input("정비 차량 (쉼표로 구분)", value="").split(",") if x.strip()]

# 전일근무 불러오기
prev_data = load_json(PREV_FILE, {"열쇠":"","교양_5교시":"","1종수동":""})
prev_key = prev_data.get("열쇠","")
prev_gy5 = prev_data.get("교양_5교시","")
prev_sd = prev_data.get("1종수동","")
st.sidebar.markdown("---")
st.sidebar.info(f"전일 기준 → 열쇠:{prev_key or '-'}, 교양5:{prev_gy5 or '-'}, 1종:{prev_sd or '-'}")

# =====================================
# GPT OCR (근무제외자 자동추출 포함)
# =====================================
def gpt_extract(img_bytes, want_early=False, want_late=False, want_excluded=False):
    b64 = base64.b64encode(img_bytes).decode()
    user = (
        "이 이미지는 운전면허시험 근무표입니다.\n"
        "1) 도로주행 근무자 이름만 추출하세요.\n"
        "2) 괄호 안의 정보(A-합, B-불 등)는 유지하세요.\n"
        "3) '휴가, 교육, 출장, 공가, 연가, 연차, 돌봄' 등의 표기가 있으면 'excluded'에 이름을 넣으세요.\n"
        + ("4) '조퇴:'가 있다면 이름과 시간을 숫자(예:14, 14.5)로 JSON에 포함.\n" if want_early else "")
        + ("5) '10시 출근' 또는 '외출:' 항목이 있다면 이름과 시간을 숫자(예:10)로 JSON에 포함.\n" if want_late else "")
        + "결과를 JSON으로 반환.\n"
        "예시: {\"names\": [\"김성연(A-합)\",\"이호석(B-불)\"],"
        "\"excluded\": [\"윤원실\"],"
        "\"early_leave\": [{\"name\":\"김병욱\",\"time\":14}],"
        "\"late_start\": [{\"name\":\"안유미\",\"time\":10}]}"
    )
    try:
        res = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role":"system","content":"표에서 이름을 JSON으로 추출"},
                {"role":"user","content":[
                    {"type":"text","text":user},
                    {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}
                ]}
            ]
        )
        raw = res.choices[0].message.content
        js = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        names = js.get("names", [])
        excluded = js.get("excluded", [])
        early = js.get("early_leave", []) if want_early else []
        late = js.get("late_start", []) if want_late else []
        return names, excluded, early, late
    except Exception as e:
        st.error(f"OCR 실패: {e}")
        return [], [], [], []

# =====================================
# 1️⃣ 이미지 업로드 & OCR
# =====================================
st.markdown("<h4>1️⃣ 근무표 이미지 업로드 & OCR</h4>", unsafe_allow_html=True)
col1, col2 = st.columns(2)
with col1: m_file = st.file_uploader("📸 오전 근무표", type=["png","jpg","jpeg"])
with col2: a_file = st.file_uploader("📸 오후 근무표", type=["png","jpg","jpeg"])

if st.button("🧠 오전 GPT 인식"):
    if not m_file: st.warning("오전 이미지를 업로드하세요.")
    else:
        with st.spinner("오전 GPT 분석 중..."):
            m_names, excluded, _, late = gpt_extract(m_file.read(), want_late=True, want_excluded=True)
            st.session_state.m_names_raw = m_names
            st.session_state.excluded_auto = excluded
            st.session_state.late_start = late
            st.success(f"오전 인식 완료: 근무자 {len(m_names)}명, 제외자 {len(excluded)}명")

if st.button("🧠 오후 GPT 인식"):
    if not a_file: st.warning("오후 이미지를 업로드하세요.")
    else:
        with st.spinner("오후 GPT 분석 중..."):
            a_names, _, early, _ = gpt_extract(a_file.read(), want_early=True)
            st.session_state.a_names_raw = a_names
            st.session_state.early_leave = early
            st.success(f"오후 인식 완료: 근무자 {len(a_names)}명, 조퇴 {len(early)}명")

# =====================================
# 2️⃣ 인식 결과 확인 (스크롤 적용)
# =====================================
st.markdown("### 🚫 근무제외자 (자동추출 후 수정 가능)")
excluded_raw = "\n".join(st.session_state.get("excluded_auto", []))
excluded_text = st.text_area("근무제외자", excluded_raw, height=120)

st.markdown("### 🌅 오전 근무자 (수정 가능)")
morning_raw = "\n".join(st.session_state.get("m_names_raw", []))
morning_text = st.text_area("오전 근무자", morning_raw, height=220)

st.markdown("### 🌇 오후 근무자 (수정 가능)")
afternoon_raw = "\n".join(st.session_state.get("a_names_raw", []))
afternoon_text = st.text_area("오후 근무자", afternoon_raw, height=220)

m_list = [x.strip() for x in morning_text.splitlines() if x.strip()]
a_list = [x.strip() for x in afternoon_text.splitlines() if x.strip()]
excluded = {x.strip() for x in excluded_text.splitlines() if x.strip()}

# =====================================
# 배정 보조 유틸
# =====================================
def parse_vehicle_map(lines):
    m = {}
    for line in lines:
        parts = line.strip().split()
        if len(parts) >= 2:
            car = parts[0]
            name = " ".join(parts[1:])
            m[name] = car
    return m

def get_vehicle(name, veh_map):
    nkey = normalize_name(name)
    for k, v in veh_map.items():
        if normalize_name(k) == nkey:
            return v
    return ""

def mark_car(car, repair_list):
    return f"{car}{' (정비)' if (car and car in repair_list) else ''}" if car else ""

def pick_next_from_cycle(cycle, last, allowed_norms: set):
    """순번 순환 선택 (allowed_norms: 출근/제외 반영된 허용자 집합; 정규화 기준)"""
    if not cycle:
        return None
    cyc_norm = [normalize_name(x) for x in cycle]
    last_norm = normalize_name(last)
    start = (cyc_norm.index(last_norm) + 1) % len(cycle) if last_norm in cyc_norm else 0
    for i in range(len(cycle)*2):
        cand = cycle[(start + i) % len(cycle)]
        if normalize_name(cand) in allowed_norms:
            return cand
    return None

def extract_course_from_token(token: str):
    """
    이름 토큰 내 괄호에서 코스/합불 추출.
    - 특수문자 제거 후 'A' 또는 'B'만 인식, '합'/'불'로 결과 판단.
    - 예: '(A-합)', '(A합)', '(B 불)' 등 → ('A', '합격') / ('B', '불합격')
    """
    m = re.search(r"\((.*?)\)", token)
    if not m:
        return None
    raw = m.group(1)
    up = re.sub(r"[^A-Za-z가-힣]", "", raw).upper()  # 특수문자 제거
    course = 'A' if 'A' in up else ('B' if 'B' in up else None)
    result = '합격' if '합' in up else ('불합격' if '불' in up else None)
    if course and result:
        return course, result
    return None

# =====================================
# 3️⃣ 오전 배정
# =====================================
st.markdown("---")
st.markdown("## 3️⃣ 오전 근무 배정")

if st.button("📋 오전 배정 생성"):
    try:
        # 차량표 매핑
        veh1_map = parse_vehicle_map(veh1_lines)
        veh2_map = parse_vehicle_map(veh2_lines)

        # OCR → 교정 → 코스 추출
        corrected_m = [correct_name(x, employee_list) for x in m_list]
        course_records = []
        cleaned_m = []
        for token in corrected_m:
            # 이름과 코스 분리
            info = extract_course_from_token(token)
            pure = re.sub(r"\(.*?\)", "", token).strip()
            if info:
                c, r = info
                course_records.append({"name": pure, "course": f"{c}코스", "result": r})
            cleaned_m.append(pure)
        # 코스 결과 저장 (오전 출력용)
        save_json(COURSE_FILE, course_records)

        # 제외 반영
        excl_norms = {normalize_name(x) for x in excluded}
        m_norms = {normalize_name(x) for x in cleaned_m} - excl_norms

        # 🔑 열쇠(전일 이후 순번)
        filtered_keys = [x for x in key_order if normalize_name(x) not in excl_norms]
        if filtered_keys:
            knorms = [normalize_name(x) for x in filtered_keys]
            pnorm = normalize_name(prev_key)
            today_key = filtered_keys[(knorms.index(pnorm)+1) % len(filtered_keys)] if pnorm in knorms else filtered_keys[0]
        else:
            today_key = ""

        # 🧑‍🏫 오전 교양 1·2교시
        gy1 = pick_next_from_cycle(gyoyang_order, prev_gy5, m_norms)
        gy1_norm = normalize_name(gy1) if gy1 else None
        gy2 = pick_next_from_cycle(gyoyang_order, (gy1 or prev_gy5), m_norms - ({gy1_norm} if gy1_norm else set()))

        # 🔧 1종 수동
        sud_m, last_pick = [], prev_sd
        for _ in range(sudong_count):
            cand = pick_next_from_cycle(sudong_order, last_pick, m_norms - {normalize_name(x) for x in sud_m})
            if not cand:
                break
            sud_m.append(cand)
            last_pick = cand

        # 🚗 2종 자동 = 오전 전체 - 1종
        sud_norms_m = {normalize_name(x) for x in sud_m}
        auto_m = [nm for nm in cleaned_m if normalize_name(nm) in (m_norms - sud_norms_m)]

        # 상태 저장 (오전 대비/차량 비교용)
        st.session_state["today_key"] = today_key
        st.session_state["am_gy_base_for_pm"] = gy2 or gy1 or prev_gy5
        st.session_state["am_sud_base_for_pm"] = (sud_m[-1] if sud_m else prev_sd)

        st.session_state["am_driver_names"] = sud_m + auto_m
        st.session_state["am_cars_1"] = [get_vehicle(x, veh1_map) for x in sud_m if get_vehicle(x, veh1_map)]
        st.session_state["am_cars_2"] = [get_vehicle(x, veh2_map) for x in auto_m if get_vehicle(x, veh2_map)]

        # === 출력
        lines = []
        if today_key: lines.append(f"열쇠: {today_key}")
        if gy1: lines.append(f"1교시(교양): {gy1}")
        if gy2: lines.append(f"2교시(교양): {gy2}")

        if sud_m:
            for nm in sud_m:
                lines.append(f"1종수동: {nm} {mark_car(get_vehicle(nm, veh1_map), repair_cars)}")
            if sudong_count == 2 and len(sud_m) < 2:
                lines.append("※ 수동 가능 인원이 1명입니다.")
        else:
            lines.append("1종수동: (배정자 없음)")

        if auto_m:
            lines.append("2종 자동:")
            for nm in auto_m:
                lines.append(f" • {nm} {mark_car(get_vehicle(nm, veh2_map), repair_cars)}")
        else:
            lines.append("2종 자동: (배정자 없음)")

        # 🧭 코스점검 결과(오전만)
        if course_records:
            lines.append("")
            lines.append("🧭 코스점검 결과:")
            a_pass = [c["name"] for c in course_records if c["course"]=="A코스" and c["result"]=="합격"]
            a_fail = [c["name"] for c in course_records if c["course"]=="A코스" and c["result"]=="불합격"]
            b_pass = [c["name"] for c in course_records if c["course"]=="B코스" and c["result"]=="합격"]
            b_fail = [c["name"] for c in course_records if c["course"]=="B코스" and c["result"]=="불합격"]
            if a_pass: lines.append(" • A코스 합격: " + ", ".join(a_pass))
            if a_fail: lines.append(" • A코스 불합격: " + ", ".join(a_fail))
            if b_pass: lines.append(" • B코스 합격: " + ", ".join(b_pass))
            if b_fail: lines.append(" • B코스 불합격: " + ", ".join(b_fail))

        result_text = "\n".join(lines)
        st.markdown("### 📋 오전 결과")
        st.code(result_text, language="text")
        clipboard_copy_button("📋 결과 복사하기", result_text)

    except Exception as e:
        st.error(f"오전 오류: {e}")

# =====================================
# 4️⃣ 오후 배정 (+오전 대비 비교/미배정/저장)
# =====================================
st.markdown("---")
st.markdown("## 4️⃣ 오후 근무 배정")

save_check = st.checkbox("이 결과를 전일근무.json으로 저장", value=True)

if st.button("📋 오후 배정 생성"):
    try:
        veh1_map = parse_vehicle_map(veh1_lines)
        veh2_map = parse_vehicle_map(veh2_lines)

        # 교정
        corrected_a = [correct_name(x, employee_list) for x in a_list]
        excl_norms = {normalize_name(x) for x in excluded}
        a_norms = {normalize_name(x) for x in corrected_a} - excl_norms

        # 오후 교양 3·4·5
        gy_start = st.session_state.get("am_gy_base_for_pm", prev_gy5)
        used = set()
        gy3 = pick_next_from_cycle(gyoyang_order, gy_start, a_norms)
        if gy3: used.add(normalize_name(gy3))
        gy4 = pick_next_from_cycle(gyoyang_order, gy3 or gy_start, a_norms - used)
        if gy4: used.add(normalize_name(gy4))
        gy5 = pick_next_from_cycle(gyoyang_order, gy4 or gy3 or gy_start, a_norms - used)

        # 오후 1종 수동 (교양과 중복 허용)
        sud_base = st.session_state.get("am_sud_base_for_pm", prev_sd)
        sud_a, last_pick = [], sud_base
        for _ in range(sudong_count):
            cand = pick_next_from_cycle(sudong_order, last_pick, a_norms)
            if not cand:
                break
            sud_a.append(cand)
            last_pick = cand

        # 오후 2종 자동 = 오후 전체 - 1종
        sud_norms_a = {normalize_name(x) for x in sud_a}
        auto_a = [nm for nm in corrected_a if normalize_name(nm) in (a_norms - sud_norms_a)]

        # === 출력
        today_key = st.session_state.get("today_key", prev_key)
        lines = []
        if today_key: lines.append(f"열쇠: {today_key}")
        if gy3: lines.append(f"3교시(교양): {gy3}")
        if gy4: lines.append(f"4교시(교양): {gy4}")
        if gy5: lines.append(f"5교시(교양): {gy5}")

        if sud_a:
            for nm in sud_a:
                lines.append(f"1종수동: {nm} {mark_car(get_vehicle(nm, veh1_map), repair_cars)}")
            if sudong_count == 2 and len(sud_a) < 2:
                lines.append("※ 수동 가능 인원이 1명입니다.")
        else:
            lines.append("1종수동: (배정자 없음)")

        if auto_a:
            lines.append("2종 자동:")
            for nm in auto_a:
                lines.append(f" • {nm} {mark_car(get_vehicle(nm, veh2_map), repair_cars)}")
        else:
            lines.append("2종 자동: (배정자 없음)")

        # === 오전 대비 비교 (신규 투입 / 빠진 인원)
        lines.append("")
        lines.append("오전 대비 비교:")

        am_drivers = st.session_state.get("am_driver_names", [])  # 오전 운전 전체(1+2)
        am_norms = {normalize_name(x) for x in am_drivers}
        pm_drivers = sud_a + auto_a
        pm_norms = {normalize_name(x) for x in pm_drivers}

        new_joiners = sorted([nm for nm in pm_drivers if normalize_name(nm) not in am_norms])
        missing = sorted([nm for nm in am_drivers if normalize_name(nm) not in pm_norms])

        if new_joiners:
            lines.append(" • 신규 투입: " + ", ".join(new_joiners))
        if missing:
            lines.append(" • 빠진 인원: " + ", ".join(missing))
        if not new_joiners and not missing:
            lines.append(" • 변동 없음")

        # === 미배정 차량 (오전에 있었는데 오후에 없는 차량만)
        am_cars_1 = set(st.session_state.get("am_cars_1", []))
        am_cars_2 = set(st.session_state.get("am_cars_2", []))
        pm_cars_1 = {get_vehicle(x, veh1_map) for x in sud_a if get_vehicle(x, veh1_map)}
        pm_cars_2 = {get_vehicle(x, veh2_map) for x in auto_a if get_vehicle(x, veh2_map)}
        unassigned_1 = sorted([c for c in am_cars_1 if c and c not in pm_cars_1])
        unassigned_2 = sorted([c for c in am_cars_2 if c and c not in pm_cars_2])

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

        # 출력 + 복사
        result_text = "\n".join(lines)
        st.markdown("### 📋 오후 결과")
        st.code(result_text, language="text")
        clipboard_copy_button("📋 결과 복사하기", result_text)

        # ✅ 전일 저장
        if save_check:
            data = {
                "열쇠": today_key,
                "교양_5교시": gy5 or gy4 or gy3 or prev_gy5,
                "1종수동": (sud_a[-1] if sud_a else prev_sd)
            }
            save_json(PREV_FILE, data)
            st.success("전일근무.json 업데이트 완료 ✅")

    except Exception as e:
        st.error(f"오후 오류: {e}")
