# =====================================
# app.py — 도로주행 근무자동배정 v7.17.2 (완전본)
# =====================================
import streamlit as st
from openai import OpenAI
import base64, re, json, os, difflib

st.set_page_config(page_title="도로주행 근무자동배정", layout="wide")
st.markdown("<h3 style='text-align:center; font-size:22px;'>🚗 도로주행 근무자동배정</h3>", unsafe_allow_html=True)

# =====================================
# OpenAI API 초기화
# =====================================
try:
    client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
except Exception:
    st.error("⚠️ OPENAI_API_KEY 설정 필요")
    st.stop()
MODEL_NAME = "gpt-4o"

# =====================================
# 파일 유틸 함수
# =====================================
def load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return default or []
    return default or []

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"{path} 저장 실패: {e}")

# =====================================
# 교정용 한글 자모 분리/비교
# =====================================
CHO_LIST = list("ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ")
JUNG_LIST = list("ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ")
JONG_LIST = [""] + list("ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ")

# (기존 것을 이 블록으로 교체)
CONFUSABLES = {
    # 초성/종성 자주 헷갈림
    'ㅁ': ['ㅂ'], 'ㅂ': ['ㅁ'],
    'ㄴ': ['ㄹ'], 'ㄹ': ['ㄴ'],
    'ㄱ': ['ㅋ'], 'ㅋ': ['ㄱ'],
    'ㅅ': ['ㅈ','ㅊ'], 'ㅈ': ['ㅅ','ㅊ'], 'ㅊ': ['ㅈ','ㅅ'],

    # 중성 자주 헷갈림
    'ㅐ': ['ㅔ'], 'ㅔ': ['ㅐ'],
    'ㅡ': ['ㅜ'], 'ㅜ': ['ㅡ'],   # ★ 은↔운 케이스 잡는 핵심
    # (필요하면 추가)
    # 'ㅓ': ['ㅗ'], 'ㅗ': ['ㅓ'],
    # 'ㅕ': ['ㅑ'], 'ㅑ': ['ㅕ'],
}


def split_hangul(c):
    code = ord(c) - 0xAC00
    cho = code // 588
    jung = (code - cho * 588) // 28
    jong = code % 28
    return cho, jung, jong

def similar_jamo(a, b):
    return a == b or (a in CONFUSABLES and b in CONFUSABLES[a])

def hangul_similarity(a, b):
    """자모 유사도 (OCR 혼동 허용 포함)"""
    if not a or not b:
        return 0
    score = 0
    total = max(len(a), len(b))
    for i in range(min(len(a), len(b))):
        ca, cb = a[i], b[i]
        if not ('가' <= ca <= '힣' and '가' <= cb <= '힣'):
            score += 1 if ca == cb else 0
            continue
        cho_a, jung_a, jong_a = split_hangul(ca)
        cho_b, jung_b, jong_b = split_hangul(cb)
        s = 0
        if similar_jamo(CHO_LIST[cho_a], CHO_LIST[cho_b]): s += 0.4
        if similar_jamo(JUNG_LIST[jung_a], JUNG_LIST[jung_b]): s += 0.4
        if similar_jamo(JONG_LIST[jong_a], JONG_LIST[jong_b]): s += 0.2
        score += s
    return score / total

def correct_name_v2(name, valid_names, cutoff=0.6):
    """전체 근무자 기준 고급 오타 교정"""
    if not name or not valid_names:
        return name
    name_norm = re.sub(r"[^가-힣]", "", name)
    best_match, best_score = None, 0
    for valid in valid_names:
        score = hangul_similarity(name_norm, valid)
        if score > best_score:
            best_match, best_score = valid, score
    return best_match if best_score >= cutoff else name

def normalize_name(s):
    return re.sub(r"[^가-힣]", "", re.sub(r"\(.*?\)", "", s or ""))

# =====================================
# 기본 JSON 파일들
# =====================================
EMP_FILE = "employee_list.json"
PREV_FILE = "전일근무.json"
COURSE_FILE = "course_result.json"

