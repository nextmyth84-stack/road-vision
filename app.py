import streamlit as st
from openai import OpenAI
import base64, re, json, os

# -------------------------
# 페이지 설정
# -------------------------
st.set_page_config(page_title="도로주행 근무자동배정", layout="wide")
st.markdown(
    "<h3 style='text-align:center; font-size:22px; margin-bottom:10px;'>🚗 도로주행 근무자동배정 (GPT OCR + 순번/차량/조퇴/저장 완전본)</h3>",
    unsafe_allow_html=True
)

# -------------------------
# OpenAI 초기화
# -------------------------
try:
    client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
except Exception:
    st.error("⚠️ OPENAI_API_KEY가 설정되어 있지 않습니다.")
    st.stop()

MODEL_NAME = "gpt-4o"
PREV_FILE = "전일근무.json"

# -------------------------
# 전일 기준 불러오기
# -------------------------
prev_key = ""
prev_gyoyang5 = ""
prev_sudong = ""

if os.path.exists(PREV_FILE):
    try:
        with open(PREV_FILE, "r", encoding="utf-8") as f:
            prev = json.load(f)
        prev_key = prev.get("열쇠", "")
        prev_gyoyang5 = prev.get("교양_5교시", "")
        prev_sudong = prev.get("1종수동", "")
        st.info(f"✅ 전일근무.json 자동 불러옴 → 열쇠:{prev_key}, 교양5:{prev_gyoyang5}, 수동:{prev_sudong}")
    except Exception as e:
        st.warning(f"전일근무.json 불러오기 실패: {e}")

# -------------------------
# 사이드바
# -------------------------
st.sidebar.header("순번 및 차량표 설정")

def_list = lambda t: [x.strip() for x in t.splitlines() if x.strip()]

