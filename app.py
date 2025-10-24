# =====================================
# app.py — 도로주행 근무자동배정 v7.18.2 (교정·코스완전본)
# =====================================
import streamlit as st
from openai import OpenAI
import base64, re, json, os, difflib

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
# JSON 유틸
# =====================================
def load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return default if default is not None else []
    return default if default is not None else []

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"{path} 저장 실패: {e}")

# =====================================
# 교정 알고리즘 (correct_name_v3)
#  - 자모 유사도 + difflib 평균
#  - OCR 혼동자(ㅁ↔ㅂ, ㅡ↔ㅜ 등) 허용
#  - 상대점수 0.08 미만이면 교정 보류
# =====================================
CHO_LIST = list("ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ")
JUNG_LIST = list("ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ")
JONG_LIST = [""] + list("ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ")

CONFUSABLES = {
    'ㅁ': ['ㅂ'], 'ㅂ': ['ㅁ'],
    'ㄴ': ['ㄹ'], 'ㄹ': ['ㄴ'],
    'ㄱ': ['ㅋ'], 'ㅋ': ['ㄱ'],
    'ㅅ': ['ㅈ','ㅊ'], 'ㅈ': ['ㅅ','ㅊ'], 'ㅊ': ['ㅈ','ㅅ'],
    'ㅐ': ['ㅔ'], 'ㅔ': ['ㅐ'],
    'ㅡ': ['ㅜ'], 'ㅜ': ['ㅡ'],
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
    if not a or not b: return 0
    score, total = 0, max(len(a), len(b))
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

def normalized_name(s):
    return re.sub(r"[^가-힣]", "", s or "")

def correct_name_v3(name, valid_names, cutoff=0.6):
    if not name or not valid_names: return name
    n = normalized_name(name)
    best = (None, 0); scores = []
    for valid in valid_names:
        v = normalized_name(valid)
        jamo_score = hangul_similarity(n, v)
        seq_score = difflib.SequenceMatcher(None, n, v).ratio()
        score = (jamo_score + seq_score) / 2
        scores.append((valid, score))
        if score > best[1]: best = (valid, score)
    scores.sort(key=lambda x: x[1], reverse=True)
    if len(scores) > 1 and (scores[0][1] - scores[1][1]) < 0.08:
        return name  # 비슷한 후보 여럿 → 교정 보류
    return best[0] if best[1] >= cutoff else name

# normalize_name 별칭 (기존 코드 호환)
def normalize_name(s): 
    return normalized_name(s)

# =====================================
# 코스 추출 + 배정용 이름 정리
# =====================================
def extract_course_from_token(token: str):
    """괄호 내 'A'/'B' + '합/불'만 추출 (특수문자 제거 후 판별)"""
    m = re.search(r"\((.*?)\)", token)
    if not m: return None
    raw = re.sub(r"[^A-Za-z가-힣]", "", m.group(1)).upper()
    course = "A" if "A" in raw else ("B" if "B" in raw else None)
    result = "합격" if "합" in raw else ("불합격" if "불" in raw else None)
    if course and result:
        return course, result
    return None

def split_and_clean_name_list(raw_names: list, valid_names: list):
    """
    1) correct_name_v3로 교정
    2) 괄호에서 코스 추출 → 기록
    3) 배정용 이름은 괄호 제거해서 반환
    """
    course_records, cleaned = [], []
    for token in raw_names:
        fixed = correct_name_v3(token, valid_names)
        info = extract_course_from_token(fixed)
        pure = re.sub(r"\(.*?\)", "", fixed).strip()
        if info:
            c, r = info
            course_records.append({"name": pure, "course": f"{c}코스", "result": r})
        cleaned.append(pure)
    return cleaned, course_records

# =====================================
# 파일 경로 / 기본 데이터
# =====================================
EMP_FILE   = "employee_list.json"
KEY_FILE   = "data_key.json"
GY_FILE    = "data_gyoyang.json"
SUD_FILE   = "data_sudong.json"
VEH1_FILE  = "veh1.json"
VEH2_FILE  = "veh2.json"
PREV_FILE  = "전일근무.json"
COURSE_FILE= "course_result.json"

default_key = ["권한솔","김남균","김면정","김성연","김지은","안유미","윤여헌","윤원실","이나래","이호석","조윤영","조정래"]
default_gy  = ["권한솔","김남균","김면정","김병욱","김성연","김주현","김지은","안유미","이호석","조정래"]
default_sd  = ["권한솔","김남균","김성연","김주현","이호석","조정래"]
default_veh1= ["2호 조정래","5호 권한솔","7호 김남균","8호 이호석","9호 김주현","10호 김성연"]
default_veh2= ["4호 김남균","5호 김병욱","6호 김지은","12호 안유미","14호 김면정","15호 이호석","17호 김성연","18호 권한솔","19호 김주현","22호 조정래"]
default_emp = sorted(list({*default_key, *default_gy, *default_sd, "김병욱","김주현"}))

# 로드
employee_list = load_json(EMP_FILE, default_emp)
key_order   = load_json(KEY_FILE,  default_key)
gyoyang_ord = load_json(GY_FILE,   default_gy)
sudong_ord  = load_json(SUD_FILE,  default_sd)
veh1_lines  = load_json(VEH1_FILE, default_veh1)
veh2_lines  = load_json(VEH2_FILE, default_veh2)

# -------------------------------------
# 사이드바: 전체 근무자 (숨김, 수정/저장)
# -------------------------------------
st.sidebar.header("근무 데이터 관리")
with st.sidebar.expander("👥 전체 근무자명단", expanded=False):
    emp_edit = st.text_area("전체 근무자", "\n".join(employee_list), height=180)
    if st.button("💾 근무자명단 저장"):
        new_list = [x.strip() for x in emp_edit.splitlines() if x.strip()]
        save_json(EMP_FILE, new_list)
        employee_list = new_list
        st.sidebar.success("전체 근무자 저장 완료")

# -------------------------------------
# 사이드바: 순번/차량표 (숨김, 수정/저장)
# -------------------------------------
with st.sidebar.expander("🔑 열쇠 순번", expanded=False):
    key_edit = st.text_area("열쇠 순번", "\n".join(key_order), height=140)
    if st.button("💾 열쇠 저장"):
        save_json(KEY_FILE, [x.strip() for x in key_edit.splitlines() if x.strip()])
        key_order = load_json(KEY_FILE, default_key)
        st.sidebar.success("열쇠 순번 저장 완료")

with st.sidebar.expander("📘 교양 순번", expanded=False):
    gy_edit = st.text_area("교양 순번", "\n".join(gyoyang_ord), height=140)
    if st.button("💾 교양 저장"):
        save_json(GY_FILE, [x.strip() for x in gy_edit.splitlines() if x.strip()])
        gyoyang_ord = load_json(GY_FILE, default_gy)
        st.sidebar.success("교양 순번 저장 완료")

with st.sidebar.expander("🧰 1종 수동 순번", expanded=False):
    sd_edit = st.text_area("1종 수동 순번", "\n".join(sudong_ord), height=140)
    if st.button("💾 1종 저장"):
        save_json(SUD_FILE, [x.strip() for x in sd_edit.splitlines() if x.strip()])
        sudong_ord = load_json(SUD_FILE, default_sd)
        st.sidebar.success("1종 순번 저장 완료")

with st.sidebar.expander("🚗 차량표 (1종/2종)", expanded=False):
    v1_edit = st.text_area("1종 수동 차량표", "\n".join(veh1_lines), height=110)
    v2_edit = st.text_area("2종 자동 차량표", "\n".join(veh2_lines), height=150)
    if st.button("💾 차량표 저장"):
        save_json(VEH1_FILE, [x.strip() for x in v1_edit.splitlines() if x.strip()])
        save_json(VEH2_FILE, [x.strip() for x in v2_edit.splitlines() if x.strip()])
        veh1_lines = load_json(VEH1_FILE, default_veh1)
        veh2_lines = load_json(VEH2_FILE, default_veh2)
        st.sidebar.success("차량표 저장 완료")

sudong_count = st.sidebar.radio("1종 수동 인원수", [1, 2], index=0)
repair_cars = [x.strip() for x in st.sidebar.text_input("정비 차량 (쉼표로 구분)", value="").split(",") if x.strip()]

# 전일값
prev_data = load_json(PREV_FILE, {"열쇠":"","교양_5교시":"","1종수동":""})
prev_key  = prev_data.get("열쇠","")
prev_gy5  = prev_data.get("교양_5교시","")
prev_sd   = prev_data.get("1종수동","")
st.sidebar.info(f"전일 기준 → 열쇠:{prev_key or '-'}, 교양5:{prev_gy5 or '-'}, 1종:{prev_sd or '-'}")

# =====================================
# GPT OCR: 근무자/제외자/조퇴/지각 (조퇴/지각은 필요시 확장)
# =====================================
def gpt_extract(img_bytes, want_early=False, want_late=False, want_excluded=False):
    b64 = base64.b64encode(img_bytes).decode()
    user = (
        "이 이미지는 운전면허시험 근무표입니다.\n"
        "1) 도로주행 근무자 이름만 names 배열로 추출하세요.\n"
        "2) 괄호(A-합, B-불 등)가 있으면 그대로 둔 원문을 names에 넣으세요.\n"
        "3) 휴가/교육/출장/공가/연가/연차/돌봄 등 표기된 이름은 excluded에 넣으세요.\n"
        + ("4) '조퇴:' 있으면 early_leave: [{name, time(숫자)}].\n" if want_early else "")
        + ("5) '10시 출근'/'외출:' 있으면 late_start: [{name, time(숫자)}].\n" if want_late else "")
        + 'JSON만 반환. 예: {"names":["김성연(A-합)","이호석(B-불)"], "excluded":["윤원실"]}'
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
            js.get("late_start", []) if want_late else [],
        )
    except Exception as e:
        st.error(f"OCR 실패: {e}")
        return [], [], [], []

# =====================================
# 1) 이미지 업로드 & OCR
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
    if not cycle: return None
    cyc_norm = [normalize_name(x) for x in cycle]
    last_norm = normalize_name(last)
    start = (cyc_norm.index(last_norm) + 1) % len(cycle) if last_norm in cyc_norm else 0
    for i in range(len(cycle)*2):
        cand = cycle[(start+i) % len(cycle)]
        if normalize_name(cand) in allowed_norms:
            return cand
    return None

def clipboard_copy_button(label, text):
    btn_id = f"btn_{abs(hash(label+text))}"
    st.markdown(
        f"""
        <button id="{btn_id}" style="background:#2563eb;color:white;border:none;
        padding:6px 12px;border-radius:8px;cursor:pointer;margin-top:6px;">{label}</button>
        <script>
        const b=document.getElementById("{btn_id}");
        b.onclick=()=>{{navigator.clipboard.writeText(`{text}`);b.innerText="✅ 복사됨!";setTimeout(()=>b.innerText="{label}",1500);}};
        </script>
        """, unsafe_allow_html=True
    )

# =====================================
# 3️⃣ 오전 배정
# =====================================
st.markdown("---")
st.markdown("## 3️⃣ 오전 근무 배정")

if st.button("📋 오전 배정 생성"):
    try:
        veh1_map = parse_vehicle_map(veh1_lines)
        veh2_map = parse_vehicle_map(veh2_lines)

        # 교정 + 괄호 분리 → 배정용 이름 / 코스기록
        cleaned_m, course_records = split_and_clean_name_list(m_list, employee_list)
        save_json(COURSE_FILE, course_records)

        excl_norms = {normalize_name(x) for x in excluded}
        m_norms = {normalize_name(x) for x in cleaned_m} - excl_norms

        # 🔑 열쇠
        key_filtered = [x for x in key_order if normalize_name(x) not in excl_norms]
        if key_filtered:
            knorms = [normalize_name(x) for x in key_filtered]
            pnorm = normalize_name(prev_key)
            today_key = key_filtered[(knorms.index(pnorm)+1)%len(key_filtered)] if pnorm in knorms else key_filtered[0]
        else:
            today_key = ""

        # 🧑‍🏫 오전 교양 1·2교시
        gy1 = pick_next_from_cycle(gyoyang_ord, prev_gy5, m_norms)
        gy1_norm = normalize_name(gy1) if gy1 else None
        gy2 = pick_next_from_cycle(gyoyang_ord, gy1 or prev_gy5, m_norms - ({gy1_norm} if gy1_norm else set()))

        # 🔧 1종 수동
        sud_m, last_pick = [], prev_sd
        for _ in range(sudong_count):
            cand = pick_next_from_cycle(sudong_ord, last_pick, m_norms - {normalize_name(x) for x in sud_m})
            if not cand: break
            sud_m.append(cand)
            last_pick = cand

        # 🚗 2종 자동 = 전체 - 1종
        sud_norms_m = {normalize_name(x) for x in sud_m}
        auto_m = [nm for nm in cleaned_m if normalize_name(nm) in (m_norms - sud_norms_m)]

        # 상태 저장(오전 대비/차량 비교용)
        st.session_state["today_key"] = today_key
        st.session_state["am_gy_base_for_pm"] = gy2 or gy1 or prev_gy5
        st.session_state["am_sud_base_for_pm"] = sud_m[-1] if sud_m else prev_sd
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

        # 🧭 코스점검(오전만)
        if course_records:
            lines.append("")
            lines.append("🧭 코스점검 결과:")
            for c in ["A","B"]:
                passed = [r["name"] for r in course_records if r["course"]==f"{c}코스" and r["result"]=="합격"]
                failed = [r["name"] for r in course_records if r["course"]==f"{c}코스" and r["result"]=="불합격"]
                if passed: lines.append(f" • {c}코스 합격: {', '.join(passed)}")
                if failed: lines.append(f" • {c}코스 불합격: {', '.join(failed)}")

        am_text = "\n".join(lines)
        st.markdown("### 📋 오전 결과")
        st.code(am_text, language="text")
        clipboard_copy_button("📋 결과 복사하기", am_text)

    except Exception as e:
        st.error(f"오전 오류: {e}")

# =====================================
# 4️⃣ 오후 배정
# =====================================
st.markdown("---")
st.markdown("## 4️⃣ 오후 근무 배정")
save_check = st.checkbox("이 결과를 전일근무.json으로 저장", value=True)

if st.button("📋 오후 배정 생성"):
    try:
        veh1_map = parse_vehicle_map(veh1_lines)
        veh2_map = parse_vehicle_map(veh2_lines)

        # 교정 + 괄호 제거
        cleaned_a, _ = split_and_clean_name_list(a_list, employee_list)

        excl_norms = {normalize_name(x) for x in excluded}
        a_norms = {normalize_name(x) for x in cleaned_a} - excl_norms

        # 🧑‍🏫 오후 교양 3·4·5
        gy_start = st.session_state.get("am_gy_base_for_pm", prev_gy5)
        used = set()
        gy3 = pick_next_from_cycle(gyoyang_ord, gy_start, a_norms)
        if gy3: used.add(normalize_name(gy3))
        gy4 = pick_next_from_cycle(gyoyang_ord, gy3 or gy_start, a_norms - used)
        if gy4: used.add(normalize_name(gy4))
        gy5 = pick_next_from_cycle(gyoyang_ord, gy4 or gy3 or gy_start, a_norms - used)

        # 🔧 오후 1종 수동 (교양과 중복 허용)
        sud_base = st.session_state.get("am_sud_base_for_pm", prev_sd)
        sud_a, last_pick = [], sud_base
        for _ in range(sudong_count):
            cand = pick_next_from_cycle(sudong_ord, last_pick, a_norms)
            if not cand: break
            sud_a.append(cand)
            last_pick = cand

        # 🚗 오후 2종 자동 = 전체 - 1종
        sud_norms_a = {normalize_name(x) for x in sud_a}
        auto_a = [nm for nm in cleaned_a if normalize_name(nm) in (a_norms - sud_norms_a)]

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

        # === 오전 대비 비교
        lines.append("")
        lines.append("오전 대비 비교:")
        am_drivers = st.session_state.get("am_driver_names", [])
        am_norms = {normalize_name(x) for x in am_drivers}
        pm_drivers = sud_a + auto_a
        pm_norms = {normalize_name(x) for x in pm_drivers}

        new_joiners = sorted([nm for nm in pm_drivers if normalize_name(nm) not in am_norms])
        missing = sorted([nm for nm in am_drivers if normalize_name(nm) not in pm_norms])

        if new_joiners: lines.append(" • 신규 투입: " + ", ".join(new_joiners))
        if missing:     lines.append(" • 빠진 인원: " + ", ".join(missing))
        if not new_joiners and not missing:
            lines.append(" • 변동 없음")

        # === 미배정 차량 (오전에 있었는데 오후에 없는 차량만)
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

        pm_text = "\n".join(lines)
        st.markdown("### 📋 오후 결과")
        st.code(pm_text, language="text")
        clipboard_copy_button("📋 결과 복사하기", pm_text)

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

