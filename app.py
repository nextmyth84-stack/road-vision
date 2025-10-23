import streamlit as st
from openai import OpenAI
import base64, re, json, os

# -------------------------
# 페이지 설정
# -------------------------
st.set_page_config(page_title="도로주행 근무자동배정", layout="wide")
st.markdown("<h2 style='font-size:22px;'>🚗 도로주행 근무자동배정 (GPT OCR + 순번/차량)</h2>", unsafe_allow_html=True)

# -------------------------
# OpenAI 초기화
# -------------------------
try:
    client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
except Exception as e:
    st.error("⚠️ OPENAI_API_KEY 설정 확인 필요.")
    st.stop()

# -------------------------
# OCR 프롬프트: 도로주행 근무자만 추출
# -------------------------
def gpt_extract_names_from_image(image_bytes):
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    system = (
        "당신은 이미지 표에서 이름을 추출하는 전문가입니다. "
        "결과는 반드시 JSON 형식으로 반환해야 하며, 불필요한 설명은 금지합니다."
    )
    user = (
        "이미지에서 '학과', '기능장', '초소'를 제외한 도로주행 근무자 이름만 추출하세요.\n"
        "이름 옆 괄호(A-합, B-불 등)는 그대로 유지하세요.\n"
        "출력은 반드시 JSON 형식으로:\n"
        '{"names": ["김남균(A-불)", "김주현(B-합)"]}'
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type":"text","text": user},
                    {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}
                ]}
            ],
            max_tokens=1000
        )
        raw = resp.choices[0].message.content
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        js = json.loads(m.group(0)) if m else {}
        names = js.get("names", [])
        return names
    except Exception as e:
        st.error(f"OCR 실패: {e}")
        return []

# -------------------------
# 유틸: 정규화 / 매칭용
# -------------------------
def normalize_name(s: str) -> str:
    """괄호, 공백, 기호 제거 후 한글만 남김"""
    if not isinstance(s, str): return ""
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"[-_·•‧‵′]", "", s)
    s = re.sub(r"\s+", "", s)
    return re.sub(r"[^\uAC00-\uD7A3]", "", s)

def build_present_map(name_list):
    """입력된 근무자 리스트를 {정규화된이름: 원본이름} 형태로 변환"""
    m = {}
    for x in name_list:
        k = normalize_name(x)
        if k and k not in m:
            m[k] = x
    return m

def get_vehicle(name, veh_map):
    """차량 매칭 (정규화 기준으로 비교)"""
    key = normalize_name(name)
    for k, v in veh_map.items():
        if normalize_name(k) == key:
            return v
    return ""

def pick_next_from_cycle(cycle, last, allowed_norms: set):
    """순번표에서 last 다음으로 allowed_norms(정규화 이름)에 속한 첫 사람 반환"""
    if not cycle: return None
    start_idx = 0 if not last or last not in cycle else (cycle.index(last) + 1) % len(cycle)
    for i in range(len(cycle)*2):
        cand = cycle[(start_idx + i) % len(cycle)]
        if normalize_name(cand) in allowed_norms:
            return cand
    return None

# -------------------------
# 오전 근무 배정 (예시 구조)
# -------------------------
st.markdown("<h4 style='font-size:18px;'>1️⃣ 오전 근무 배정 생성</h4>", unsafe_allow_html=True)

# 예시 입력 (실제는 이미지 OCR 결과로 대체)
morning_list = ["김면정(A-합)", "김성연(B-불)", "이호석", "조정래"]
excluded_set = ["안유미(휴가)"]

key_order = ["권한솔", "김남균", "김면정", "김성연", "김지은", "안유미", "조정래"]
gyoyang_order = ["권한솔", "김남균", "김면정", "김성연", "이호석", "조정래"]
sudong_order = ["김남균", "김성연", "조정래"]
veh1 = {"김남균": "7호", "김성연": "10호"}
veh2 = {"김면정": "14호", "이호석": "15호", "조정래": "22호"}

# 순번 계산
present_map = build_present_map(morning_list)
excluded_norm = {normalize_name(x) for x in excluded_set}
present_norms = set(present_map.keys()) - excluded_norm

prev_key = "조정래"
prev_gyoyang5 = "김성연"
prev_sudong = "김성연"
sudong_count = 1

# 열쇠
key_cycle_filtered = [x for x in key_order if normalize_name(x) not in excluded_norm]
today_key = key_cycle_filtered[(key_cycle_filtered.index(prev_key)+1)%len(key_cycle_filtered)]

# 교양
gy1_name = pick_next_from_cycle(gyoyang_order, prev_gyoyang5, present_norms)
gy1 = present_map.get(normalize_name(gy1_name), "-") if gy1_name else "-"
gy2_name = pick_next_from_cycle(gyoyang_order, gy1_name, present_norms - {normalize_name(gy1)})
gy2 = present_map.get(normalize_name(gy2_name), "-") if gy2_name else "-"

# 1종 수동
sudong_list = []
last = prev_sudong
for _ in range(sudong_count):
    pick = pick_next_from_cycle(sudong_order, last, present_norms)
    if not pick: break
    orig = present_map.get(normalize_name(pick))
    if orig:
        sudong_list.append(orig)
    last = pick

# 2종 자동
sud_norms = {normalize_name(x) for x in sudong_list}
auto_list = [x for x in morning_list if normalize_name(x) not in sud_norms]

# 출력
st.markdown("<h4 style='font-size:16px;'>📋 오전 결과</h4>", unsafe_allow_html=True)
lines = [
    f"열쇠: {today_key}",
    f"교양 1교시: {gy1}",
    f"교양 2교시: {gy2}"
]
if sudong_list:
    for nm in sudong_list:
        car = get_vehicle(nm, veh1)
        lines.append(f"1종수동: {nm} {car}")
