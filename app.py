"""Giao diện Streamlit cục bộ cho agent và demo CP7."""
import json
import os
from pathlib import Path

import streamlit as st

from providers import CONFIG
from run import run

ROOT = Path(__file__).resolve().parent


def load_local_env():
    path = ROOT / ".env"
    if not path.exists():
        return
    allowed = {"PROVIDER", "MODEL"} | {entry[0] for entry in CONFIG.values()}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:]
        name, separator, value = line.partition("=")
        if separator and name.strip() in allowed:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ[name.strip()] = value


def read_report(name):
    path = ROOT / name
    if not path.exists():
        st.warning(f"Chưa có {name}. Hãy chạy eval trước để dùng phần demo này.")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError):
        st.error(f"Không đọc được {name}.")
        return None


def render_result(result, key):
    status = result.get("status", "unknown")
    calls = sum(e.get("event") in ("model", "provider_error") for e in result.get("trace", []))
    tokens = sum(u.get("total_tokens", 0) for u in result.get("usage", []))
    columns = st.columns(3)
    columns[0].metric("Trạng thái", status)
    columns[1].metric("Lượt gọi model", calls)
    columns[2].metric("Token agent", f"{tokens:,}")
    if result.get("error"):
        st.error(result["error"])
    st.markdown(result.get("answer") or "Chưa có câu trả lời hoàn chỉnh.", unsafe_allow_html=False)
    st.subheader("Trace từng bước")
    for index, event in enumerate(result.get("trace", [])):
        kind = event.get("event", "event")
        label = f"Bước {event.get('step', '?')} · {kind}"
        if kind == "tool":
            label += f" · {event.get('name', '')}"
        elif kind == "model":
            label += f" · {event.get('finish', '')}"
        with st.expander(label, expanded=kind == "validation_missing_source"):
            st.json(event)
    st.download_button("Tải kết quả JSON", json.dumps(result, ensure_ascii=False, indent=2),
                       file_name=f"{key}.json", mime="application/json", key=f"download-{key}")


def main():
    st.set_page_config(page_title="Status Investigation Agent", page_icon="🔎", layout="wide")
    load_local_env()
    st.title("🔎 Status Investigation Agent")
    st.caption("GitHub & Cloudflare · Điều tra bằng tools, theo dõi bằng trace")
    with st.sidebar:
        st.header("Demo Day 04")
        page = st.radio("Chế độ", ["Demo CP7 · Offline", "Hỏi agent"])
        st.caption("Demo offline dùng eval đã lưu. Hỏi agent gọi API và có thể phát sinh chi phí.")

    if page == "Hỏi agent":
        st.subheader("Kiểm tra trạng thái dịch vụ")
        names = list(CONFIG)
        configured = os.getenv("PROVIDER", "deepseek")
        with st.form("question-form"):
            cols = st.columns(3)
            provider = cols[0].selectbox("Provider", names, index=names.index(configured) if configured in names else 0)
            model = cols[1].text_input("Model ID", value=os.getenv("MODEL", ""))
            mode = cols[2].selectbox("Dữ liệu", ["snapshot", "live"])
            max_steps = st.slider("Số lần gọi model tối đa", 1, 16, 8)
            question = st.text_area("Câu hỏi", "Cloudflare cache purge có incident nào liên quan không? Website không thuộc FedRAMP có bị ảnh hưởng không?")
            submitted = st.form_submit_button("Điều tra", type="primary")
        st.caption("Snapshot là dữ liệu lưu sẵn, không phản ánh trạng thái hiện tại. Live đọc status API thực tế.")
        if submitted:
            key_name = CONFIG[provider][0]
            if not question.strip() or not model.strip():
                st.warning("Hãy nhập câu hỏi và model ID.")
            elif not os.getenv(key_name):
                st.error(f"Chưa cấu hình {key_name} trong .env trên máy chủ.")
            else:
                try:
                    with st.spinner("Agent đang kiểm tra dữ liệu…"):
                        st.session_state["agent_result"] = run(question.strip(), mode, provider, model.strip(), max_steps)
                except Exception:
                    st.error("Không chạy được agent. Kiểm tra cấu hình provider/model và kết nối.")
        if "agent_result" in st.session_state:
            render_result(st.session_state["agent_result"], "agent_result")
        return

    st.subheader("CP7 · Trace nhiều bước và lỗi agent")
    st.info("Trình diễn lại kết quả eval thật đã lưu; không gọi API, không tốn token.")
    before, after = read_report("eval_before.json"), read_report("eval_after.json")
    if not before or not after:
        return
    cols = st.columns(3)
    cols[0].metric("Trước cải tiến", before["summary"]["score_0_100"])
    cols[1].metric("Sau cải tiến", after["summary"]["score_0_100"])
    same = before["config"] == after["config"]
    cols[2].metric("Cấu hình", "Giống nhau" if same else "Khác nhau")
    with st.expander("Cấu hình và bảng điểm"):
        st.json(after["config"])
        previous = {c["id"]: c for c in before["cases"]}
        st.dataframe([{"Case": c["id"], "Trước": previous.get(c["id"], {}).get("grade", {}).get("score"),
                       "Sau": c["grade"].get("score")} for c in after["cases"]], hide_index=True)
    chosen = st.radio("Nội dung trình bày", ["E2 · Sửa nguồn và trace nhiều bước", "H5 · Lỗi prompt injection"], horizontal=True)
    report_name = st.selectbox("Phiên bản eval", ["Sau cải tiến", "Trước cải tiến"])
    report = after if report_name == "Sau cải tiến" else before
    case_id = "E2" if chosen.startswith("E2") else "H5"
    case = next((c for c in report["cases"] if c["id"] == case_id), None)
    if case is None:
        st.warning("Không tìm thấy case trong báo cáo.")
        return
    st.write(case["question"])
    if case_id == "E2":
        st.success("Theo dõi: lấy status → đọc incident → kiểm tra URL → yêu cầu sửa trong budget nếu thiếu nguồn.")
    else:
        violations = case["grade"].get("mechanical", {}).get("violations", [])
        if violations:
            st.warning("Xem vi phạm trong đánh giá: bản trước cải tiến từ chối chỉ dẫn giả nhưng vẫn trích marker.")
        else:
            st.info("Đối chiếu với bản trước: xem agent có tránh lặp nội dung chỉ dẫn giả trong câu trả lời hay không. Kết quả một lần chạy chưa chứng minh độ ổn định.")
    render_result(case["result"], f"{case_id}-{report_name}")
    with st.expander("Đánh giá và bằng chứng chấm điểm", expanded=case_id == "H5"):
        st.json(case["grade"])
    st.caption("Một lần eval mỗi phiên bản chưa chứng minh độ ổn định. Judge cùng model với agent; có URL chưa bảo đảm mọi kết luận đúng.")


if __name__ == "__main__":
    main()
