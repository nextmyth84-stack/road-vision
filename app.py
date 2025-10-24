# =====================================
# 도로주행 근무자동배정 v7.31a (완전본)
# =====================================
import streamlit as st
from openai import OpenAI
import base64, json, re, os, difflib

# 기본 설정
st.set_page_config(page_title="도로주행 근무자동배정", layout="wide")
st.markdown("<h3 style='text-align:center;'>🚗 도로주행 근무자동배정 v7.31a</h3>", unsafe_allow_html=True)

# OpenAI 초기화
try:
    client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
except Exception:
    st.error("⚠️ OPENAI_API_KEY 설정 필요")
    st.stop()
MODEL_NAME = "gpt-4o"

# ===============================
# JSON 파일 관리
# ===============================
def load_json(path, default=None):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except:
        pass
    return default if default is not None else []

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.warning(f"저장 실패: {e}")

# ===============================
# 파일 경로
# ===============================
PREV_FILE = "전일근무.json"
files = {
    "열쇠": "열쇠순번.json",
    "교양": "교양순번.json",
    "1종": "1종순번.json",
    "veh1": "1종차량.json",
    "veh2": "2종차량.json",
    "employees": "전체근무자.json"
}

# ===============================
# 전일 불러오기
# ===============================
prev_key, prev_gy5, prev_sud = "", "", ""
if os.path.exists(PREV_FILE):
    try:
        js = load_json(PREV_FILE)
        prev_key = js.get("열쇠", "")
        prev_gy5 = js.get("교양_5교시", "")
        prev_sud = js.get("1종수동", "")
        st.info(f"전일 → 열쇠:{prev_key or '-'}, 교양5:{prev_gy5 or '-'}, 1종:{prev_sud or '-'}")
    except Exception as e:
        st.warning(f"전일근무.json 읽기 실패: {e}")

# ===============================
# 유틸 함수
# ===============================
def normalize_name(s):
    return re.sub(r"[^가-힣]", "", re.sub(r"\(.*?\)", "", s or ""))

def pick_next_from_cycle(cycle, last, allowed_norms:set):
    if not cycle: return None
    cycle_norm = [normalize_name(x) for x in cycle]
    last_norm = normalize_name(last)
    start = 0
    if last_norm in cycle_norm:
        start = (cycle_norm.index(last_norm) + 1) % len(cycle)
    for i in range(len(cycle)*2):
        cand = cycle[(start + i) % len(cycle)]
        if normalize_name(cand) in allowed_norms:
            return cand
    return None

def get_vehicle(name, veh_map):
    n = normalize_name(name)
    for k,v in veh_map.items():
        if normalize_name(v)==n:
            return k
    return ""

def mark_car(car, repairs):
    return f"{car}{' (정비)' if car in repairs else ''}" if car else ""

def can_attend_period_morning(name, period, late_list):
    """10시 출근자는 1교시 불가"""
    tmap={1:9.0,2:10.5}
    for e in late_list:
        if normalize_name(e.get("name",""))==normalize_name(name):
            try:t=float(e.get("time",99))
            except:t=99
            return t<=tmap[period]
    return True

def can_attend_period_afternoon(name, period, early_list):
    """14.5시 이전 조퇴자는 해당 교시 불가"""
    tmap={3:13.0,4:14.5,5:16.0}
    for e in early_list:
        if normalize_name(e.get("name",""))==normalize_name(name):
            try:t=float(e.get("time",99))
            except:t=99
            return t>tmap[period]
    return True
# =====================================
# OCR JSON 파싱 안정화 + 오타 교정 알고리즘
# =====================================