# =====================================
# 전체 근무자 관리
# =====================================
st.sidebar.header("근무 데이터 관리")
with st.sidebar.expander("👥 전체 근무자명단", expanded=False):
    default_emp = [
        "권한솔","김남균","김면정","김성연","김지은","안유미",
        "윤여헌","윤원실","이나래","이호석","조윤영","조정래","김병욱","김주현"
    ]
    employee_list = load_json(EMP_FILE, default_emp)
    emp_edit = st.text_area("전체 근무자", "\n".join(employee_list), height=180)
    if st.button("💾 근무자명단 저장"):
        new_list = [x.strip() for x in emp_edit.splitlines() if x.strip()]
        save_json(EMP_FILE, new_list)
        st.sidebar.success("전체 근무자 저장 완료")

# =====================================
# 순번/차량표 파일 정의
# =====================================
KEY_FILE  = "data_key.json"
GY_FILE   = "data_gyoyang.json"
SUD_FILE  = "data_sudong.json"
VEH1_FILE = "veh1.json"
VEH2_FILE = "veh2.json"

# 기본값
default_key = ["권한솔","김남균","김면정","김성연","김지은","안유미","윤여헌","윤원실","이나래","이호석","조윤영","조정래"]
default_gy  = ["권한솔","김남균","김면정","김병욱","김성연","김주현","김지은","안유미","이호석","조정래"]
default_sd  = ["권한솔","김남균","김성연","김주현","이호석","조정래"]
default_veh1 = ["2호 조정래","5호 권한솔","7호 김남균","8호 이호석","9호 김주현","10호 김성연"]
default_veh2 = ["4호 김남균","5호 김병욱","6호 김지은","12호 안유미","14호 김면정","15호 이호석","17호 김성연","18호 권한솔","19호 김주현","22호 조정래"]

# 파일 로드
key_order   = load_json(KEY_FILE,  default_key)
gyoyang_ord = load_json(GY_FILE,   default_gy)
sudong_ord  = load_json(SUD_FILE,  default_sd)
veh1_lines  = load_json(VEH1_FILE, default_veh1)
veh2_lines  = load_json(VEH2_FILE, default_veh2)

# -------------------------------------
# 사이드바: 순번/차량표(숨김 → 수정/저장)
# -------------------------------------
st.sidebar.markdown("---")
with st.sidebar.expander("🔑 열쇠 순번", expanded=False):
    key_edit = st.text_area("열쇠 순번", "\n".join(key_order), height=150)
    if st.button("💾 열쇠 저장"):
        save_json(KEY_FILE, [x.strip() for x in key_edit.splitlines() if x.strip()])
        st.sidebar.success("열쇠 순번 저장 완료")

with st.sidebar.expander("📘 교양 순번", expanded=False):
    gy_edit = st.text_area("교양 순번", "\n".join(gyoyang_ord), height=150)
    if st.button("💾 교양 저장"):
        save_json(GY_FILE, [x.strip() for x in gy_edit.splitlines() if x.strip()])
        st.sidebar.success("교양 순번 저장 완료")

with st.sidebar.expander("🧰 1종 수동 순번", expanded=False):
    sd_edit = st.text_area("1종 수동 순번", "\n".join(sudong_ord), height=150)
    if st.button("💾 1종 저장"):
        save_json(SUD_FILE, [x.strip() for x in sd_edit.splitlines() if x.strip()])
        st.sidebar.success("1종 수동 순번 저장 완료")

with st.sidebar.expander("🚗 차량표 (1종/2종)", expanded=False):
    v1_edit = st.text_area("1종 수동 차량표", "\n".join(veh1_lines), height=120)
    v2_edit = st.text_area("2종 자동 차량표", "\n".join(veh2_lines), height=160)
    if st.button("💾 차량표 저장"):
        save_json(VEH1_FILE, [x.strip() for x in v1_edit.splitlines() if x.strip()])
        save_json(VEH2_FILE, [x.strip() for x in v2_edit.splitlines() if x.strip()])
        st.sidebar.success("차량표 저장 완료")

