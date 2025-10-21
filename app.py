# app.py
import streamlit as st
import os
import base64
import json
import re
from io import BytesIO
from PIL import Image
from typing import List, Dict, Tuple

# OpenAI client (pip install openai) - using new OpenAI Python client
try:
    from openai import OpenAI
except Exception:
    raise RuntimeError("openai 패키지가 필요합니다. `pip install openai` 실행하세요.")

# ========== 설정 ==========
st.set_page_config(page_title="도로주행 GPT-OCR 배정기", layout="wide")
st.title("🚦 도로주행 — GPT 이미지 OCR + 자동 배정 (한글)")

# 모델 이름 (이미지 입력 가능한 모델로 설정하세요)
GPT_IMAGE_MODEL = "gpt-4o-mini"

# OpenAI 초기화 (환경변수 OPENAI_API_KEY 필요)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY", None)
if not OPENAI_API_KEY:
    st.error("OpenAI API 키가 설정되어 있지 않습니다. 환경변수 OPENAI_API_KEY 또는 Streamlit secrets에 추가하세요.")
    st.stop()
client = OpenAI(api_key=OPENAI_API_KEY)

# ========== 유틸리티 ==========
def image_to_base64_bytes(img_file) -> str:
    b = img_file.read()
    return base64.b64encode(b).decode("utf-8")

def prompt_for_names_from_image(role_hint: str = "도로주행 근무자") -> str:
    """
    GPT에게 보낼 프롬프트 템플릿. 핵심: JSON 배열로 정확히 반환하라.
    """
    p = f"""
다음은 근무표 사진입니다. 당신은 '표'에서 **{role_hint}** 섹션을 찾아서
괄호() 안의 메모, 'A-합', 'B-불', '전산병행' 등 메모를 제거한 **이름 목록만**
순서(위→아래)대로 추출해서 **정확한 JSON** 형식으로 반환하세요.

반드시 출력 형식은 **유효한 JSON** 하나의 객체여야 합니다. (다른 텍스트 NO)

요구하는 출력 JSON 형식:
{{
  "names": ["홍길동","김철수", ...],
  "notes": ["김면정(A-합) -> A-합 처리됨", "..."]  // 메모/부가정보가 필요하면 적음, 없으면 빈 배열
}}

조건:
- 이름은 한글 2~5자만 허용.
- 괄호/쉼표/영문/숫자 제거.
- 만약 '도로주행' 섹션을 찾을 수 없거나 불확실하면 빈 배열을 반환하도록 하세요.
- 출력에 어떤 추가 설명 텍스트(사람 친화적 문장)를 포함하지 마세요. 오직 JSON만.
- 사진이 여러 섹션(오전/오후)이면, 호출 시 role_hint로 "오전 도로주행" 또는 "오후 도로주행"을 지정하여 분리 호출하세요.
"""
    return p