def _extract_first_json_object(text: str):
    """GPT 응답에서 첫 번째 완전한 JSON 오브젝트 추출"""
    if not text:
        return None
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{": depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i+1]
    return None


def correct_name_v2(name: str, all_names: list[str], cutoff=0.6):
    """근무자명 교정: OCR 오타를 전체근무자 기준으로 보정"""
    import difflib
    n = normalize_name(name)
    if not n or not all_names:
        return name
    all_norms = {normalize_name(x): x for x in all_names}
    close = difflib.get_close_matches(n, all_norms.keys(), n=1, cutoff=cutoff)
    if close:
        return all_norms[close[0]]
    return name


def gpt_extract(img_bytes, want_early=False, want_late=False, want_excluded=False):
    """OCR 결과: names, course_records, excluded, early, late"""
    b64 = base64.b64encode(img_bytes).decode()
    prompt = (
        "이 이미지는 운전면허시험 근무표입니다.\n"
        "1) '학과','기능','PC','초소' 등은 제외하고 도로주행 근무자만 추출.\n"
        "2) 괄호 안의 A/B와 합/불은 코스점검 결과임.\n"
        "3) '휴가','출장','연차','공가','돌봄','연가' 등의 단어가 들어간 이름은 excluded로 추출.\n"
        "4) '조퇴','외출','10시 출근' 등 시간은 숫자로 표시.\n"
        "JSON만 출력, 설명 금지.\n"
        "예시: {\"names\": [\"김성연(B합)\"], \"excluded\": [\"안유미\"], "
        "\"early_leave\": [{\"name\":\"김병욱\",\"time\":14.5}], "
        "\"late_start\": [{\"name\":\"김지은\",\"time\":10}]}"
    )
    try:
        res = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "근무표를 JSON으로만 변환"},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]}
            ]
        )
        raw = (res.choices[0].message.content or "").strip()

        # JSON 안정 추출
        json_str = _extract_first_json_object(raw)
        if not json_str:
            m = re.search(r"\{.*\}", raw, re.S)
            json_str = m.group(0) if m else "{}"
        try:
            js = json.loads(json_str)
        except json.JSONDecodeError:
            js = json.loads(re.sub(r",\s*}\s*$", "}", json_str))

        if not isinstance(js, dict):
            js = {}

        raw_names = js.get("names", []) or []
        excluded = js.get("excluded", []) if want_excluded else []
        early = js.get("early_leave", []) if want_early else []
        late = js.get("late_start", []) if want_late else []

        names, course_records = [], []
        for n in raw_names:
            m2 = re.search(r"([가-힣]+)\s*\(([^)]*)\)", n)
            if m2:
                nm = m2.group(1).strip()
                det = re.sub(r"[^A-Za-z가-힣]", "", m2.group(2)).upper()
                crs = "A" if "A" in det else ("B" if "B" in det else None)
                res_txt = "합격" if "합" in det else ("불합격" if "불" in det else None)
                if crs and res_txt:
                    course_records.append({"name": nm, "course": f"{crs}코스", "result": res_txt})
                names.append(nm)
            else:
                names.append(n.strip())

        # 시간 숫자형 변환
        def to_float(v):
            try: return float(v)
            except: return None
        for e in early: e["time"] = to_float(e.get("time"))
        for l in late:  l["time"] = to_float(l.get("time"))

        return names, course_records, excluded, early, late

    except Exception as e:
        st.error(f"OCR 실패: {e}")
        return [], [], [], [], []
# =====================================
# 사이드바 — JSON 기반 순번/차량/근무자 관리 (토글 확장)
# =====================================
st.sidebar.header("⚙️ 설정 및 데이터 관리")