sudong_count = st.sidebar.radio("1종 수동 인원수", [1, 2], index=0)
repair_cars = [x.strip() for x in st.sidebar.text_input("정비 차량 (쉼표로 구분)", value="").split(",") if x.strip()]

# 전일값 로드/표시
prev_data = load_json(PREV_FILE, {"열쇠":"", "교양_5교시":"", "1종수동":""})
prev_key  = prev_data.get("열쇠","")
prev_gy5  = prev_data.get("교양_5교시","")
prev_sd   = prev_data.get("1종수동","")
st.sidebar.info(f"전일 기준 → 열쇠:{prev_key or '-'}, 교양5:{prev_gy5 or '-'}, 1종:{prev_sd or '-'}")

# =====================================
# GPT OCR: 근무자/제외자/조퇴/지각 추출
# =====================================
def gpt_extract(img_bytes, want_early=False, want_late=False, want_excluded=False):
    b64 = base64.b64encode(img_bytes).decode()
    user = (
        "이 이미지는 운전면허시험 근무표입니다.\n"
        "1) 도로주행 근무자 이름만 names 배열에 추출.\n"
        "2) 괄호(A-합, B-불 등)는 그대로 두되, JSON에는 괄호 포함 원문을 names에 넣으세요.\n"
        "3) '휴가, 교육, 출장, 공가, 연가, 연차, 돌봄' 표기된 이름은 excluded 배열에 넣으세요.\n"
        + ("4) '조퇴:'가 있으면 early_leave: [{name, time(숫자)}].\n" if want_early else "")
        + ("5) '10시 출근' 또는 '외출:'이 있으면 late_start: [{name, time(숫자)}].\n" if want_late else "")
        + "반환 예: {\"names\":[\"김성연(A-합)\",\"이호석(B-불)\"],"
          "\"excluded\":[\"윤원실\"],"
          "\"early_leave\":[{\"name\":\"김병욱\",\"time\":14}],"
          "\"late_start\":[{\"name\":\"안유미\",\"time\":10}]}"
    )
    try:
        res = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role":"system","content":"표에서 이름/제외자 정보를 JSON으로 추출"},
                {"role":"user","content":[
                    {"type":"text","text":user},
                    {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}
                ]}
            ]
        )
        raw = res.choices[0].message.content
        js = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        return (
            js.get("names", []),
            js.get("excluded", []),
            js.get("early_leave", []) if want_early else [],
            js.get("late_start", []) if want_late else []
        )
    except Exception as e:
        st.error(f"OCR 실패: {e}")
        return [], [], [], []

# =====================================
# 1) 이미지 업로드 & OCR 실행
# =====================================
st.markdown("<h4 style='margin-top:6px;'>1️⃣ 근무표 이미지 업로드 & OCR</h4>", unsafe_allow_html=True)
c1, c2 = st.columns(2)
with c1: m_file = st.file_uploader("📸 오전 근무표", type=["png","jpg","jpeg"])
with c2: a_file = st.file_uploader("📸 오후 근무표", type=["png","jpg","jpeg"])

b1, b2 = st.columns(2)
with b1:
    if st.button("🧠 오전 GPT 인식"):
        if not m_file:
            st.warning("오전 이미지를 업로드하세요.")
        else:
            with st.spinner("오전 GPT 분석 중..."):
                m_names, excluded_auto, _, late = gpt_extract(m_file.read(), want_late=True, want_excluded=True)
                st.session_state.m_names_raw = m_names
                st.session_state.excluded_auto = excluded_auto
                st.session_state.late_start = late
                st.success(f"오전 인식 → 근무자 {len(m_names)}명, 제외자 {len(excluded_auto)}명")

with b2:
    if st.button("🧠 오후 GPT 인식"):
        if not a_file:
            st.warning("오후 이미지를 업로드하세요.")
        else:
            with st.spinner("오후 GPT 분석 중..."):
                a_names, _, early, _ = gpt_extract(a_file.read(), want_early=True)
                st.session_state.a_names_raw = a_names
                st.session_state.early_leave = early
                st.success(f"오후 인식 → 근무자 {len(a_names)}명, 조퇴 {len(early)}명")

