# app.py — 도로주행 근무자동배정 (GPT OCR + 순번/차량 통합 완전본)
import streamlit as st
from openai import OpenAI
import base64, re, json, os

# -------------------------
# 페이지 설정
# -------------------------
st.set_page_config(page_title="도로주행 근무자동배정 (GPT OCR + 순번)", layout="wide")
st.title("🚗 도로주행 근무자동배정 (GPT OCR + 순번/차량 통합)")

# -------------------------
# OpenAI 초기화 (Secrets에 OPENAI_API_KEY 필요)
# -------------------------
try:
    client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
except Exception as e:
    st.error("⚠️ OPENAI_API_KEY가 설정되어 있지 않거나 접근 불가합니다. Streamlit Secrets 설정을 확인하세요.")
    st.stop()

# -------------------------
# 사이드바: 순번표 / 차량표 / 옵션 (기본값은 사용자가 준 값)
# -------------------------
st.sidebar.header("초기 데이터 (수정 가능)")

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

st.sidebar.markdown("**(1) 순번표 / 차량표** (필요 시 수정하세요)")
key_order_text = st.sidebar.text_area("열쇠 순번 (위→아래 순환)", default_key_order, height=160)
gyoyang_order_text = st.sidebar.text_area("교양 순번 (위→아래 순환)", default_gyoyang_order, height=160)
sudong_order_text = st.sidebar.text_area("1종 수동 순번 (위→아래 순환)", default_sudong_order, height=160)
cha1_text = st.sidebar.text_area("1종 수동 차량표 (줄당: '호수 이름')", default_cha1, height=140)
cha2_text = st.sidebar.text_area("2종 자동 차량표 (줄당: '호수 이름')", default_cha2, height=220)

def parse_list(text):
    return [line.strip() for line in text.splitlines() if line.strip()]

def parse_vehicle_map(text):
    m = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            car = parts[0]
            name = " ".join(parts[1:])
            m[name] = car
    return m

key_order = parse_list(key_order_text)
gyoyang_order = parse_list(gyoyang_order_text)
sudong_order = parse_list(sudong_order_text)
veh1 = parse_vehicle_map(cha1_text)
veh2 = parse_vehicle_map(cha2_text)

st.sidebar.markdown("---")
st.sidebar.header("옵션 / 전일 기준")
prev_key = st.sidebar.text_input("전일 열쇠", value="")
prev_gyoyang5 = st.sidebar.text_input("전일 5교시 교양", value="")
prev_sudong = st.sidebar.text_input("전일 1종수동", value="")
sudong_count = st.sidebar.radio("1종 수동 인원수 (기본)", [1,2], index=0)
computer_names_input = st.sidebar.text_input("전산병행자 (쉼표로 구분)", value="")
computer_names = [n.strip() for n in computer_names_input.split(",") if n.strip()]
repair_cars_input = st.sidebar.text_input("정비중 차량 (예: 12호,6호)", value="")
repair_cars = [r.strip() for r in repair_cars_input.split(",") if r.strip()]

# 모델 선택
st.sidebar.markdown("---")
model_name = st.sidebar.selectbox("GPT 이미지 모델 선택", ["gpt-4o-mini", "gpt-4o"], index=0)

# -------------------------
# 유틸: 이미지 → base64
# -------------------------
def image_to_b64_str(file) -> str:
    b = file.read()
    return base64.b64encode(b).decode("utf-8")

# -------------------------
# GPT 이미지 OCR 호출 (Responses/chat 호환성에 맞춰 안전하게 호출)
# -------------------------
def gpt_extract_names_from_image(image_bytes, hint="도로주행 근무자"):
    """
    이미지 바이트를 받아 GPT에 전달하여 '이름 리스트' 결과를 JSON으로 반환하도록 요청.
    모델은 반드시 JSON {"names":[...], "notes":[...]} 를 반환하도록 프롬프트를 강제합니다.
    """
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    # 프롬프트 (명확히 JSON만 반환하도록 지시)
    system = "당신은 표에서 사람 이름만 뽑아 JSON으로만 반환하는 도구입니다. 응답 외 추가 문장을 출력하지 마십시오."
    user = (
        f"이미지에서 '{hint}' 섹션의 이름만 추출하세요. 괄호/메모(예: A-합, B-불), 숫자, 영문등은 제거하고\n"
        "반드시 다음 JSON 형식으로만 답하세요:\n"
        '{"names": ["홍길동","김철수"], "notes": []}\n'
        "이름은 한글 2~5자만 허용합니다."
    )

    # 최신 OpenAI Python client는 여러 방식이 있기에 chat.completions.create 를 사용 (환경에 따라 조정)
    try:
        resp = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type":"text","text": user},
                    {"type":"image_url","image_url":{"url": f"data:image/jpeg;base64,{b64}"}}
                ]}
            ],
            max_tokens=1000
        )
    except Exception as e:
        return [], f"GPT 호출 실패: {e}"

    # 응답 텍스트 추출
    try:
        raw = resp.choices[0].message.content
        # JSON 파싱 시도: 모델이 JSON만 반환하도록 강제했으나 안전하게 {} 범위 찾음
        m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not m:
            return [], f"모델 반환 형식 오류: {raw}"
        js = json.loads(m.group(0))
        names = js.get("names", []) if isinstance(js, dict) else []
        # 정제: 괄호/비한글 제거, 2~5글자 필터
        clean = []
        for n in names:
            if not isinstance(n, str): 
                continue
            n2 = re.sub(r"[\(\)\[\]\{\}]", "", n)
            n2 = re.sub(r"[^가-힣]", "", n2).strip()
            if 2 <= len(n2) <= 5:
                clean.append(n2)
        return clean, raw
    except Exception as e:
        return [], f"응답 파싱 실패: {e} | 원문: {raw}"