def call_gpt_for_image_names(image_bytes_b64: str, role_hint: str = "도로주행 근무자") -> Tuple[List[str], List[str], str]:
    """
    GPT 이미지 분석 호출.
    Returns: (names_list, notes_list, raw_response_text)
    """
    # Build input for Responses API with image attached as data URL
    data_url = f"data:image/jpeg;base64,{image_bytes_b64}"

    system_prompt = "당신은 한국어에 능통한 표(테이블) 텍스트 추출 전문가입니다."
    user_prompt = prompt_for_names_from_image(role_hint=role_hint)

    # The 'input' for the Responses API supports a list of multimodal parts.
    # We'll use the OpenAI Python client 'Responses' wrapper through client.responses.create.
    try:
        resp = client.responses.create(
            model=GPT_IMAGE_MODEL,
            input=[
                {"role":"system","content": system_prompt},
                {"role":"user","content": user_prompt},
                # attach image as a multimodal input part (type may vary by client version)
                {"type":"input_image","image_url": data_url}
            ],
            # set a moderate timeout / max tokens
            max_output_tokens=800
        )
    except Exception as e:
        return [], [], f"GPT 호출 실패: {e}"

    # The exact shape of resp depends on client version.
    # Try to extract text content robustly.
    try:
        # New Responses API: resp.output may have content items with 'type':'output_text'
        outputs = []
        if hasattr(resp, "output") and resp.output:
            # resp.output is a list of items
            for item in resp.output:
                # item may contain 'content' list
                if isinstance(item, dict):
                    # flatten text fields
                    if "content" in item:
                        for c in item["content"]:
                            if isinstance(c, dict) and c.get("type") == "output_text":
                                outputs.append(c.get("text",""))
                    else:
                        # fallback: if item has 'text'
                        if item.get("text"):
                            outputs.append(item.get("text"))
        # fallback: try resp.output_text if present
        raw_text = " ".join(outputs) if outputs else (getattr(resp, "output_text", "") or str(resp))
    except Exception:
        raw_text = str(resp)

    # Now attempt to find JSON within raw_text
    json_str = None
    # try to locate first { ... }
    m = re.search(r"\{.*\}", raw_text, flags=re.DOTALL)
    if m:
        json_str = m.group(0)
    else:
        # maybe the model returned a JSON array or multiple lines: treat whole as JSON
        json_str = raw_text.strip()

    # parse JSON safely
    try:
        parsed = json.loads(json_str)
        names = parsed.get("names", []) if isinstance(parsed, dict) else []
        notes = parsed.get("notes", []) if isinstance(parsed, dict) else []
        # ensure names are cleaned: allow only Korean 2~5 chars
        clean_names = []
        for n in names:
            if isinstance(n, str):
                n2 = re.sub(r"[\(\)\[\]\{\}]", "", n).strip()
                n2 = re.sub(r"[^가-힣]", "", n2)
                if 2 <= len(n2) <= 5:
                    clean_names.append(n2)
        return clean_names, notes if isinstance(notes, list) else [], raw_text
    except Exception as e:
        # If parsing failed, return raw_text for human debugging
        return [], [], f"JSON 파싱 실패: {e}\n원문:\n{raw_text}"

# ========== 사이드바: 순번표 / 차량 매핑 / 옵션 ==========
st.sidebar.header("초기 데이터 입력 (수정 가능)")

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

st.sidebar.markdown("**순번표 / 차량표** (원하면 수정)")
key_order_text = st.sidebar.text_area("열쇠 순번 (위→아래)", value=default_key_order, height=160)
gyoyang_order_text = st.sidebar.text_area("교양 순번 (위→아래)", value=default_gyoyang_order, height=160)
sudong_order_text = st.sidebar.text_area("1종 수동 순번 (위→아래)", value=default_sudong_order, height=160)
cha1_text = st.sidebar.text_area("1종 수동 차량표 (한 줄: '호수 이름')", value=default_cha1, height=140)
cha2_text = st.sidebar.text_area("2종 자동 차량표 (한 줄: '호수 이름')", value=default_cha2, height=200)

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
st.sidebar.header("옵션")
prev_key = st.sidebar.text_input("전일 열쇠", value="")
prev_gyoyang5 = st.sidebar.text_input("전일 5교시 교양", value="")
prev_sudong = st.sidebar.text_input("전일 1종수동", value="")
sudong_count = st.sidebar.radio("1종 수동 인원수", [1,2], index=0)
computer_names_input = st.sidebar.text_input("전산병행자 (쉼표구분)", value="")
computer_names = [n.strip() for n in computer_names_input.split(",") if n.strip()]
repair_cars_input = st.sidebar.text_input("정비중 차량 (쉼표로, 예: 12호,6호)", value="")
repair_cars = [r.strip() for r in repair_cars_input.split(",") if r.strip()]

# ========== 메인 UI ==========
st.header("1) 이미지 업로드 (오전/오후 각각)")

col1, col2 = st.columns(2)
with col1:
    morning_file = st.file_uploader("오전 근무표 이미지", type=["png","jpg","jpeg"], key="morning_upload")
with col2:
    afternoon_file = st.file_uploader("오후 근무표 이미지", type=["png","jpg","jpeg"], key="afternoon_upload")

st.markdown("모델이 이미지를 분석해 '이름 목록'을 JSON 배열로 반환하도록 합니다. 반환 결과를 확인하고 수정 후 '최종 배정'을 실행하세요.")