# =====================================
# 2) 인식 결과 확인/수정 (스크롤 적용)
# =====================================
# 근무제외자 타이틀 (작게)
st.markdown("<h6 style='font-size:15px; font-weight:bold; margin-top:10px;'>근무제외자</h6>", unsafe_allow_html=True)
excluded_raw = "\n".join(st.session_state.get("excluded_auto", []))
excluded_text = st.text_area("자동추출 후 수정 가능", excluded_raw, height=110, label_visibility="collapsed")

st.markdown("<h5 style='margin-top:6px;'>🌅 오전 근무자 (수정 가능)</h5>", unsafe_allow_html=True)
morning_raw = "\n".join(st.session_state.get("m_names_raw", []))
morning_text = st.text_area("오전 근무자", morning_raw, height=220)

st.markdown("<h5 style='margin-top:6px;'>🌇 오후 근무자 (수정 가능)</h5>", unsafe_allow_html=True)
afternoon_raw = "\n".join(st.session_state.get("a_names_raw", []))
afternoon_text = st.text_area("오후 근무자", afternoon_raw, height=220)

# 리스트 변환
m_list = [x.strip() for x in morning_text.splitlines() if x.strip()]
a_list = [x.strip() for x in afternoon_text.splitlines() if x.strip()]
excluded = {x.strip() for x in excluded_text.splitlines() if x.strip()}

# =====================================
# 보조 함수
# =====================================
def clipboard_copy_button(label, text):
    """Streamlit 클립보드 복사 버튼"""
    clip_id = f"copy_{abs(hash(label))}"
    html = f"""
    <button id="{clip_id}" style="background:#3b82f6;color:white;border:none;
    padding:6px 12px;border-radius:6px;cursor:pointer;margin-top:6px;">{label}</button>
    <script>
    const b = document.getElementById("{clip_id}");
    b.onclick = () => {{
      navigator.clipboard.writeText(`{text}`);
      b.innerText = "✅ 복사됨!";
      setTimeout(()=>b.innerText="{label}",1500);
    }};
    </script>
    """
    st.markdown(html, unsafe_allow_html=True)

def extract_course_from_token(token: str):
    """괄호 내 'A'/'B' + '합/불' 추출"""
    m = re.search(r"\((.*?)\)", token)
    if not m:
        return None
    raw = re.sub(r"[^A-Za-z가-힣]", "", m.group(1)).upper()
    course = "A" if "A" in raw else ("B" if "B" in raw else None)
    result = "합격" if "합" in raw else ("불합격" if "불" in raw else None)
    if course and result:
        return course, result
    return None

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
    return f"{car}{' (정비)' if car in repair_list else ''}" if car else ""

def pick_next_from_cycle(cycle, last, allowed_norms: set):
    """순번 순환 선택"""
    if not cycle:
        return None
    cyc_norm = [normalize_name(x) for x in cycle]
    last_norm = normalize_name(last)
    start = (cyc_norm.index(last_norm) + 1) % len(cycle) if last_norm in cyc_norm else 0
    for i in range(len(cycle)*2):
        cand = cycle[(start+i) % len(cycle)]
        if normalize_name(cand) in allowed_norms:
            return cand
    return None

# =====================================
# 3️⃣ 오전 근무 배정
# =====================================
st.markdown("---")
st.markdown("## 3️⃣ 오전 근무 배정")