# 파일 로드
key_order   = load_json(files["열쇠"], ["권한솔","김남균","김면정","김성연","김지은","안유미","윤여헌","윤원실","이나래","이호석","조윤영","조정래"])
gyoyang_order = load_json(files["교양"], ["권한솔","김남균","김면정","김병욱","김성연","김주현","김지은","안유미","이호석","조정래"])
sudong_order  = load_json(files["1종"], ["권한솔","김남균","김성연","김주현","이호석","조정래"])
veh1_map = load_json(files["veh1"], {"2호":"조정래","5호":"권한솔","7호":"김남균","8호":"이호석","9호":"김주현","10호":"김성연"})
veh2_map = load_json(files["veh2"], {"4호":"김남균","5호":"김병욱","6호":"김지은","12호":"안유미","14호":"김면정","15호":"이호석","17호":"김성연","18호":"권한솔","19호":"김주현","22호":"조정래"})
all_employees = load_json(files["employees"], ["권한솔","김남균","김면정","김성연","김지은","안유미","윤여헌","윤원실","이나래","이호석","조윤영","조정래","김병욱","김주현"])

# 🔽 토글형 편집 UI
with st.sidebar.expander("🧭 순번표 (열쇠 / 교양 / 1종 수동)", expanded=False):
    col1, col2, col3 = st.columns(3)
    with col1:
        new_key = st.text_area("열쇠 순번", "\n".join(key_order), height=180)
    with col2:
        new_gyo = st.text_area("교양 순번", "\n".join(gyoyang_order), height=180)
    with col3:
        new_sud = st.text_area("1종 수동 순번", "\n".join(sudong_order), height=180)
    if st.button("💾 순번표 저장"):
        save_json(files["열쇠"], [x.strip() for x in new_key.splitlines() if x.strip()])
        save_json(files["교양"], [x.strip() for x in new_gyo.splitlines() if x.strip()])
        save_json(files["1종"], [x.strip() for x in new_sud.splitlines() if x.strip()])
        st.success("✅ 순번표 저장 완료")

# 차량표
with st.sidebar.expander("🚗 차량표 관리", expanded=False):
    c1, c2 = st.columns(2)
    with c1:
        veh1_text = "\n".join([f"{k} {v}" for k,v in veh1_map.items()])
        new_v1 = st.text_area("1종 수동 차량표", veh1_text, height=150)
    with c2:
        veh2_text = "\n".join([f"{k} {v}" for k,v in veh2_map.items()])
        new_v2 = st.text_area("2종 자동 차량표", veh2_text, height=150)
    if st.button("💾 차량표 저장"):
        def parse_map(t):
            m = {}
            for line in t.splitlines():
                p=line.strip().split()
                if len(p)>=2: m[p[0]]=p[1]
            return m
        save_json(files["veh1"], parse_map(new_v1))
        save_json(files["veh2"], parse_map(new_v2))
        st.success("✅ 차량표 저장 완료")

# 전체 근무자 명단
with st.sidebar.expander("👥 전체 근무자 관리", expanded=False):
    emp_text = "\n".join(all_employees)
    new_emp = st.text_area("근무자 명단", emp_text, height=220)
    if st.button("💾 근무자 저장"):
        save_json(files["employees"], [x.strip() for x in new_emp.splitlines() if x.strip()])
        st.success("✅ 근무자 명단 저장 완료")

# 옵션 설정
sudong_count = st.sidebar.radio("1종 수동 인원수", [1,2], index=0)
repair_cars = [x.strip() for x in st.sidebar.text_input("정비 차량 (쉼표로 구분)").split(",") if x.strip()]

# 전일값 수정
st.sidebar.markdown("---")
st.sidebar.subheader("🗓 전일값 확인/수정")
prev_key = st.sidebar.text_input("전일 열쇠", value=prev_key)
prev_gy5 = st.sidebar.text_input("전일 교양5", value=prev_gy5)
prev_sud = st.sidebar.text_input("전일 1종수동", value=prev_sud)
if st.sidebar.button("💾 전일값 저장"):
    save_json(PREV_FILE, {"열쇠": prev_key, "교양_5교시": prev_gy5, "1종수동": prev_sud})
    st.sidebar.success("✅ 전일값 저장 완료")