# ========== 호출 버튼: GPT 이미지 OCR ==========
if st.button("이미지로부터 이름 추출 (GPT)"):
    # Morning
    if morning_file:
        b64 = image_to_base64_bytes(morning_file)
        names_m, notes_m, raw_m = call_gpt_for_image_names(b64, role_hint="오전 도로주행 근무자")
        st.session_state.m_names = names_m
        st.session_state.m_notes = notes_m
        st.session_state.m_raw = raw_m
        st.success(f"오전 후보 {len(names_m)}명 추출")
    else:
        st.session_state.m_names = []
        st.session_state.m_notes = []
        st.session_state.m_raw = ""
    # Afternoon
    if afternoon_file:
        b64 = image_to_base64_bytes(afternoon_file)
        names_a, notes_a, raw_a = call_gpt_for_image_names(b64, role_hint="오후 도로주행 근무자")
        st.session_state.a_names = names_a
        st.session_state.a_notes = notes_a
        st.session_state.a_raw = raw_a
        st.success(f"오후 후보 {len(names_a)}명 추출")
    else:
        st.session_state.a_names = []
        st.session_state.a_notes = []
        st.session_state.a_raw = ""

# show raw model text for debugging if needed
if st.session_state.get("m_raw"):
    with st.expander("오전 GPT 원문 (디버그)"):
        st.text_area("오전 원문", st.session_state.get("m_raw"), height=200)
if st.session_state.get("a_raw"):
    with st.expander("오후 GPT 원문 (디버그)"):
        st.text_area("오후 원문", st.session_state.get("a_raw"), height=200)

# ========== 사용자 확인 / 편집 ==========
st.header("2) 추출 결과 확인·수정")
m_default_text = "\n".join(st.session_state.get("m_names", []))
a_default_text = "\n".join(st.session_state.get("a_names", []))
colm, cola = st.columns(2)
with colm:
    st.subheader("오전 (추출 -> 검토)")
    morning_edit = st.text_area("오전 최종 근무자 (한 줄에 하나씩)", value=m_default_text, height=220)
with cola:
    st.subheader("오후 (추출 -> 검토)")
    afternoon_edit = st.text_area("오후 최종 근무자 (한 줄에 하나씩)", value=a_default_text, height=220)

morning_list = [x.strip() for x in morning_edit.splitlines() if x.strip()]
afternoon_list = [x.strip() for x in afternoon_edit.splitlines() if x.strip()]

