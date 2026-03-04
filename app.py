import csv
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

# ---- Optional email support (SendGrid) ----
try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail
except Exception:
    SendGridAPIClient = None
    Mail = None


APP_TITLE = "Inspector Equipment – Need List"
DATA_DIR = "data"
ITEMS_PATH = os.path.join(DATA_DIR, "items.json")
SUBMISSIONS_PATH = os.path.join(DATA_DIR, "submissions.csv")


@dataclass
class Item:
    label: str
    value_field: str = "none"   # "none" | "text" | "number" | "choice"
    choices: Optional[List[str]] = None


# ---------- Storage helpers ----------
def ensure_data_dir():
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
        items.append(
            Item(
                label=str(it.get("label", "")).strip(),
                value_field=str(it.get("value_field", "none")).strip().lower(),
                choices=it.get("choices"),
            )
        )

    return [i for i in items if i.label]


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


def ensure_submissions_file():
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


def download_csv_button():
    if not os.path.exists(SUBMISSIONS_PATH):
        return
    with open(SUBMISSIONS_PATH, "rb") as f:
        st.download_button(
            label="Download submissions CSV",
            data=f,
            file_name="submissions.csv",
            mime="text/csv",
            use_container_width=True,
        )


# ---------- Email helpers ----------
def get_secret(name: str) -> Optional[str]:
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.getenv(name)


def send_email_sendgrid(subject: str, body_text: str) -> Tuple[bool, str]:
    api_key = get_secret("SENDGRID_API_KEY")
    from_email = get_secret("FROM_EMAIL")
    to_email = get_secret("TO_EMAIL") or "nicholas.nabholz@bexar.org"

    if not api_key or not from_email:
        return False, "Email not configured. Missing SENDGRID_API_KEY and/or FROM_EMAIL in secrets/env."

    if SendGridAPIClient is None or Mail is None:
        return False, "SendGrid library not available. Add sendgrid to requirements.txt."

    try:
        message = Mail(
            from_email=from_email,
            to_emails=to_email,
            subject=subject,
            plain_text_content=body_text,
        )
        sg = SendGridAPIClient(api_key)
        resp = sg.send(message)
        if 200 <= resp.status_code < 300:
            return True, f"Email sent to {to_email}."
        return False, f"SendGrid returned status {resp.status_code}."
    except Exception as e:
        return False, f"Email error: {e}"


# ---------- Business logic ----------
def is_truck_field(label: str) -> bool:
    l = label.strip().lower()
    return l in {"truck model year", "truck unit number"}


def build_email(inspector_name: str, needed_rows: List[Dict[str, Any]], comment: str) -> Tuple[str, str]:
    ts_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = f"Inspector Equipment NEED List – {inspector_name} – {ts_local}"

    lines = []
    lines.append(f"Inspector: {inspector_name}")
    lines.append(f"Submitted: {ts_local}")
    lines.append("")
    lines.append("NEEDED ITEMS:")

    if not needed_rows:
        lines.append("None selected.")
    else:
        for row in needed_rows:
            label = row.get("item", "")
            value = row.get("value", None)
            if value is None or str(value).strip() == "":
                lines.append(f"- {label}")
            else:
                lines.append(f"- {label}: {value}")

    if comment.strip():
        lines.append("")
        lines.append("COMMENT:")
        lines.append(comment.strip())

    return subject, "\n".join(lines)


def main():
    st.set_page_config(page_title=APP_TITLE, layout="centered")
    st.title(APP_TITLE)

    items = load_items()

    # ---- Admin flag via URL ----
    params = st.query_params
    is_admin = str(params.get("admin", "0")).strip() == "1"

    # ---- Hide sidebar completely for non-admin users ----
    if not is_admin:
        st.markdown(
            """
            <style>
              section[data-testid="stSidebar"] {display:none !important;}
              div[data-testid="collapsedControl"] {display:none !important;}
              header button {display:none !important;}
              .block-container {padding-left: 1rem !important;}
            </style>
            """,
            unsafe_allow_html=True,
        )

    # ---- Sidebar admin (ONLY for admin link) ----
    if is_admin:
        with st.sidebar:
            st.header("Admin (No Password)")
            st.caption("Adds items to the bottom of the list.")

            with st.form("admin_add_item", clear_on_submit=True):
                new_label = st.text_input("Item name", placeholder="Example: EXTRA BATTERY PACK")
                value_field = st.selectbox(
                    "Optional right-side field",
                    options=["none", "text", "number", "choice"],
                    help="none = checkbox only. text/number = small box. choice = dropdown.",
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
            st.subheader("Submissions")
            download_csv_button()

            st.divider()
            st.subheader("Email Settings")
            st.caption("Uses SendGrid. Configure via Streamlit Secrets.")
            st.text(f"TO_EMAIL: {get_secret('TO_EMAIL') or 'nicholas.nabholz@bexar.org'}")
            st.text(f"FROM_EMAIL: {get_secret('FROM_EMAIL') or '(not set)'}")
            st.text(f"SENDGRID_API_KEY: {'set' if get_secret('SENDGRID_API_KEY') else '(not set)'}")

    # ---- Inspector form fields (always visible) ----
    inspector_name = st.text_input("Inspector Name (required)", placeholder="Type inspector name")
    st.markdown("Check **NEED** for anything the inspector is missing. Leave unchecked if they don’t need it.")
    st.divider()

    # ---- Render vertical list ----
    needed_results: List[Dict[str, Any]] = []
    truck_model_year_value = None
    truck_unit_number_value = None

    for idx, item in enumerate(items):
        col_need, col_value = st.columns([1, 3], vertical_alignment="center")
        need_key = f"need_{idx}"
        val_key = f"val_{idx}"

        with col_need:
            need_checked = st.checkbox("NEED", key=need_key)

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

        # Capture truck fields (number inputs) by label
        if item.value_field == "number" and item.label.strip().lower() == "truck model year":
            truck_model_year_value = st.session_state.get(val_key)
        if item.value_field == "number" and item.label.strip().lower() == "truck unit number":
            truck_unit_number_value = st.session_state.get(val_key)

        # Only include checked items (except truck fields handled below)
        if need_checked and not is_truck_field(item.label):
            needed_results.append({"item": item.label, "value": value})

        st.divider()

    # ---- Comment box at end ----
    comment = st.text_area("Comments (optional)", height=120, placeholder="Type any notes here...")

    # ---- Submit button ----
    submit = st.button("Submit", type="primary", use_container_width=True)

    if submit:
        if not inspector_name.strip():
            st.error("Inspector Name is required.")
            st.stop()

        final_needed = list(needed_results)

        # Include truck fields only if user actually entered them (number_input defaults to 0)
        if truck_model_year_value not in (None, 0, "0", ""):
            final_needed.append({"item": "TRUCK MODEL YEAR", "value": int(truck_model_year_value)})

        if truck_unit_number_value not in (None, 0, "0", ""):
            final_needed.append({"item": "TRUCK UNIT NUMBER", "value": int(truck_unit_number_value)})

        clean_comment = comment.strip()

        append_submission(inspector_name, final_needed, clean_comment)

        subject, body = build_email(inspector_name, final_needed, clean_comment)
        ok, msg = send_email_sendgrid(subject, body)

        if ok:
            st.success("Submitted successfully. " + msg)
        else:
            st.warning("Submitted and saved locally, but email failed. " + msg)

        with st.expander("Preview submission (what was sent)"):
            st.code(body)


if __name__ == "__main__":
    main()