if st.button("📋 오전 배정 생성"):
    try:
        veh1_map = parse_vehicle_map(veh1_lines)
        veh2_map = parse_vehicle_map(veh2_lines)

        corrected_m = [correct_name_v2(x, employee_list) for x in m_list]
        course_records = []
        cleaned_m = []
        for token in corrected_m:
            info = extract_course_from_token(token)
            pure = re.sub(r"\(.*?\)", "", token).strip()
            if info:
                c, r = info
                course_records.append({"name": pure, "course": f"{c}코스", "result": r})
            cleaned_m.append(pure)
        save_json(COURSE_FILE, course_records)

        excl_norms = {normalize_name(x) for x in excluded}
        m_norms = {normalize_name(x) for x in cleaned_m} - excl_norms

        key_filtered = [x for x in key_order if normalize_name(x) not in excl_norms]
        if key_filtered:
            knorms = [normalize_name(x) for x in key_filtered]
            pnorm = normalize_name(prev_key)
            today_key = key_filtered[(knorms.index(pnorm)+1)%len(key_filtered)] if pnorm in knorms else key_filtered[0]
        else:
            today_key = ""

        gy1 = pick_next_from_cycle(gyoyang_ord, prev_gy5, m_norms)
        gy1_norm = normalize_name(gy1) if gy1 else None
        gy2 = pick_next_from_cycle(gyoyang_ord, gy1 or prev_gy5, m_norms - ({gy1_norm} if gy1_norm else set()))

        sud_m, last_pick = [], prev_sd
        for _ in range(sudong_count):
            cand = pick_next_from_cycle(sudong_ord, last_pick, m_norms - {normalize_name(x) for x in sud_m})
            if not cand: break
            sud_m.append(cand)
            last_pick = cand

        sud_norms_m = {normalize_name(x) for x in sud_m}
        auto_m = [nm for nm in cleaned_m if normalize_name(nm) in (m_norms - sud_norms_m)]

        st.session_state["today_key"] = today_key
        st.session_state["am_gy_base_for_pm"] = gy2 or gy1 or prev_gy5
        st.session_state["am_sud_base_for_pm"] = sud_m[-1] if sud_m else prev_sd
        st.session_state["am_driver_names"] = sud_m + auto_m
        st.session_state["am_cars_1"] = [get_vehicle(x, veh1_map) for x in sud_m if get_vehicle(x, veh1_map)]
        st.session_state["am_cars_2"] = [get_vehicle(x, veh2_map) for x in auto_m if get_vehicle(x, veh2_map)]

        # 출력
        lines = []
        if today_key: lines.append(f"열쇠: {today_key}")
        if gy1: lines.append(f"1교시(교양): {gy1}")
        if gy2: lines.append(f"2교시(교양): {gy2}")

        if sud_m:
            for nm in sud_m:
                lines.append(f"1종수동: {nm} {mark_car(get_vehicle(nm, veh1_map), repair_cars)}")
        else:
            lines.append("1종수동: (배정자 없음)")

        if auto_m:
            lines.append("2종 자동:")
            for nm in auto_m:
                lines.append(f" • {nm} {mark_car(get_vehicle(nm, veh2_map), repair_cars)}")

        # 코스점검
        if course_records:
            lines.append("")
            lines.append("🧭 코스점검 결과:")
            for c in ["A","B"]:
                passed = [r["name"] for r in course_records if r["course"]==f"{c}코스" and r["result"]=="합격"]
                failed = [r["name"] for r in course_records if r["course"]==f"{c}코스" and r["result"]=="불합격"]
                if passed: lines.append(f" • {c}코스 합격: {', '.join(passed)}")
                if failed: lines.append(f" • {c}코스 불합격: {', '.join(failed)}")

        result_text = "\n".join(lines)
        st.markdown("### 📋 오전 결과")
        st.code(result_text, language="text")
        clipboard_copy_button("📋 결과 복사하기", result_text)

    except Exception as e:
        st.error(f"오전 오류: {e}")

# =====================================
# 4️⃣ 오후 근무 배정
# =====================================
st.markdown("---")
st.markdown("## 4️⃣ 오후 근무 배정")
save_check = st.checkbox("이 결과를 전일근무.json으로 저장", value=True)