# =====================================
# 1️⃣ OCR 인식 (오전/오후/근무제외자 자동)
# =====================================
st.markdown("<h4 style='font-size:18px;'>📸 근무표 이미지 업로드</h4>", unsafe_allow_html=True)
c1, c2, c3 = st.columns(3)
with c1:
    m_file = st.file_uploader("오전 근무표", type=["jpg","jpeg","png"])
with c2:
    a_file = st.file_uploader("오후 근무표", type=["jpg","jpeg","png"])
with c3:
    ex_file = st.file_uploader("근무제외자 포함 이미지(상단)", type=["jpg","jpeg","png"])

b1, b2, b3 = st.columns(3)
with b1:
    if st.button("🧠 오전 인식"):
        if not m_file:
            st.warning("오전 이미지를 업로드하세요.")
        else:
            with st.spinner("오전 GPT 분석 중..."):
                m_names, course_records, _, _, late = gpt_extract(m_file.read(), want_late=True)
                # 이름 교정
                m_names = [correct_name_v2(n, all_employees, cutoff=0.5) for n in m_names]
                st.session_state["m_names_raw"] = m_names
                st.session_state["late_start"] = late
                st.session_state["m_course_records"] = course_records
                st.success(f"✅ 오전 인식 완료: {len(m_names)}명 / 외출 {len(late)}명")
            st.rerun()

with b2:
    if st.button("🧠 오후 인식"):
        if not a_file:
            st.warning("오후 이미지를 업로드하세요.")
        else:
            with st.spinner("오후 GPT 분석 중..."):
                a_names, _, _, early, _ = gpt_extract(a_file.read(), want_early=True)
                a_names = [correct_name_v2(n, all_employees, cutoff=0.5) for n in a_names]
                st.session_state["a_names_raw"] = a_names
                st.session_state["early_leave"] = early
                st.success(f"✅ 오후 인식 완료: {len(a_names)}명 / 조퇴 {len(early)}명")
            st.rerun()

with b3:
    if st.button("🧠 근무제외자 인식"):
        if not ex_file:
            st.warning("근무제외자 이미지 업로드 필요")
        else:
            with st.spinner("근무제외자 GPT 분석 중..."):
                _, _, excluded, _, _ = gpt_extract(ex_file.read(), want_excluded=True)
                excluded = [correct_name_v2(n, all_employees) for n in excluded]
                st.session_state["excluded_auto"] = excluded
                st.success(f"✅ 근무제외자 {len(excluded)}명 인식됨")
            st.rerun()

# =====================================
# 2️⃣ 인식 결과 수정 (스크롤 지원)
# =====================================
st.markdown("<h4 style='font-size:18px;'>📝 인식 결과 확인 / 수정</h4>", unsafe_allow_html=True)
col1, col2, col3 = st.columns(3)
with col1:
    excl = "\n".join(st.session_state.get("excluded_auto", []))
    excluded_text = st.text_area("근무 제외자", excl, height=160)
with col2:
    morning_text = "\n".join(st.session_state.get("m_names_raw", []))
    morning_area = st.text_area("🌅 오전 근무자 (수정 가능)", morning_text, height=160)
with col3:
    afternoon_text = "\n".join(st.session_state.get("a_names_raw", []))
    afternoon_area = st.text_area("🌇 오후 근무자 (수정 가능)", afternoon_text, height=160)

excluded = {normalize_name(x) for x in excluded_text.splitlines() if x.strip()}
m_list = [x.strip() for x in morning_area.splitlines() if x.strip()]
a_list = [x.strip() for x in afternoon_area.splitlines() if x.strip()]

m_norms = {normalize_name(x) for x in m_list} - excluded
a_norms = {normalize_name(x) for x in a_list} - excluded
late_start = st.session_state.get("late_start", [])
early_leave = st.session_state.get("early_leave", [])
course_records = st.session_state.get("m_course_records", [])