# -------------------------
# OCR 버튼 + 파일 업로드
# -------------------------
st.header("1) 오전/오후 근무표 이미지 업로드 및 GPT OCR")
col1, col2 = st.columns(2)
with col1:
    morning_file = st.file_uploader("오전 근무표 이미지", type=["png","jpg","jpeg"], key="morning")
with col2:
    afternoon_file = st.file_uploader("오후 근무표 이미지", type=["png","jpg","jpeg"], key="afternoon")

if st.button("이미지로부터 이름 추출 (GPT)"):
    if not morning_file and not afternoon_file:
        st.warning("오전 또는 오후 이미지를 업로드하세요.")
    else:
        with st.spinner("이미지를 GPT로 분석 중..."):
            if morning_file:
                m_names, m_raw = gpt_extract_names_from_image(morning_file.read(), hint="오전 도로주행")
                st.session_state.m_names = m_names
                st.session_state.m_raw_m = m_raw
                st.success(f"오전 인식: {len(m_names)}명")
            else:
                st.session_state.m_names = []
            if afternoon_file:
                a_names, a_raw = gpt_extract_names_from_image(afternoon_file.read(), hint="오후 도로주행")
                st.session_state.a_names = a_names
                st.session_state.m_raw_a = a_raw
                st.success(f"오후 인식: {len(a_names)}명")
            else:
                st.session_state.a_names = []
        st.rerun()

# 디버그: 원문 보기 (접근 가능하면)
if st.session_state.get("m_raw_m"):
    with st.expander("오전 GPT 원문 (디버그)"):
        st.text_area("오전 원문", st.session_state.get("m_raw_m"), height=180)
if st.session_state.get("m_raw_a"):
    with st.expander("오후 GPT 원문 (디버그)"):
        st.text_area("오후 원문", st.session_state.get("m_raw_a"), height=180)

# -------------------------
# 이름 선택(구간) UI — 모바일 친화적 버튼 방식
# -------------------------
def range_select_ui(names, label):
    """
    시작/끝 버튼 2회 클릭으로 구간 선택. 선택이 완료되면 리스트 반환.
    """
    if not names:
        return []
    st.markdown(f"### {label} — 추출된 이름 (위→아래 순서)")
    # show compact list
    numbered = [f"{i+1}. {n}" for i, n in enumerate(names)]
    st.text_area(f"{label} 인식 목록 (편집 가능)", "\n".join(numbered), height=120)

    st.markdown(f"**{label} 구간 선택** — 시작 버튼 → 끝 버튼 (두 번 클릭)")
    cols = st.columns(3)
    start_key = f"start_{label}"
    end_key = f"end_{label}"
    if start_key not in st.session_state:
        st.session_state[start_key] = None
    if end_key not in st.session_state:
        st.session_state[end_key] = None

    chosen = False
    for idx, nm in enumerate(names):
        col = cols[idx % 3]
        with col:
            btn_key = f"{label}_{idx}"
            is_selected = (st.session_state[start_key] == nm or st.session_state[end_key] == nm)
            btn_style = "primary" if is_selected else "secondary"
            if st.button(nm, key=btn_key, type=btn_style, use_container_width=True):
                if st.session_state[start_key] is None:
                    st.session_state[start_key] = nm
                elif st.session_state[end_key] is None:
                    st.session_state[end_key] = nm
                    chosen = True
                else:
                    # reset start to new click
                    st.session_state[start_key] = nm
                    st.session_state[end_key] = None

    if st.session_state[start_key] and st.session_state[end_key]:
        try:
            s = names.index(st.session_state[start_key])
            e = names.index(st.session_state[end_key])
            if s > e: s, e = e, s
            selected = names[s:e+1]
            st.success(f"선택 구간: {names[s]} → {names[e]} ({len(selected)}명)")
            if chosen:
                # clear selections after acknowledging
                st.session_state[start_key] = None
                st.session_state[end_key] = None
            return selected
        except Exception:
            st.error("구간 선택 오류 — 다시 시도하세요.")
            st.session_state[start_key] = None
            st.session_state[end_key] = None
    return []