else:
    lines.append("1종수동: (없음)")

lines.append("2종 자동:")
for nm in auto_list:
    car = get_vehicle(nm, veh2)
    lines.append(f" - {nm} {car}")

st.code("\n".join(lines), language="text")
# -------------------------
# 오후 근무 배정
# -------------------------
st.markdown("<h4 style='font-size:18px;'>2️⃣ 오후 근무 배정 생성</h4>", unsafe_allow_html=True)

# 예시 입력 (오전과 별도로 OCR 결과에서 가져옴)
afternoon_list = ["김면정(A-합)", "김성연(B-불)", "이호석", "조정래", "김병욱(조퇴14시)"]

# -------------------------
# 조퇴자 파싱
# -------------------------
def parse_early_leave(names):
    result = {}
    for n in names:
        m = re.search(r"조퇴\s*:?[\s]*(\d{1,2})시", n)
        if m:
            hour = int(m.group(1))
            result[normalize_name(n)] = hour
    return result

early_leave = parse_early_leave(afternoon_list)

def can_attend_period(name, period):
    """조퇴 시간 기준으로 교시 참여 가능여부 확인"""
    norm = normalize_name(name)
    if norm not in early_leave: 
        return True
    leave_hour = early_leave[norm]
    # 3교시=13시, 4교시=14시30분, 5교시=16시
    if period == 3:
        return leave_hour > 13
    elif period == 4:
        return leave_hour > 14
    elif period == 5:
        return leave_hour > 15
    return True

# -------------------------
# 교양 / 수동 / 자동 오후 배정
# -------------------------
present_map_a = build_present_map(afternoon_list)
present_norms_a = set(present_map_a.keys())
excluded_norm = {normalize_name(x) for x in excluded_set}
present_norms_a -= excluded_norm

# 오후 교양 3~5교시
gy_start = gy2_name if 'gy2_name' in locals() and gy2_name else prev_gyoyang5
used = set()
gy3 = gy4 = gy5 = None
last_pick = gy_start
for period in [3,4,5]:
    pick = pick_next_from_cycle(gyoyang_order, last_pick, present_norms_a - used)
    if not pick: continue
    cand_orig = present_map_a.get(normalize_name(pick))
    if cand_orig and can_attend_period(cand_orig, period):
        if period == 3: gy3 = cand_orig
        if period == 4: gy4 = cand_orig
        if period == 5: gy5 = cand_orig
        used.add(normalize_name(cand_orig))
    last_pick = pick

# 1종 수동(오후)
sudong_list_a = []
last = prev_sudong
for _ in range(1):
    pick = pick_next_from_cycle(sudong_order, last, present_norms_a)
    if not pick: break
    orig = present_map_a.get(normalize_name(pick))
    if orig:
        sudong_list_a.append(orig)
    last = pick

# 2종 자동
sud_norms_a = {normalize_name(x) for x in sudong_list_a}
auto_list_a = [x for x in afternoon_list if normalize_name(x) not in sud_norms_a]

# -------------------------
# 출력
# -------------------------
st.markdown("<h4 style='font-size:16px;'>📋 오후 결과</h4>", unsafe_allow_html=True)
lines = [
    f"열쇠: {today_key}",
    f"교양 3교시: {gy3 if gy3 else '-'}",
    f"교양 4교시: {gy4 if gy4 else '-'}",
    f"교양 5교시: {gy5 if gy5 else '-'}"
]
if sudong_list_a:
    for nm in sudong_list_a:
        car = get_vehicle(nm, veh1)
        lines.append(f"1종수동: {nm} {car}")
else:
    lines.append("1종수동: (없음)")

lines.append("2종 자동:")
for nm in auto_list_a:
    car = get_vehicle(nm, veh2)
    lines.append(f" - {nm} {car}")

st.code("\n".join(lines), language="text")

# -------------------------
# 전일 근무 수정 / 저장
# -------------------------
st.markdown("<h4 style='font-size:18px;'>3️⃣ 전일 근무 수정 / 저장</h4>", unsafe_allow_html=True)
PREV_FILE = "전일근무.json"
prev_key_in, prev_gy5_in, prev_sud_in = prev_key, prev_gyoyang5, prev_sudong

# 기존 json 불러오기
if os.path.exists(PREV_FILE):
    try:
        with open(PREV_FILE, "r", encoding="utf-8") as f:
            prevdata = json.load(f)
            prev_key_in = prevdata.get("열쇠", prev_key_in)
            prev_gy5_in = prevdata.get("교양_5교시", prev_gy5_in)
            prev_sud_in = prevdata.get("1종수동", prev_sud_in)
    except Exception as e:
        st.warning(f"전일근무.json 불러오기 실패: {e}")

col1, col2, col3 = st.columns(3)
with col1:
    new_key = st.text_input("전일 열쇠", value=prev_key_in)
with col2:
    new_gy5 = st.text_input("전일 교양 5교시", value=prev_gy5_in)
with col3:
    new_sud = st.text_input("전일 1종 수동", value=prev_sud_in)

if st.button("💾 수정내용 저장"):
    try:
        with open(PREV_FILE, "w", encoding="utf-8") as f:
            json.dump({"열쇠": new_key, "교양_5교시": new_gy5, "1종수동": new_sud},
                      f, ensure_ascii=False, indent=2)
        st.success("전일근무.json 저장 완료 ✅")
    except Exception as e:
        st.error(f"저장 실패: {e}")
