import csv
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
import streamlit as st


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


# ---------- Secrets + Webhook ----------
def get_secret(name: str) -> Optional[str]:
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.getenv(name)


def send_to_gsheet_webhook(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Posts to your Apps Script Web App.
    Expected response JSON:
      { ok: true, name: "...", spreadsheet_id: "..." }
      or { ok: false, error: "..." }
    """
    url = get_secret("GSHEET_WEBHOOK_URL")
    if not url:
        return False, "Missing GSHEET_WEBHOOK_URL in Streamlit Secrets."

    try:
        resp = requests.post(url, json=payload, timeout=25)
        if resp.status_code != 200:
            return False, f"Webhook HTTP {resp.status_code}: {resp.text}"

        # Apps Script should return JSON
        data = resp.json()
        if not data.get("ok"):
            return False, f"Webhook error: {data.get('error')}"

        return True, f"Created Google Sheet: {data.get('name')}"
    except Exception as e:
        return False, f"Webhook request failed: {e}"


# ---------- Business logic ----------
def is_truck_field(label: str) -> bool:
    l = label.strip().lower()
    return l in {"truck model year", "truck unit number"}


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
            st.subheader("Submissions (local CSV)")
            download_csv_button()

            st.divider()
            st.subheader("Google Sheet Webhook")
            st.caption("Creates a new Google Sheet file in your Drive folder per Submit.")
            st.text(f"GSHEET_WEBHOOK_URL: {'set' if get_secret('GSHEET_WEBHOOK_URL') else '(not set)'}")

    # ---- Inspector form fields ----
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
if "submitted" not in st.session_state:
    st.session_state.submitted = False

submit = st.button(
    "Submit",
    type="primary",
    use_container_width=True,
    disabled=st.session_state.submitted
)

if submit:

    st.session_state.submitted = True

    st.warning(
        "Submitting request... Please wait for confirmation. "
        "Do NOT refresh the page or press Submit again."
    )

    with st.spinner("Submitting request to system..."):

        if not inspector_name.strip():
            st.error("Inspector Name is required.")
            st.session_state.submitted = False
            st.stop()

        final_needed = list(needed_results)

        # Include truck fields only if user actually entered them (number_input defaults to 0)
        if truck_model_year_value not in (None, 0, "0", ""):
            final_needed.append({"item": "TRUCK MODEL YEAR", "value": int(truck_model_year_value)})

        if truck_unit_number_value not in (None, 0, "0", ""):
            final_needed.append({"item": "TRUCK UNIT NUMBER", "value": int(truck_unit_number_value)})

        clean_comment = comment.strip()

        # Local CSV save (optional; Streamlit Cloud storage may be temporary)
        append_submission(inspector_name, final_needed, clean_comment)

        # Create a NEW Google Sheet file in your Drive folder
        payload = {
            "inspector_name": inspector_name.strip(),
            "comment": clean_comment,
            "items": final_needed,
        }
        ok, msg = send_to_gsheet_webhook(payload)

        if ok:
            st.success("Submitted successfully. " + msg)
        else:
            st.error("Submit failed. " + msg)


if __name__ == "__main__":
    main()