st.markdown("---")
st.header("2) 추출된 근무자 확인 및 구간 선택")
colm, cola = st.columns(2)
with colm:
    st.subheader("오전")
    morning_selected = []
    if st.session_state.get("m_names"):
        morning_selected = range_select_ui(st.session_state.get("m_names"), "오전")
        if morning_selected:
            st.session_state.selected_morning = morning_selected
    else:
        st.info("오전 인식 결과가 없습니다. 먼저 '이미지로부터 이름 추출 (GPT)'를 실행하세요.")
with cola:
    st.subheader("오후")
    afternoon_selected = []
    if st.session_state.get("a_names"):
        afternoon_selected = range_select_ui(st.session_state.get("a_names"), "오후")
        if afternoon_selected:
            st.session_state.selected_afternoon = afternoon_selected
    else:
        st.info("오후 인식 결과가 없습니다. 먼저 '이미지로부터 이름 추출 (GPT)'를 실행하세요.")

# allow manual edit fallback
st.markdown("---")
st.header("수동 보정 (필요시)")
col1, col2 = st.columns(2)
with col1:
    manual_morning = st.text_area("오전 최종 근무자 (한 줄에 하나씩)", value="\n".join(st.session_state.get("selected_morning", [])), height=140)
with col2:
    manual_afternoon = st.text_area("오후 최종 근무자 (한 줄에 하나씩)", value="\n".join(st.session_state.get("selected_afternoon", [])), height=140)

morning_list = [x.strip() for x in manual_morning.splitlines() if x.strip()]
afternoon_list = [x.strip() for x in manual_afternoon.splitlines() if x.strip()]

# -------------------------
# 순번 계산 유틸
# -------------------------
def next_in_cycle(current, cycle):
    if not cycle:
        return None
    if current not in cycle:
        return cycle[0]
    return cycle[(cycle.index(current) + 1) % len(cycle)]

def next_valid_after(current, cycle, present_set):
    if not cycle or not present_set:
        return None
    start_idx = 0
    if current in cycle:
        start_idx = (cycle.index(current) + 1) % len(cycle)
    for i in range(len(cycle)):
        cand = cycle[(start_idx + i) % len(cycle)]
        if cand in present_set:
            return cand
    return None