# =====================================
# 3️⃣ 오전 근무 배정
# =====================================
st.markdown("<h4 style='font-size:18px;'>📋 오전 근무 배정</h4>", unsafe_allow_html=True)
if st.button("✅ 오전 배정 생성"):
    try:
        key_filtered = [x for x in key_order if normalize_name(x) not in excluded]
        if key_filtered:
            prev_norm = normalize_name(prev_key)
            if prev_norm in [normalize_name(x) for x in key_filtered]:
                idx = ([normalize_name(x) for x in key_filtered].index(prev_norm) + 1) % len(key_filtered)
                today_key = key_filtered[idx]
            else:
                today_key = key_filtered[0]
        else:
            today_key = ""
        st.session_state["today_key"] = today_key

        gy1 = pick_next_from_cycle(gyoyang_order, prev_gy5, m_norms)
        if gy1 and not can_attend_period_morning(gy1, 1, late_start):
            gy1 = pick_next_from_cycle(gyoyang_order, gy1, m_norms)
        gy1_norm = normalize_name(gy1) if gy1 else None
        gy2 = pick_next_from_cycle(gyoyang_order, gy1 or prev_gy5, m_norms - ({gy1_norm} if gy1_norm else set()))
        st.session_state["gy_base_pm"] = gy2 if gy2 else prev_gy5

        # 1종 수동
        sud_m, last = [], prev_sud
        for _ in range(sudong_count):
            pick = pick_next_from_cycle(sudong_order, last, m_norms - {normalize_name(x) for x in sud_m})
            if not pick: break
            sud_m.append(pick)
            last = pick
        st.session_state["sud_base_pm"] = sud_m[-1] if sud_m else prev_sud

        sud_norms = {normalize_name(x) for x in sud_m}
        auto_m = [x for x in m_list if normalize_name(x) in (m_norms - sud_norms)]

        # === 출력 ===
        lines = []
        if today_key: lines.append(f"열쇠: {today_key}")
        if gy1: lines.append(f"1교시: {gy1}")
        if gy2: lines.append(f"2교시: {gy2}")
        for nm in sud_m:
            lines.append(f"1종수동: {nm} {mark_car(get_vehicle(nm, veh1_map), repair_cars)}")
        if not sud_m and sudong_count >= 1:
            lines.append("1종수동: (배정자 없음)")
        if auto_m:
            lines.append("2종자동:")
            for nm in auto_m:
                lines.append(f" • {nm} {mark_car(get_vehicle(nm, veh2_map), repair_cars)}")

        # 코스점검결과
        if course_records:
            lines.append("코스점검 결과:")
            for rec in course_records:
                lines.append(f" • {rec['name']} — {rec['course']} {rec['result']}")

        # 결과 표시 + 복사
        result_text = "\n".join(lines)
        st.markdown("<h5 style='font-size:16px;'>오전 결과</h5>", unsafe_allow_html=True)
        st.code(result_text, language="text")
        st.markdown(f"""
            <button onclick="navigator.clipboard.writeText(`{result_text}`)">
            📋 결과 복사하기
            </button>
        """, unsafe_allow_html=True)

    except Exception as e:
        st.error(f"오전 오류: {e}")
# =====================================
# 4️⃣ 오후 근무 배정
# =====================================
st.markdown("<h4 style='font-size:18px;'>🌇 오후 근무 배정</h4>", unsafe_allow_html=True)
save_check = st.checkbox("이 결과를 전일 기준으로 저장", value=True)