default_key_order = """권한솔
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
default_gyoyang_order = """권한솔
김남균
김면정
김병욱
김성연
김주현
김지은
안유미
이호석
조정래"""
default_sudong_order = """권한솔
김남균
김성연
김주현
이호석
조정래"""
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

key_order = def_list(st.sidebar.text_area("열쇠 순번", default_key_order, height=160))
gyoyang_order = def_list(st.sidebar.text_area("교양 순번", default_gyoyang_order, height=160))
sudong_order = def_list(st.sidebar.text_area("1종 수동 순번", default_sudong_order, height=160))

def parse_vehicle_map(text):
    m = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            car = parts[0]; name = " ".join(parts[1:])
            m[name] = car
    return m

veh1 = parse_vehicle_map(st.sidebar.text_area("1종 수동 차량표", default_cha1, height=140))
veh2 = parse_vehicle_map(st.sidebar.text_area("2종 자동 차량표", default_cha2, height=200))

sudong_count = st.sidebar.radio("1종 수동 인원수", [1, 2], index=0)
absent_text = st.sidebar.text_area("휴가/교육자 (한 줄에 한 명)", height=100, value="")
repair_cars_text = st.sidebar.text_input("정비 차량 (쉼표로 구분, 예: 12호,6호)", value="")
excluded_set = set([x.strip() for x in absent_text.splitlines() if x.strip()])
repair_cars = [x.strip() for x in repair_cars_text.split(",") if x.strip()]

# -------------------------
# 🔄 전일근무 수정 메뉴
# -------------------------
st.sidebar.markdown("---")
st.sidebar.subheader("🗓 전일 근무자 확인 / 수정")

prev_key = st.sidebar.text_input("전일 열쇠", value=prev_key)
prev_gyoyang5 = st.sidebar.text_input("전일 5교시 교양", value=prev_gyoyang5)
prev_sudong = st.sidebar.text_input("전일 1종수동", value=prev_sudong)

if st.sidebar.button("💾 수정내용 저장하기"):
    try:
        with open(PREV_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"열쇠": prev_key, "교양_5교시": prev_gyoyang5, "1종수동": prev_sudong},
                f, ensure_ascii=False, indent=2
            )
        st.sidebar.success("✅ 전일근무.json에 수정내용 저장 완료!")
    except Exception as e:
        st.sidebar.error(f"저장 실패: {e}")

# -------------------------
# 유틸 함수
# -------------------------
def normalize_name(s: str) -> str:
    if not isinstance(s, str): return ""
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"[-_·•‧‵′]", "", s)
    s = re.sub(r"\s+", "", s)
    return re.sub(r"[^\uAC00-\uD7A3]", "", s)

def build_norm_maps(name_list):
    """정규화 <-> 원본 매핑"""
    norm_to_orig = {}
    orig_to_norm = {}
    for x in name_list:
        n = normalize_name(x)
        orig_to_norm[x] = n
        if n and n not in norm_to_orig:
            norm_to_orig[n] = x
    return norm_to_orig, orig_to_norm

def pick_next_from_cycle(cycle, last, allowed_norms: set) -> str | None:
    """순번표에서 last 다음 사람 중 allowed_norms에 있는 '정규화 이름'을 찾아 반환(원본이름은 아님)"""
    if not cycle: return None
    start_idx = 0 if (not last or last not in cycle) else (cycle.index(last) + 1) % len(cycle)
    for i in range(len(cycle)):
        cand = cycle[(start_idx + i) % len(cycle)]
        if normalize_name(cand) in allowed_norms:
            return cand
    return None

def normalize_name(s):
    s = re.sub(r".*?", "", s)
    s = re.sub(r"[-_·•‧‵′]", "", s)
    s = re.sub(r"\s+", "", s)
    return re.sub(r"[^\uAC00-\uD7A3]", "", s)

def build_present_map(name_list):
    m = {}
    for x in name_list:
        key = normalize_name(x)
        if key and key not in m:
            m[key] = x
    return m

def next_in_cycle(current, cycle):
    if not cycle: return None
    if current not in cycle: return cycle[0]
    return cycle[(cycle.index(current)+1) % len(cycle)]

def pick_k_from_cycle(cycle, start_from, k, present_map, exclude_set=None, extra_pred=None):
    exclude_set = exclude_set or set()
    res = []; seen=set()
    if not cycle: return res
    start_idx = 0
    if start_from in cycle:
        start_idx = (cycle.index(start_from)+1) % len(cycle)
    for i in range(len(cycle)*2):
        cand = cycle[(start_idx+i) % len(cycle)]
        nkey = normalize_name(cand)
        if nkey in seen: continue
        seen.add(nkey)
        if nkey not in present_map: continue
        if nkey in exclude_set: continue
        if extra_pred and not extra_pred(present_map[nkey]): continue
        res.append(present_map[nkey])
        if len(res) >= k: break
    return res

def get_vehicle(name, veh_map):
    base = re.sub(r".*?", "", name).strip()
    for k,v in veh_map.items():
        if normalize_name(k) == normalize_name(base):
            return v
    return ""

def format_name_with_car(name, veh_map):
    car = get_vehicle(name, veh_map)
    mark = " (정비)" if car and car in repair_cars else ""
    note = re.search(r"(.*?)", name)
    note = f" ({note.group(1).replace('-', '').strip()})" if note else ""
    base = re.sub(r".*?", "", name).strip()
    return f"{base}{(' ' + car) if car else ''}{note}{mark}"

def can_attend_period(name, period, early_leave_list):
    time_map = {3:13.0,4:14.5,5:16.0}
    for e in early_leave_list:
        if normalize_name(e["name"]) in normalize_name(name):
            if e["time"] <= time_map[period]: return False
    return True

# -------------------------
# GPT OCR
# -------------------------
def gpt_extract_names_from_image(image_bytes, hint="도로주행"):
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    system = "당신은 표에서 사람 이름을 추출하는 전문 도구입니다. 반드시 JSON으로 응답하세요."
    user = (
        "이 이미지는 운전면허시험 근무표입니다.\n"
        "1️⃣ '학과', '기능장', '초소'를 제외한 도로주행 근무자 이름만 추출하세요.\n"
        "2️⃣ '조퇴 :' 문구가 있으면 조퇴자 이름과 시간을 추출하세요. 예: 조퇴 : 김병욱(14시~)\n"
        "3️⃣ 괄호 안 시간은 정수(14,14.5 등)로 변환하세요.\n"
        "4️⃣ 괄호 안이 '지원','인턴','연수'이면 제외하세요.\n"
        '결과 JSON 예: {"names":["김남균(A합)","김주현(B불)"],"early_leave":[{"name":"김병욱","time":14}]}'
    )
    try:
        r = client.chat.completions.create(model=MODEL_NAME,messages=[
            {"role":"system","content":system},
            {"role":"user","content":[
                {"type":"text","text":user},
                {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}
            ]}
        ])
        raw=r.choices[0].message.content
        js=json.loads(re.search(r"\{.*\}",raw,re.S).group(0))
        names=[n for n in js.get("names",[]) if not re.search("(지원|인턴|연수)",n)]
        return names, js.get("early_leave", []), raw
    except Exception as e:
        return [], [], str(e)

# -------------------------
# UI
# -------------------------
st.markdown("<h4 style='font-size:18px;'>1️⃣ 근무표 이미지 업로드</h4>", unsafe_allow_html=True)
morning_file=st.file_uploader("📸 오전 근무표",type=["png","jpg","jpeg"],key="morning")
afternoon_file=st.file_uploader("📸 오후 근무표",type=["png","jpg","jpeg"],key="afternoon")

if st.button("🧠 GPT로 이름 추출"):
    if not morning_file and not afternoon_file:
        st.warning("오전 또는 오후 이미지를 업로드하세요.")
    else:
        with st.spinner("GPT 분석 중..."):
            if morning_file:
                m_names,_,_=gpt_extract_names_from_image(morning_file.read(),"오전 도로주행")
                st.session_state.m_names=m_names; st.success(f"오전 인식: {len(m_names)}명")
            if afternoon_file:
                a_names,early_leave,_=gpt_extract_names_from_image(afternoon_file.read(),"오후 도로주행")
                st.session_state.a_names=a_names; st.session_state.early_leave=early_leave
                st.success(f"오후 인식: {len(a_names)}명 (조퇴 {len(early_leave)}명)")
        st.rerun()

# -------------------------
# 인식 결과
# -------------------------
st.markdown("<h4 style='font-size:18px;'>2️⃣ 인식 결과 확인</h4>", unsafe_allow_html=True)
col1,col2=st.columns(2)
morning_txt="\n".join(st.session_state.get("m_names",[]))
afternoon_txt="\n".join(st.session_state.get("a_names",[]))
morning_final=col1.text_area("오전 근무자",value=morning_txt,height=150)
afternoon_final=col2.text_area("오후 근무자",value=afternoon_txt,height=150)
morning_list=[x.strip() for x in morning_final.splitlines() if x.strip()]
afternoon_list=[x.strip() for x in afternoon_final.splitlines() if x.strip()]
early_leave_list=st.session_state.get("early_leave",[])

if st.button("📋 오전 근무 배정 생성"):
    # 정규화 맵
    present_norm_to_orig, present_orig_to_norm = build_norm_maps(morning_list)

    # 휴가/교육 제외 세트(정규화)
    excluded_norm = {normalize_name(x) for x in excluded_set}

    # 오늘 오전 실제 가능 인원(정규화)
    present_norms = set(present_norm_to_orig.keys()) - excluded_norm

    # 🔑 열쇠: 전체 근무자(휴가/교육 제외) 1일 1회 순환
    all_allowed_norms = [normalize_name(x) for x in key_order if normalize_name(x) not in excluded_norm]
    # all_allowed_norms를 순번표 그대로 쓰려면 pick_next_from_cycle에 원본 cycle을 넣어야 하므로,
    # 열쇠는 기존 next_in_cycle로 유지하되 제외만 반영
    key_cycle_filtered = [x for x in key_order if normalize_name(x) in set(all_allowed_norms)]
    today_key = next_in_cycle(prev_key, key_cycle_filtered) if key_cycle_filtered else ""

    # 🧑‍🏫 교양: prev_gyoyang5 다음부터 회전해 정확히 2명(1,2교시) 선발
    gy_cycle = gyoyang_order[:]  # 원본 순번표
    # 1교시
    gy1_name_in_cycle = pick_next_from_cycle(gy_cycle, prev_gyoyang5, present_norms)
    gy1 = present_norm_to_orig.get(normalize_name(gy1_name_in_cycle), "-") if gy1_name_in_cycle else "-"
    # 2교시 (gy1 바로 다음)
    # gy1이 없으면 prev_gyoyang5에서 다시 시작
    base_for_gy2 = gy1_name_in_cycle if gy1_name_in_cycle else prev_gyoyang5
    # 2교시 후보에서 1교시 정규화 이름 제외
    present_norms_for_gy2 = present_norms - ({normalize_name(gy1)} if gy1 != "-" else set())
    gy2_name_in_cycle = pick_next_from_cycle(gy_cycle, base_for_gy2, present_norms_for_gy2)
    gy2 = present_norm_to_orig.get(normalize_name(gy2_name_in_cycle), "-") if gy2_name_in_cycle else "-"

    # 🔧 1종 수동: prev_sudong 다음부터 회전해 sudong_count명 선발
    sudong_cycle = sudong_order[:]
    sud_list = []
    last_pick = prev_sudong if prev_sudong in sudong_cycle else None
    allowed_for_sudong = set(present_norms)  # (원하면 교양자 제외하려면 여기서 제거)
    for _ in range(sudong_count):
        pick = pick_next_from_cycle(sudong_cycle, last_pick, allowed_for_sudong)
        if not pick: break
        pick_orig = present_norm_to_orig.get(normalize_name(pick))
        if pick_orig:
            sud_list.append(pick_orig)
            allowed_for_sudong -= {normalize_name(pick_orig)}
            last_pick = pick
        else:
            break

    # 🚗 2종 자동: 오전 전체 - (1종수동 배정자)
    sud_norm_set = {normalize_name(x) for x in sud_list}
    two_auto = [x for x in morning_list if present_orig_to_norm.get(x) in (present_norms - sud_norm_set)]

    # 오후 교양 순번 계산용으로 저장 (오전 2교시 교양자)
    st.session_state.gy2 = gy2 if gy2 != "-" else ""

# 출력
gy1_clean = re.sub(r"\(.*?\)", "", gy1).strip() if gy1 != "-" else "-"
gy2_clean = re.sub(r"\(.*?\)", "", gy2).strip() if gy2 != "-" else "-"

lines = [
    "📅 오전 배정",
    f"열쇠: {today_key}",
    f"교양 1교시: {gy1_clean}",
    f"교양 2교시: {gy2_clean}",
]

if sud_list:
    for nm in sud_list:
        lines.append(f"1종수동: {format_name_with_car(nm, veh1)}")
else:
    lines.append("1종수동: (배정자 없음)")

lines.append("2종 자동:")
for nm in two_auto:
    lines.append(f" - {format_name_with_car(nm, veh2)}")

st.code("\n".join(lines), language="text")



# -------------------------
# 오후 배정
# -------------------------
st.markdown("<h4 style='font-size:18px;'>4️⃣ 오후 근무 배정 생성</h4>", unsafe_allow_html=True)
if st.button("📋 오후 근무 배정 생성"):
    present_a_map=build_present_map(afternoon_list)
    exclude_norm={normalize_name(x) for x in excluded_set}
    all_allowed=[x for x in key_order if normalize_name(x) not in exclude_norm]
    afternoon_key=next_in_cycle(prev_key,all_allowed) if prev_key else (all_allowed[0] if all_allowed else "")
    
    gy_start = None
    if 'gy2' in st.session_state and st.session_state.gy2 and st.session_state.gy2 in gyoyang_order:
        gy_start = st.session_state.gy2
    elif prev_gyoyang5 and prev_gyoyang5 in gyoyang_order:
        gy_start = prev_gyoyang5

    gy_pool = pick_k_from_cycle(gyoyang_order, gy_start, len(gyoyang_order), present_a_map, exclude_norm)
    
    def can_period(nm,period): return can_attend_period(nm,period,early_leave_list)
    gy3=gy4=gy5=None; used=set(); idx=0
    while idx<len(gy_pool) and not gy3:
        c=gy_pool[idx]; idx+=1
        if can_period(c,3): gy3=c; used.add(normalize_name(c)); break
    while idx<len(gy_pool) and not gy4:
        c=gy_pool[idx]; idx+=1
        if normalize_name(c) in used: continue
        if can_period(c,4): gy4=c; used.add(normalize_name(c)); break
    while idx<len(gy_pool) and not gy5:
        c=gy_pool[idx]; idx+=1
        if normalize_name(c) in used: continue
        if can_period(c,5): gy5=c; used.add(normalize_name(c)); break

    aft_sudong=pick_k_from_cycle(sudong_order,prev_sudong,1,present_a_map,exclude_norm)
    aft_sudong=aft_sudong[0] if aft_sudong else None
    sudong_norm={normalize_name(aft_sudong)} if aft_sudong else set()
    aft_2jong=[x for x in afternoon_list if normalize_name(x) not in sudong_norm and normalize_name(x) not in exclude_norm]

    lines=[f"📅 오후 배정",f"열쇠: {afternoon_key}",f"교양 3교시: {gy3 or '-'}",f"교양 4교시: {gy4 or '-'}",f"교양 5교시: {gy5 or '-'}"]
    if aft_sudong: lines.append(f"1종수동 (오후): {format_name_with_car(aft_sudong,veh1)}")
    else: lines.append("1종수동 (오후): (배정자 없음)")
    lines.append("2종 자동:")
    for nm in aft_2jong: lines.append(f" - {format_name_with_car(nm,veh2)}")

    if early_leave_list:
        lines.append("조퇴자:")
        for e in early_leave_list:
            t=str(e['time']).replace('.5','시30분~') if isinstance(e['time'],float) else f"{int(e['time'])}시~"
            lines.append(f" - {e['name']}({t})")

    st.code("\n".join(lines),language="text")

    # ✅ 자동 저장
    today_record = {
        "열쇠": afternoon_key,
        "교양_5교시": gy5 if gy5 else (gy4 if gy4 else (gy3 if gy3 else prev_gyoyang5)),
        "1종수동": aft_sudong if aft_sudong else prev_sudong
    }