# -------------------------
# 3) 최종 배정 생성 (버튼)
# -------------------------
st.markdown("---")
st.header("3) 최종 배정 생성 (순번 + 차량 배정)")
if st.button("최종 근무 배정 생성"):
    if not morning_list and not afternoon_list:
        st.warning("오전 또는 오후 근무자 목록이 비어 있습니다.")
    else:
        present_m = set(morning_list)
        present_a = set(afternoon_list)

        # 열쇠: next after prev_key
        today_key = next_in_cycle(prev_key, key_order) if prev_key else key_order[0]

        # 교양 오전 (2명) - skip 전산병행
        gy_start = next_in_cycle(prev_gyoyang5, gyoyang_order) if prev_gyoyang5 else gyoyang_order[0]
        gy_candidates = []
        cur = gy_start
        for _ in range(len(gyoyang_order)*2):
            if cur in present_m and cur not in computer_names:
                if cur not in gy_candidates:
                    gy_candidates.append(cur)
            if len(gy_candidates) >= 2:
                break
            cur = next_in_cycle(cur, gyoyang_order)
        gy1 = gy_candidates[0] if len(gy_candidates) >= 1 else None
        gy2 = gy_candidates[1] if len(gy_candidates) >= 2 else None

        # 1종 수동 오전 (sudong_count)
        sudong_assigned = []
        cur_s = prev_sudong if prev_sudong else sudong_order[0]
        for _ in range(len(sudong_order)*2):
            cand = next_in_cycle(cur_s, sudong_order)
            cur_s = cand
            if cand in present_m and cand not in sudong_assigned:
                sudong_assigned.append(cand)
            if len(sudong_assigned) >= sudong_count:
                break

        # 오전 2종자동: present_m minus sudong_assigned
        morning_2jong = [p for p in morning_list if p not in sudong_assigned]
        morning_2jong_map = []
        for name in morning_2jong:
            car = veh2.get(name, "")
            note = "(정비중)" if car and car in repair_cars else ""
            morning_2jong_map.append((name, car, note))

        # 오후 배정
        afternoon_key = today_key
        last_gy = gy2 if gy2 else (gy1 if gy1 else prev_gyoyang5)
        last_sudong = sudong_assigned[-1] if sudong_assigned else prev_sudong

        # 오후 교양 3~5
        aft_gy_candidates = []
        curg = last_gy if last_gy else gyoyang_order[0]
        for _ in range(len(gyoyang_order)*2):
            curg = next_in_cycle(curg, gyoyang_order)
            if curg in present_a and curg not in computer_names:
                if curg not in aft_gy_candidates:
                    aft_gy_candidates.append(curg)
            if len(aft_gy_candidates) >= 3:
                break
        gy3 = aft_gy_candidates[0] if len(aft_gy_candidates) >= 1 else None
        gy4 = aft_gy_candidates[1] if len(aft_gy_candidates) >= 2 else None
        gy5 = aft_gy_candidates[2] if len(aft_gy_candidates) >= 3 else None

        # 오후 1종 (1명)
        aft_sudong = None
        curs2 = last_sudong if last_sudong else sudong_order[0]
        for _ in range(len(sudong_order)*2):
            cand = next_in_cycle(curs2, sudong_order)
            curs2 = cand
            if cand in present_a:
                aft_sudong = cand
                break

        aft_2jong = [p for p in afternoon_list if p != aft_sudong]
        aft_2jong_map = []
        for name in aft_2jong:
            car = veh2.get(name, "")
            note = "(정비중)" if car and car in repair_cars else ""
            aft_2jong_map.append((name, car, note))

        # -------------------------
        # 출력 텍스트 생성
        # -------------------------
        morning_lines = []
        morning_lines.append(f"📅 오전 배정")
        morning_lines.append(f"열쇠: {today_key}")
        morning_lines.append(f"교양 1교시: {gy1 if gy1 else '-'}")
        morning_lines.append(f"교양 2교시: {gy2 if gy2 else '-'}")
        if sudong_assigned:
            for i, nm in enumerate(sudong_assigned, start=1):
                morning_lines.append(f"1종수동 #{i}: {nm}" + (f" ({veh1.get(nm)})" if veh1.get(nm) else ""))
        else:
            morning_lines.append("1종수동: (배정자 없음)")
        morning_lines.append("2종 자동:")
        for nm, car, note in morning_2jong_map:
            morning_lines.append(f" - {nm} → {car if car else '-'} {note}")

        afternoon_lines = []
        afternoon_lines.append(f"📅 오후 배정")
        afternoon_lines.append(f"열쇠: {afternoon_key}")
        afternoon_lines.append(f"교양 3교시: {gy3 if gy3 else '-'}")
        afternoon_lines.append(f"교양 4교시: {gy4 if gy4 else '-'}")
        afternoon_lines.append(f"교양 5교시: {gy5 if gy5 else '-'}")
        if aft_sudong:
            afternoon_lines.append(f"1종수동 (오후): {aft_sudong}" + (f" ({veh1.get(aft_sudong)})" if veh1.get(aft_sudong) else ""))
        else:
            afternoon_lines.append("1종수동 (오후): (배정자 없음)")
        afternoon_lines.append("2종 자동:")
        for nm, car, note in aft_2jong_map:
            afternoon_lines.append(f" - {nm} → {car if car else '-'} {note}")

        # 화면 출력
        st.markdown("## 최종 배정 결과")
        c1, c2 = st.columns(2)
        with c1:
            st.text("\n".join(morning_lines))
        with c2:
            st.text("\n".join(afternoon_lines))

        combined = "\n".join(morning_lines) + "\n\n" + "\n".join(afternoon_lines)
        st.download_button("결과 다운로드 (.txt)", data=combined.encode("utf-8-sig"), file_name="근무배정결과.txt", mime="text/plain")

        # 전일저장 옵션
        if st.checkbox("이 결과를 '전일 기준'으로 저장 (전일근무.json 덮어쓰기)", value=True):
            PREV_DAY_FILE = "전일근무.json"
            today_record = {
                "열쇠": afternoon_key,
                "교양_5교시": gy5 if gy5 else (gy4 if gy4 else (gy3 if gy3 else prev_gyoyang5)),
                "1종수동": aft_sudong if aft_sudong else (sudong_assigned[-1] if sudong_assigned else prev_sudong)
            }
            try:
                with open(PREV_DAY_FILE, "w", encoding="utf-8") as f:
                    json.dump(today_record, f, ensure_ascii=False, indent=2)
                st.success(f"{PREV_DAY_FILE}에 저장했습니다.")
            except Exception as e:
                st.error(f"전일 저장 실패: {e}")