if st.button("✅ 오후 배정 생성"):
    try:
        today_key = st.session_state.get("today_key", prev_key)
        gy_start = st.session_state.get("gy_base_pm", prev_gy5)
        if not gy_start: gy_start = gyoyang_order[0] if gyoyang_order else None

        # 교양(3~5교시)
        used, gy3, gy4, gy5 = set(), None, None, None
        last = gy_start
        for p in [3,4,5]:
            while True:
                pick = pick_next_from_cycle(gyoyang_order, last, a_norms - used)
                if not pick: break
                last = pick
                if can_attend_period_afternoon(pick, p, early_leave):
                    if p == 3: gy3 = pick
                    elif p == 4: gy4 = pick
                    else: gy5 = pick
                    used.add(normalize_name(pick))
                    break

        # 1종 수동
        sud_a, last = [], st.session_state.get("sud_base_pm", prev_sud)
        for _ in range(sudong_count):
            pick = pick_next_from_cycle(sudong_order, last, a_norms)
            if not pick: break
            sud_a.append(pick)
            last = pick
        used.update(normalize_name(x) for x in sud_a)

        # 2종 자동 (1종 제외)
        sud_norms = {normalize_name(x) for x in sud_a}
        auto_a = [x for x in a_list if normalize_name(x) in (a_norms - sud_norms)]

        # === 출력 ===
        lines = []
        if today_key: lines.append(f"열쇠: {today_key}")
        if gy3: lines.append(f"3교시: {gy3}")
        if gy4: lines.append(f"4교시: {gy4}")
        if gy5: lines.append(f"5교시: {gy5}")
        for nm in sud_a:
            lines.append(f"1종수동: {nm} {mark_car(get_vehicle(nm, veh1_map), repair_cars)}")
        if auto_a:
            lines.append("2종자동:")
            for nm in auto_a:
                lines.append(f" • {nm} {mark_car(get_vehicle(nm, veh2_map), repair_cars)}")

        # === 오전 대비 비교 ===
        lines.append("오전 대비 비교:")
        morning_auto = set(st.session_state.get("m_names_raw", []))
        afternoon_auto = set(a_list)
        afternoon_sud = {normalize_name(x) for x in sud_a}

        added = sorted(list(afternoon_auto - morning_auto))
        missing = sorted([m for m in morning_auto if normalize_name(m) not in afternoon_sud and m not in afternoon_auto])

        if added: lines.append(" • 추가 인원: " + ", ".join(added))
        if missing: lines.append(" • 빠진 인원: " + ", ".join(missing))

        # === 미배정 차량 ===
        m_cars_1 = {get_vehicle(x, veh1_map) for x in st.session_state.get("m_names_raw", []) if get_vehicle(x, veh1_map)}
        m_cars_2 = {get_vehicle(x, veh2_map) for x in st.session_state.get("m_names_raw", []) if get_vehicle(x, veh2_map)}
        a_cars_1 = {get_vehicle(x, veh1_map) for x in sud_a if get_vehicle(x, veh1_map)}
        a_cars_2 = {get_vehicle(x, veh2_map) for x in auto_a if get_vehicle(x, veh2_map)}

        unassigned_1 = sorted([c for c in m_cars_1 if c not in a_cars_1])
        unassigned_2 = sorted([c for c in m_cars_2 if c not in a_cars_2])

        if unassigned_1 or unassigned_2:
            lines.append("미배정 차량:")
            if unassigned_1:
                lines.append(" [1종 수동]")
                for c in unassigned_1: lines.append(f"  • {c} 마감")
            if unassigned_2:
                lines.append(" [2종 자동]")
                for c in unassigned_2: lines.append(f"  • {c} 마감")

        # === 출력 및 복사 버튼 ===
        result_text = "\n".join(lines)
        st.markdown("<h5 style='font-size:16px;'>오후 결과</h5>", unsafe_allow_html=True)
        st.code(result_text, language="text")
        st.markdown(f"""
            <button onclick="navigator.clipboard.writeText(`{result_text}`)">
            📋 결과 복사하기
            </button>
        """, unsafe_allow_html=True)

        # === 전일 저장 ===
        if save_check:
            data = {
                "열쇠": today_key,
                "교양_5교시": gy5 or gy4 or gy3 or prev_gy5,
                "1종수동": sud_a[-1] if sud_a else prev_sud
            }
            save_json(PREV_FILE, data)
            st.success("✅ 전일근무.json 업데이트 완료")

    except Exception as e:
        st.error(f"오후 오류: {e}")