# ========== 3) 최종 배정 생성 (순번로직 적용) ==========
st.header("3) 최종 배정 생성")
if st.button("최종 근무 배정 생성"):
    # prepare sets
    present_set_morning = set(morning_list)
    present_set_afternoon = set(afternoon_list)

    # --- 오전 배정 ---
    today_key = next_in_cycle(prev_key, key_order)

    # 교양 오전 (2명)
    gy_start = next_in_cycle(prev_gyoyang5, gyoyang_order)
    gy_candidates = []
    cur = gy_start
    for _ in range(len(gyoyang_order)*2):
        if cur in present_set_morning and cur not in computer_names:
            if cur not in gy_candidates:
                gy_candidates.append(cur)
        if len(gy_candidates) >= 2:
            break
        cur = next_in_cycle(cur, gyoyang_order)
    gy1 = gy_candidates[0] if len(gy_candidates) > 0 else None
    gy2 = gy_candidates[1] if len(gy_candidates) > 1 else None

    # 1종 수동 오전 (sudong_count)
    sudong_assigned = []
    cur_s = prev_sudong if prev_sudong else sudong_order[0]
    for _ in range(len(sudong_order)*2):
        cand = next_in_cycle(cur_s, sudong_order)
        cur_s = cand
        if cand in present_set_morning and cand not in sudong_assigned:
            sudong_assigned.append(cand)
        if len(sudong_assigned) >= sudong_count:
            break

    # morning 2종 mapping
    morning_2jong = [p for p in morning_list if p not in sudong_assigned]
    morning_2jong_map = []
    for name in morning_2jong:
        car = veh2.get(name, "")
        note = "(정비중)" if car and car in repair_cars else ""
        morning_2jong_map.append((name, car, note))

    # build morning text
    morning_lines = []
    morning_lines.append("=== 오전 배정 ===")
    morning_lines.append(f"열쇠: {today_key}")
    morning_lines.append(f"교양 1교시: {gy1 if gy1 else '-'}")
    morning_lines.append(f"교양 2교시: {gy2 if gy2 else '-'}")
    for idx, nm in enumerate(sudong_assigned, start=1):
        morning_lines.append(f"1종수동 #{idx}: {nm} {( '(%s)'%veh1.get(nm) if veh1.get(nm) else '')}")
    morning_lines.append("2종 자동:")
    for name, car, note in morning_2jong_map:
        morning_lines.append(f" - {name} → {car if car else '-'} {note}")

    # --- 오후 배정 ---
    afternoon_key = today_key
    last_gy = gy2 if gy2 else (gy1 if gy1 else prev_gyoyang5)
    last_sudong = sudong_assigned[-1] if sudong_assigned else prev_sudong

    # afternoon 교양 3,4,5
    aft_gy_candidates = []
    cur_g = last_gy if last_gy else gyoyang_order[0]
    for _ in range(len(gyoyang_order)*2):
        cur_g = next_in_cycle(cur_g, gyoyang_order)
        if cur_g in present_set_afternoon and cur_g not in computer_names:
            if cur_g not in aft_gy_candidates:
                aft_gy_candidates.append(cur_g)
        if len(aft_gy_candidates) >= 3:
            break
    gy3 = aft_gy_candidates[0] if len(aft_gy_candidates) > 0 else None
    gy4 = aft_gy_candidates[1] if len(aft_gy_candidates) > 1 else None
    gy5 = aft_gy_candidates[2] if len(aft_gy_candidates) > 2 else None

    # afternoon 1종 (1명)
    aft_sudong = None
    cur_s2 = last_sudong if last_sudong else sudong_order[0]
    for _ in range(len(sudong_order)*2):
        cand = next_in_cycle(cur_s2, sudong_order)
        cur_s2 = cand
        if cand in present_set_afternoon:
            aft_sudong = cand
            break

    aft_2jong = [p for p in afternoon_list if p != aft_sudong]
    aft_2jong_map = []
    for name in aft_2jong:
        car = veh2.get(name, "")
        note = "(정비중)" if car and car in repair_cars else ""
        aft_2jong_map.append((name, car, note))

    afternoon_lines = []
    afternoon_lines.append("=== 오후 배정 ===")
    afternoon_lines.append(f"열쇠: {afternoon_key}")
    afternoon_lines.append(f"교양 3교시: {gy3 if gy3 else '-'}")
    afternoon_lines.append(f"교양 4교시: {gy4 if gy4 else '-'}")
    afternoon_lines.append(f"교양 5교시: {gy5 if gy5 else '-'}")
    if aft_sudong:
        afternoon_lines.append(f"1종수동 (오후): {aft_sudong} {( '(%s)'%veh1.get(aft_sudong) if veh1.get(aft_sudong) else '')}")
    afternoon_lines.append("2종 자동:")
    for name, car, note in aft_2jong_map:
        afternoon_lines.append(f" - {name} → {car if car else '-'} {note}")

    # ========== 출력 ==========
    st.subheader("최종 배정 결과 (오전 / 오후)")
    col1, col2 = st.columns(2)
    with col1:
        st.text("\n".join(morning_lines))
    with col2:
        st.text("\n".join(afternoon_lines))

    all_text = "\n".join(morning_lines) + "\n\n" + "\n".join(afternoon_lines)
    st.download_button("결과 다운로드 (.txt)", data=all_text.encode("utf-8-sig"), file_name="근무배정결과.txt", mime="text/plain")

    # Save as previous day if user wants
    if st.checkbox("이 결과를 '전일 기준'으로 저장 (다음 실행 시 자동 로드)", value=True):
        today_record = {
            "열쇠": afternoon_key,
            "교양_5교시": gy5 if gy5 else (gy4 if gy4 else (gy3 if gy3 else prev_gyoyang5)),
            "1종수동": aft_sudong if aft_sudong else last_sudong
        }
        try:
            with open(PREV_DAY_FILE, "w", encoding="utf-8") as f:
                json.dump(today_record, f, ensure_ascii=False, indent=2)
            st.success("전일근무.json에 저장했습니다.")
        except Exception as e:
            st.error("전일 저장 오류: " + str(e))
