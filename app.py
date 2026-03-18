import csv
import io
import json
import os
import textwrap
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import streamlit as st
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


APP_TITLE = "Inspector Equipment – Need List"
DATA_DIR = "data"
ITEMS_PATH = os.path.join(DATA_DIR, "items.json")
SUBMISSIONS_PATH = os.path.join(DATA_DIR, "submissions.csv")
DEFAULT_SEND_TO = "NICHOLAS.NABHOLZ@BEXAR.ORG"


@dataclass
class Item:
    label: str
    value_field: str = "none"   # "none" | "text" | "number" | "choice"
    choices: Optional[List[str]] = None


# ---------- Storage helpers ----------
def ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def load_items() -> List[Item]:
    ensure_data_dir()

    if not os.path.exists(ITEMS_PATH):
        with open(ITEMS_PATH, "w", encoding="utf-8") as f:
            json.dump({"items": []}, f, indent=2)

    with open(ITEMS_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)

    items: List[Item] = []
    for it in raw.get("items", []):
        label = str(it.get("label", "")).strip()
        value_field = str(it.get("value_field", "none")).strip().lower()
        choices = it.get("choices")

        if label:
            items.append(
                Item(
                    label=label,
                    value_field=value_field if value_field in {"none", "text", "number", "choice"} else "none",
                    choices=choices if isinstance(choices, list) else None,
                )
            )

    return items