if st.button("📋 오후 배정 생성"):
    try:
        veh1_map = parse_vehicle_map(veh1_lines)
        veh2_map = parse_vehicle_map(veh2_lines)
        corrected_a = [correct_name_v2(x, employee_list) for x in a_list]
        excl_norms = {normalize_name(x) for x in excluded}
        a_norms = {normalize_name(x) for x in corrected_a} - excl_norms

        gy_start = st.session_state.get("am_gy_base_for_pm", prev_gy5)
        used = set()
        gy3 = pick_next_from_cycle(gyoyang_ord, gy_start, a_norms)
        if gy3: used.add(normalize_name(gy3))
        gy4 = pick_next_from_cycle(gyoyang_ord, gy3 or gy_start, a_norms - used)
        if gy4: used.add(normalize_name(gy4))
        gy5 = pick_next_from_cycle(gyoyang_ord, gy4 or gy3 or gy_start, a_norms - used)

        sud_base = st.session_state.get("am_sud_base_for_pm", prev_sd)
        sud_a, last_pick = [], sud_base
        for _ in range(sudong_count):
            cand = pick_next_from_cycle(sudong_ord, last_pick, a_norms)
            if not cand: break
            sud_a.append(cand)
            last_pick = cand

        sud_norms_a = {normalize_name(x) for x in sud_a}
        auto_a = [nm for nm in corrected_a if normalize_name(nm) in (a_norms - sud_norms_a)]

        today_key = st.session_state.get("today_key", prev_key)
        lines = []
        if today_key: lines.append(f"열쇠: {today_key}")
        if gy3: lines.append(f"3교시(교양): {gy3}")
        if gy4: lines.append(f"4교시(교양): {gy4}")
        if gy5: lines.append(f"5교시(교양): {gy5}")

        if sud_a:
            for nm in sud_a:
                lines.append(f"1종수동: {nm} {mark_car(get_vehicle(nm, veh1_map), repair_cars)}")
        else:
            lines.append("1종수동: (배정자 없음)")

        if auto_a:
            lines.append("2종 자동:")
            for nm in auto_a:
                lines.append(f" • {nm} {mark_car(get_vehicle(nm, veh2_map), repair_cars)}")

        # 오전 대비 비교
        lines.append("\n오전 대비 비교:")
        am_drivers = st.session_state.get("am_driver_names", [])
        am_norms = {normalize_name(x) for x in am_drivers}
        pm_norms = {normalize_name(x) for x in (sud_a + auto_a)}
        new_joiners = [nm for nm in (sud_a + auto_a) if normalize_name(nm) not in am_norms]
        missing = [nm for nm in am_drivers if normalize_name(nm) not in pm_norms]
        if new_joiners: lines.append(" • 신규 투입: " + ", ".join(sorted(new_joiners)))
        if missing: lines.append(" • 빠진 인원: " + ", ".join(sorted(missing)))
        if not new_joiners and not missing:
            lines.append(" • 변동 없음")

        # 미배정 차량
        am_c1 = set(st.session_state.get("am_cars_1", []))
        am_c2 = set(st.session_state.get("am_cars_2", []))
        pm_c1 = {get_vehicle(x, veh1_map) for x in sud_a if get_vehicle(x, veh1_map)}
        pm_c2 = {get_vehicle(x, veh2_map) for x in auto_a if get_vehicle(x, veh2_map)}
        un1 = sorted([c for c in am_c1 if c and c not in pm_c1])
        un2 = sorted([c for c in am_c2 if c and c not in pm_c2])
        if un1 or un2:
            lines.append("")
            lines.append("미배정 차량:")
            if un1:
                lines.append(" [1종 수동]")
                for c in un1: lines.append(f"  • {c} 마감")
            if un2:
                lines.append(" [2종 자동]")
                for c in un2: lines.append(f"  • {c} 마감")

        result_text = "\n".join(lines)
        st.markdown("### 📋 오후 결과")
        st.code(result_text, language="text")
        clipboard_copy_button("📋 결과 복사하기", result_text)

        if save_check:
            save_json(PREV_FILE, {"열쇠":today_key,"교양_5교시":gy5 or gy4 or gy3 or prev_gy5,"1종수동":(sud_a[-1] if sud_a else prev_sd)})
            st.success("전일근무.json 업데이트 완료 ✅")

    except Exception as e:
        st.error(f"오후 오류: {e}")