def save_items(items: List[Item]) -> None:
    ensure_data_dir()
    payload = {
        "items": [
            {
                "label": i.label,
                "value_field": i.value_field,
                **({"choices": i.choices} if i.value_field == "choice" and i.choices else {}),
            }
            for i in items
        ]
    }
    with open(ITEMS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def ensure_submissions_file() -> None:
    ensure_data_dir()
    if not os.path.exists(SUBMISSIONS_PATH):
        with open(SUBMISSIONS_PATH, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["timestamp_utc", "inspector_name", "needed_json", "comment"])


def append_submission(inspector_name: str, needed: List[Dict[str, Any]], comment: str) -> None:
    ensure_submissions_file()
    ts = datetime.now(timezone.utc).isoformat()
    with open(SUBMISSIONS_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([ts, inspector_name.strip(), json.dumps(needed, ensure_ascii=False), comment.strip()])


def download_csv_button() -> None:
    if not os.path.exists(SUBMISSIONS_PATH):
        return

    with open(SUBMISSIONS_PATH, "rb") as f:
        st.download_button(
            label="Download submissions CSV",
            data=f.read(),
            file_name="submissions.csv",
            mime="text/csv",
            use_container_width=True,
        )


# ---------- PDF helpers ----------
def safe_filename(value: str) -> str:
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in (" ", "_", "-")).strip()
    cleaned = cleaned.replace(" ", "_")
    return cleaned or "receipt"


def wrap_text_lines(text: str, width: int = 90) -> List[str]:
    if not text:
        return [""]
    lines: List[str] = []
    for paragraph in str(text).splitlines() or [""]:
        wrapped = textwrap.wrap(paragraph, width=width) if paragraph else [""]
        lines.extend(wrapped)
    return lines or [""]


def create_receipt_pdf(
    inspector_name: str,
    needed: List[Dict[str, Any]],
    comment: str,
) -> tuple[str, bytes]:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    _, page_height = letter

    left_margin = 50
    top_y = page_height - 50
    y = top_y

    def new_page() -> None:
        nonlocal y
        pdf.showPage()
        y = top_y
        pdf.setFont("Helvetica", 11)

    def draw_line(line: str, font_name: str = "Helvetica", font_size: int = 11, gap: int = 16) -> None:
        nonlocal y
        if y < 60:
            new_page()
        pdf.setFont(font_name, font_size)
        pdf.drawString(left_margin, y, line)
        y -= gap

    pdf.setTitle("Equipment Request Receipt")

    draw_line("Equipment Request Receipt", font_name="Helvetica-Bold", font_size=16, gap=24)
    draw_line(f"Created: {datetime.now().strftime('%Y-%m-%d %I:%M %p')}")
    draw_line(f"Inspector: {inspector_name.strip()}", font_name="Helvetica-Bold")
    draw_line("")

    draw_line("Requested Equipment / Items", font_name="Helvetica-Bold", font_size=12, gap=18)

    if needed:
        for idx, entry in enumerate(needed, start=1):
            item_name = str(entry.get("item", "")).strip()
            item_value = entry.get("value", "")

            if item_value is None or str(item_value).strip() == "":
                line = f"{idx}. {item_name}"
                draw_line(line)
            else:
                line = f"{idx}. {item_name}: {item_value}"
                for wrapped in wrap_text_lines(line, width=88):
                    draw_line(wrapped)
    else:
        draw_line("No items selected.")

    draw_line("")
    draw_line("Comments", font_name="Helvetica-Bold", font_size=12, gap=18)

    if comment.strip():
        for wrapped in wrap_text_lines(comment.strip(), width=88):
            draw_line(wrapped)
    else:
        draw_line("None")

    pdf.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"equipment_receipt_{safe_filename(inspector_name)}_{timestamp}.pdf"
    return filename, pdf_bytes


# ---------- Business logic ----------
def is_truck_field(label: str) -> bool:
    l = label.strip().lower()
    return l in {"truck model year", "truck unit number"}


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="centered")

    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"] button[kind="secondary"],
        div.stButton > button {
            min-height: 52px !important;
            font-size: 16px !important;
            font-weight: 700 !important;
            border-radius: 10px !important;
        }

        div.stButton > button {
            white-space: nowrap !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title(APP_TITLE)

    items = load_items()

    params = st.query_params
    is_admin = str(params.get("admin", "0")).strip() == "1"

    if not is_admin:
        st.markdown(
            """
            <style>
              section[data-testid="stSidebar"] {display:none !important;}
              div[data-testid="collapsedControl"] {display:none !important;}
              header button {display:none !important;}
              .block-container {padding-left: 1rem !important; padding-right: 1rem !important;}
            </style>
            """,
            unsafe_allow_html=True,
        )

    if is_admin:
        with st.sidebar:
            st.header("Admin (No Password)")
            st.caption("Adds items to the bottom of the list.")

            with st.form("admin_add_item", clear_on_submit=True):
                new_label = st.text_input("Item name", placeholder="Example: EXTRA BATTERY PACK")
                value_field = st.selectbox(
                    "Optional right-side field",
                    options=["none", "text", "number", "choice"],
                    help="none = button only. text/number = small box. choice = dropdown.",
                )

                choice_text = ""
                if value_field == "choice":
                    choice_text = st.text_input(
                        "Choices (comma-separated)",
                        value="S, M, L, XL",
                        help="Example: S, M, L, XL, XXL",
                    )

                add_item = st.form_submit_button("Add item to bottom", use_container_width=True)

                if add_item:
                    if not new_label.strip():
                        st.error("Item name is required.")
                    else:
                        new_item = Item(label=new_label.strip(), value_field=value_field)
                        if value_field == "choice":
                            choices = [c.strip() for c in choice_text.split(",") if c.strip()]
                            new_item.choices = choices if choices else ["Option 1", "Option 2"]

                        items.append(new_item)
                        save_items(items)
                        st.success("Added.")
                        st.rerun()

            st.divider()
            st.subheader("Submissions (local CSV)")
            download_csv_button()

    inspector_name = st.text_input("Inspector Name (required)", placeholder="Type inspector name")
    st.markdown("Tap **NEED** for anything the inspector is missing. Leave it off if they do not need it.")
    st.divider()

    needed_results: List[Dict[str, Any]] = []
    truck_model_year_value = None
    truck_unit_number_value = None

    for idx, item in enumerate(items):
        col_need, col_value = st.columns([1.15, 3], vertical_alignment="center")
        need_key = f"need_{idx}"
        val_key = f"val_{idx}"

        with col_need:
            if need_key not in st.session_state:
                st.session_state[need_key] = False

            def toggle_need(k=need_key):
                st.session_state[k] = not st.session_state[k]

            is_on = st.session_state[need_key]
            btn_label = "✅ NEED" if is_on else "⬜ NEED"

            st.button(
                btn_label,
                key=f"btn_{need_key}",
                on_click=toggle_need,
                use_container_width=True,
                type="primary" if is_on else "secondary",
            )

            need_checked = st.session_state[need_key]

        with col_value:
            st.markdown(f"**{item.label}**")

            value: Any = None
            if item.value_field == "text":
                value = st.text_input("", key=val_key, label_visibility="collapsed", placeholder="Enter text")
            elif item.value_field == "number":
                value = st.number_input("", key=val_key, label_visibility="collapsed", step=1, format="%d")
            elif item.value_field == "choice":
                choices = item.choices or ["Option 1", "Option 2"]
                value = st.selectbox("", options=choices, key=val_key, label_visibility="collapsed")

        if item.value_field == "number" and item.label.strip().lower() == "truck model year":
            truck_model_year_value = st.session_state.get(val_key)

        if item.value_field == "number" and item.label.strip().lower() == "truck unit number":
            truck_unit_number_value = st.session_state.get(val_key)

        if need_checked and not is_truck_field(item.label):
            needed_results.append({"item": item.label, "value": value})

        st.divider()

    comment = st.text_area("Comments (optional)", height=120, placeholder="Type any notes here...")

    if "submitted" not in st.session_state:
        st.session_state.submitted = False
    if "last_pdf_bytes" not in st.session_state:
        st.session_state.last_pdf_bytes = None
    if "last_pdf_filename" not in st.session_state:
        st.session_state.last_pdf_filename = None
    if "last_success" not in st.session_state:
        st.session_state.last_success = False

    submit = st.button(
        "Submit",
        type="primary",
        use_container_width=True,
        disabled=st.session_state.submitted
    )

    if submit:
        st.session_state.submitted = True
        st.session_state.last_success = False
        st.session_state.last_pdf_bytes = None
        st.session_state.last_pdf_filename = None

        st.warning(
            " Submitting request... Please wait for confirmation. "
            "Do NOT refresh the page or press Submit again."
            "Scroll Down."
        )

        with st.spinner("Submitting request..."):
            if not inspector_name.strip():
                st.error("Inspector Name is required.")
                st.session_state.submitted = False
                st.stop()

            final_needed = list(needed_results)

            if truck_model_year_value not in (None, 0, "0", ""):
                final_needed.append({"item": "TRUCK MODEL YEAR", "value": int(truck_model_year_value)})

            if truck_unit_number_value not in (None, 0, "0", ""):
                final_needed.append({"item": "TRUCK UNIT NUMBER", "value": int(truck_unit_number_value)})

            clean_comment = comment.strip()

            try:
                append_submission(inspector_name, final_needed, clean_comment)
                pdf_filename, pdf_bytes = create_receipt_pdf(inspector_name, final_needed, clean_comment)

                st.session_state.last_pdf_filename = pdf_filename
                st.session_state.last_pdf_bytes = pdf_bytes
                st.session_state.last_success = True
            except Exception as e:
                st.error(f"Submit failed: {e}")
                st.session_state.submitted = False
                st.stop()

        st.success("Submitted successfully. SCROLL DOWN")
        st.info("Click Download PDF, then Email it")
        st.session_state.submitted = False

    if st.session_state.last_success and st.session_state.last_pdf_bytes and st.session_state.last_pdf_filename:
        st.download_button(
            label="CLICK TO DOWNLOAD PDF Receipt",
            data=st.session_state.last_pdf_bytes,
            file_name=st.session_state.last_pdf_filename,
            mime="application/pdf",
            use_container_width=True,
        )

        st.warning(f"ATTACH DOWNLOADED PDF AND EMAIL TO: {DEFAULT_SEND_TO}")


if __name__ == "__main__":
    main()
