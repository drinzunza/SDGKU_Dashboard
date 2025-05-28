import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta # Added timedelta
from streamlit_calendar import calendar
import re
import json
import os

st.set_page_config(layout="wide", page_title="Cohort & Unit Calendar")

CONFIG_FILE = "config.json"
MASTER_SCHEDULE_FILE = "master_schedule.csv"

# --- Configuration Management ---
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config_data = json.load(f)
                st.session_state.event_colors = config_data.get('event_colors', get_default_colors())
                st.session_state.teacher_assignments = config_data.get('teacher_assignments', {})
                st.session_state.all_known_teachers = set(config_data.get('all_known_teachers', []))
                return
        except Exception as e:
            st.error(f"Error loading {CONFIG_FILE}: {e}. Using defaults.")
    st.session_state.event_colors = get_default_colors()
    st.session_state.teacher_assignments = {}
    st.session_state.all_known_teachers = set()

def get_default_colors():
    return {
        "FSDI": "#1f77b4", "MDI1": "#ff7f0e", "MDI2": "#2ca02c",
        "ORIENTATION": "#d62728", "DEFAULT": "#7f7f7f"
    }

def save_config():
    config_data = {
        'event_colors': st.session_state.event_colors,
        'teacher_assignments': st.session_state.teacher_assignments,
        'all_known_teachers': sorted(list(st.session_state.all_known_teachers))
    }
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config_data, f, indent=4)
    except Exception as e:
        st.error(f"Error saving {CONFIG_FILE}: {e}")

if 'event_colors' not in st.session_state:
    load_config()

# --- Master Schedule Data Management ---
@st.cache_data(ttl=300) # Cache for 5 minutes to allow updates after changes
def load_master_schedule():
    if os.path.exists(MASTER_SCHEDULE_FILE):
        try:
            df = pd.read_csv(MASTER_SCHEDULE_FILE, dtype=str)
            if not all(col in df.columns for col in ['OriginalDateString', 'CohortName', 'UnitActivity']):
                 st.warning(f"{MASTER_SCHEDULE_FILE} is missing required columns.")
                 return pd.DataFrame(columns=['OriginalDateString', 'CohortName', 'UnitActivity', 'ParsedDate'])
            
            df['ParsedDate_temp'] = df['OriginalDateString'].apply(parse_master_schedule_date_string)
            df['ParsedDate'] = pd.to_datetime(df['ParsedDate_temp'], errors='coerce')
            df_cleaned = df.dropna(subset=['ParsedDate'])
            return df_cleaned[['OriginalDateString', 'CohortName', 'UnitActivity', 'ParsedDate']]
        except Exception as e:
            st.error(f"Error loading {MASTER_SCHEDULE_FILE}: {e}")
            return pd.DataFrame(columns=['OriginalDateString', 'CohortName', 'UnitActivity', 'ParsedDate'])
    return pd.DataFrame(columns=['OriginalDateString', 'CohortName', 'UnitActivity', 'ParsedDate'])

def parse_master_schedule_date_string(date_str):
    if pd.isna(date_str) or not str(date_str).strip(): return None
    date_str_clean = str(date_str).strip()
    try: return datetime.strptime(date_str_clean, "%m/%d/%Y").date()
    except ValueError:
        try: return datetime.strptime(date_str_clean, "%m/%d/%y").date()
        except ValueError: return None

def append_to_master_schedule(new_data_df):
    if new_data_df.empty: return
    try:
        expected_cols = ['OriginalDateString', 'CohortName', 'UnitActivity']
        if not all(col in new_data_df.columns for col in expected_cols):
            st.error("New data missing required columns.")
            return False
        if os.path.exists(MASTER_SCHEDULE_FILE):
            try:
                master_df = pd.read_csv(MASTER_SCHEDULE_FILE, dtype=str)
                if not all(col in master_df.columns for col in expected_cols):
                    st.warning(f"{MASTER_SCHEDULE_FILE} malformed. Overwriting.")
                    updated_df = new_data_df.copy()
                else:
                    updated_df = pd.concat([master_df, new_data_df], ignore_index=True)
            except pd.errors.EmptyDataError:
                updated_df = new_data_df.copy()
            except Exception as e_read:
                st.error(f"Read error for {MASTER_SCHEDULE_FILE}: {e_read}. Overwriting.")
                updated_df = new_data_df.copy()
        else:
            updated_df = new_data_df.copy()
        
        for col in expected_cols:
            if col in updated_df: updated_df[col] = updated_df[col].astype(str)
        updated_df.to_csv(MASTER_SCHEDULE_FILE, index=False)
        st.cache_data.clear() # Clear cache for load_master_schedule
        return True
    except Exception as e:
        st.error(f"Append error {MASTER_SCHEDULE_FILE}: {e}")
        return False

def parse_new_cohort_schedule_input(raw_text_input):
    lines = raw_text_input.strip().split('\n')
    if not lines: return pd.DataFrame()
    cohort_name = lines[0].strip()
    if not cohort_name:
        st.error("First line must be Cohort Name.")
        return pd.DataFrame()
    schedule_entries = []
    for line in lines[1:]:
        parts = line.strip().split('\t')
        date_str, unit_activity = None, ""
        if len(parts) == 3: date_str, unit_activity = parts[1].strip(), parts[2].strip()
        elif len(parts) == 2 and re.match(r'\d{1,2}/\d{1,2}/\d{2,4}', parts[0].strip()): # More flexible date match
             date_str, unit_activity = parts[0].strip(), parts[1].strip()
        
        if date_str:
            schedule_entries.append({
                'OriginalDateString': date_str, 'CohortName': cohort_name,
                'UnitActivity': unit_activity if unit_activity else ""
            })
    return pd.DataFrame(schedule_entries)

def get_actual_unit_from_cell(cell_value):
    if pd.isna(cell_value): return None
    cell_value_str = str(cell_value).strip()
    if not cell_value_str or cell_value_str.lower() in ["orientation", 'nan']: return None
    match = re.search(r'\b(\d{3})\b', cell_value_str)
    return match.group(1) if match else cell_value_str

def get_unit_type_for_color(unit_name_full):
    if pd.isna(unit_name_full) or not unit_name_full: return "DEFAULT"
    uname = str(unit_name_full).upper()
    if "FSDI" in uname: return "FSDI"
    if "MDI1" in uname or "MDI-1" in uname: return "MDI1"
    if "MDI2" in uname or "MDI-2" in uname: return "MDI2"
    if "ORIENTATION" in uname: return "ORIENTATION"
    return "DEFAULT"

def parse_teacher_assignment_data(raw_data):
    assignments = {}; current_cohort = None; teachers_found = set()
    for line in raw_data.splitlines():
        line = line.strip()
        if not line: continue
        if (line.upper().startswith("COHORT ") or "CH " in line.upper() or "CH." in line.upper()) and "\t" not in line and not re.match(r"^\d{3}\s", line): # Added CH.
            current_cohort = line; assignments[current_cohort] = {}
        elif current_cohort and ("\t" in line or len(line.split()) >= 2):
            parts = re.split(r'\s+|\t', line, 1)
            if len(parts) == 2:
                unit, teacher = parts[0].strip(), parts[1].strip()
                if unit and teacher:
                    unit_key = re.match(r'(\d+)', unit).group(1) if re.match(r'(\d+)', unit) else unit
                    assignments[current_cohort][unit_key] = teacher; teachers_found.add(teacher)
    return assignments, teachers_found

def generate_calendar_events_from_master(df_master, selected_cohorts, selected_units_full, selected_teachers, selected_year, selected_month):
    events = []
    if df_master is None or df_master.empty: return events
    if 'ParsedDate' not in df_master.columns or not pd.api.types.is_datetime64_any_dtype(df_master['ParsedDate']):
        st.error("ParsedDate column issue in master data for calendar.")
        return events
    try:
        df_month_year_filtered = df_master[
            (df_master['ParsedDate'].dt.year == selected_year) &
            (df_master['ParsedDate'].dt.month == selected_month)
        ]
    except AttributeError: st.error("Error accessing .dt on ParsedDate for calendar."); return events
    if df_month_year_filtered.empty: return events
    df_month = df_month_year_filtered[df_month_year_filtered['CohortName'].isin(selected_cohorts)]
    if df_month.empty: return events
        
    for index, row in df_month.iterrows():
        event_py_datetime_obj = row['ParsedDate']
        event_py_date_obj = event_py_datetime_obj.date()
        cohort_name = row['CohortName']; unit_activity_full = str(row['UnitActivity']).strip()
        actual_unit_activity_display = unit_activity_full if unit_activity_full else "No Activity"

        display_event = False
        if not selected_units_full: display_event = True
        elif actual_unit_activity_display.lower() == "orientation" and "Orientation" in selected_units_full: display_event = True
        elif actual_unit_activity_display in selected_units_full: display_event = True
        if not display_event: continue

        teacher_name = ""
        unit_key_teacher = get_actual_unit_from_cell(actual_unit_activity_display)
        if cohort_name in st.session_state.teacher_assignments and \
           unit_key_teacher in st.session_state.teacher_assignments[cohort_name]:
            teacher_name = st.session_state.teacher_assignments[cohort_name][unit_key_teacher]
        if selected_teachers and teacher_name not in selected_teachers:
            if not (not teacher_name and "Unassigned" in selected_teachers): continue

        title = f"{cohort_name}: {actual_unit_activity_display}"
        if teacher_name: title += f" ({teacher_name})"
        color = st.session_state.event_colors.get(get_unit_type_for_color(actual_unit_activity_display), st.session_state.event_colors["DEFAULT"])
        
        events.append({
            "title": title, "start": event_py_date_obj.strftime("%Y-%m-%d"), "color": color,
            "extendedProps": {"teacher": teacher_name, "cohort": cohort_name, "unit": actual_unit_activity_display}
        })
    return events

def prepare_data_for_table_view(df_master, selected_cohorts, selected_units_full, selected_teachers, start_date_table, end_date_table):
    if df_master is None or df_master.empty: return pd.DataFrame()
    if 'ParsedDate' not in df_master.columns or not pd.api.types.is_datetime64_any_dtype(df_master['ParsedDate']):
        st.error("ParsedDate column is missing or not in datetime format for table view.")
        return pd.DataFrame()
    if not start_date_table or not end_date_table:
        st.warning("Please select a valid date range for the table view.")
        return pd.DataFrame()

    # Filter by selected date range
    # Create a temporary column of Python date objects for comparison, if ParsedDate is Timestamp
    df_master_copy = df_master.copy() # Work on a copy to avoid SettingWithCopyWarning
    df_master_copy['ParsedDateAsDate'] = df_master_copy['ParsedDate'].dt.date

    try:
        df_filtered = df_master_copy[
            (df_master_copy['ParsedDateAsDate'] >= start_date_table) & # start_date_table is datetime.date
            (df_master_copy['ParsedDateAsDate'] <= end_date_table)   # end_date_table is datetime.date
        ]
    except Exception as e:
        st.error(f"Error filtering by date range for table view: {e}")
        return pd.DataFrame()
    
    # df_filtered = df_filtered.drop(columns=['ParsedDateAsDate']) # Can drop if not needed later

    if df_filtered.empty: return pd.DataFrame()
    df_filtered = df_filtered[df_filtered['CohortName'].isin(selected_cohorts)]
    if df_filtered.empty: return pd.DataFrame()

    table_data_rows = []
    for index, row in df_filtered.iterrows():
        event_py_date_obj = row['ParsedDate'].date() # Use .date() for consistency
        cohort_name = row['CohortName']
        unit_activity_full = str(row['UnitActivity']).strip()
        actual_unit_activity_display = unit_activity_full if unit_activity_full else "No Activity"

        display_event = False # Renamed for clarity
        if not selected_units_full: display_event = True
        elif actual_unit_activity_display.lower() == "orientation" and "Orientation" in selected_units_full: display_event = True
        elif actual_unit_activity_display in selected_units_full: display_event = True
        if not display_event: continue

        teacher_name = ""
        unit_key_teacher = get_actual_unit_from_cell(actual_unit_activity_display)
        if cohort_name in st.session_state.teacher_assignments and \
           unit_key_teacher in st.session_state.teacher_assignments[cohort_name]:
            teacher_name = st.session_state.teacher_assignments[cohort_name][unit_key_teacher]
        if selected_teachers and teacher_name not in selected_teachers:
            if not (not teacher_name and "Unassigned" in selected_teachers): continue

        cell_display = actual_unit_activity_display
        if teacher_name: cell_display += f" ({teacher_name})"
        
        table_data_rows.append({'Date': event_py_date_obj, 'CohortName': cohort_name, 'Activity': cell_display})

    if not table_data_rows: return pd.DataFrame()
    df_for_pivot = pd.DataFrame(table_data_rows)
    if df_for_pivot.empty: return pd.DataFrame()

    try:
        pivot_df = df_for_pivot.pivot_table(
            index='Date', columns='CohortName', values='Activity',
            aggfunc=lambda x: ' / '.join(sorted(list(set(x))))
        ).reset_index()
    except Exception as e:
        st.error(f"Error pivoting data for table view: {e}"); return pd.DataFrame()

    pivot_df = pivot_df.sort_values(by='Date')
    pivot_df['Date'] = pivot_df['Date'].apply(lambda x: x.strftime('%a, %m/%d/%Y') if pd.notna(x) else '')
    return pivot_df.fillna('')

# --- Main Application ---
master_schedule_df = load_master_schedule()

# --- SIDEBAR DEFINITIONS (MUST BE HERE TO BE ACCESSIBLE BY ALL TABS) ---
st.sidebar.title("🗓️ Filters & Controls")

# Initialize filter variables that will be set by sidebar widgets
selected_year_cal, selected_month_cal, selected_month_year_str_cal = 0, 0, ""
table_view_start_date_widget, table_view_end_date_widget = None, None # For table view date range from widget
selected_cohorts_global, selected_units_global, selected_teachers_global = [], [], []


if master_schedule_df is not None and not master_schedule_df.empty and \
   'ParsedDate' in master_schedule_df and pd.api.types.is_datetime64_any_dtype(master_schedule_df['ParsedDate']) and \
   not master_schedule_df['ParsedDate'].isnull().all():

    all_cohort_names_master = sorted(master_schedule_df['CohortName'].astype(str).unique())
    min_date_master_ts = master_schedule_df['ParsedDate'].min() # pandas Timestamp
    max_date_master_ts = master_schedule_df['ParsedDate'].max() # pandas Timestamp
    
    min_data_py_date = min_date_master_ts.date() if pd.notna(min_date_master_ts) else date.today() - timedelta(days=365)
    max_data_py_date = max_date_master_ts.date() if pd.notna(max_date_master_ts) else date.today()


    st.sidebar.markdown("### 📅 Calendar View")
    available_year_months = []
    if pd.notna(min_date_master_ts) and pd.notna(max_date_master_ts):
        min_date_py_loop = min_date_master_ts.date()
        max_date_py_loop = max_date_master_ts.date()
        current_loop_date_py = min_date_py_loop
        while current_loop_date_py <= max_date_py_loop:
            ym = (current_loop_date_py.year, current_loop_date_py.month)
            if ym not in available_year_months: available_year_months.append(ym)
            if current_loop_date_py.month == 12:
                if current_loop_date_py.year + 1 > max_date_py_loop.year: break
                current_loop_date_py = date(current_loop_date_py.year + 1, 1, 1)
            else:
                if current_loop_date_py.year == max_date_py_loop.year and current_loop_date_py.month + 1 > max_date_py_loop.month: break
                current_loop_date_py = date(current_loop_date_py.year, current_loop_date_py.month + 1, 1)
    
    if not available_year_months:
        st.sidebar.warning("No date range for calendar month selection.")
    else:
        month_year_options = { f"{datetime(year, month, 1).strftime('%B %Y')}": (year, month) for year, month in available_year_months }
        default_ym_str = f"{datetime(min_data_py_date.year, min_data_py_date.month, 1).strftime('%B %Y')}"
        current_dt_now = datetime.now()
        current_month_year_now_str = f"{datetime(current_dt_now.year, current_dt_now.month, 1).strftime('%B %Y')}"
        if current_month_year_now_str in month_year_options: default_ym_str = current_month_year_now_str
        default_index_cal = list(month_year_options.keys()).index(default_ym_str) if default_ym_str in month_year_options else 0
        
        selected_month_year_str_cal = st.sidebar.selectbox(
            "Select Month (Calendar):", options=list(month_year_options.keys()),
            index=default_index_cal, key="global_month_year_select"
        )
        selected_year_cal, selected_month_cal = month_year_options[selected_month_year_str_cal]

    st.sidebar.markdown("### 🗓️ Table View")
    # Default table view range to the selected calendar month initially
    default_table_start = datetime(selected_year_cal, selected_month_cal, 1).date() if selected_year_cal else min_data_py_date
    next_cal_month = selected_month_cal + 1 if selected_month_cal < 12 else 1
    next_cal_year = selected_year_cal if selected_month_cal < 12 else selected_year_cal + 1
    default_table_end = (datetime(next_cal_year, next_cal_month, 1) - timedelta(days=1)).date() if selected_year_cal else max_data_py_date
    
    # Ensure defaults are within the master schedule's overall range
    default_table_start = max(default_table_start, min_data_py_date)
    default_table_end = min(default_table_end, max_data_py_date)

    table_date_range_selected = st.sidebar.date_input(
        "Select Date Range (Table):",
        value=(default_table_start, default_table_end),
        min_value=min_data_py_date,
        max_value=max_data_py_date,
        key="global_table_date_range"
    )
    if len(table_date_range_selected) == 2:
        table_view_start_date_widget, table_view_end_date_widget = table_date_range_selected
    else: # Fallback if only one date is somehow returned by widget
        table_view_start_date_widget = table_date_range_selected[0] if table_date_range_selected else default_table_start
        table_view_end_date_widget = table_date_range_selected[0] if table_date_range_selected else default_table_end


    st.sidebar.markdown("### 🎓 Common Filters")
    
    all_unit_activities_master = sorted(master_schedule_df['UnitActivity'].astype(str).replace('nan','', regex=False).dropna().unique())
    all_unit_activities_master = [u for u in all_unit_activities_master if u.strip() and u.lower() != 'orientation']
    units_for_global_ui = ["Orientation"] + all_unit_activities_master # Renamed for clarity
    selected_units_global = st.sidebar.multiselect(
        "Filter by Unit:", options=sorted(list(set(units_for_global_ui))), default=[],
        key="global_unit_ms"
    )
    teacher_filter_options_global = ["Unassigned"] + sorted(list(st.session_state.all_known_teachers)) # Renamed for clarity
    selected_teachers_global = st.sidebar.multiselect(
        "Filter by Teacher:", options=teacher_filter_options_global, default=[],
        key="global_teacher_ms"
    )

    selected_cohorts_global = st.sidebar.multiselect(
        "Select Cohorts:", options=all_cohort_names_master, default=all_cohort_names_master,
        key="global_cohort_ms"
    )
else:
    st.sidebar.info("Load or add data to enable filters.")

# --- TABS DEFINITION ---
tab_calendar, tab_table_view, tab_data_management, tab_config = st.tabs([
    "📅 Calendar View", "🗓️ Table View", "💾 Data Management", "⚙️ Configuration"
])

# --- TAB CONTENT ---
with tab_calendar:
    st.header("📅 SDGKU Class Calendar")
    if master_schedule_df is not None and not master_schedule_df.empty and selected_year_cal and selected_month_cal:
        if not selected_cohorts_global:
            st.info("Please select at least one cohort in the sidebar.")
        else:
            st.subheader(f"Schedule for {selected_month_year_str_cal}")
            calendar_events = generate_calendar_events_from_master(
                master_schedule_df.copy(), selected_cohorts_global, selected_units_global, 
                selected_teachers_global, selected_year_cal, selected_month_cal
            )
            if not calendar_events: st.info(f"No events match criteria for this month.")
            
            calendar_options_dict = {
                "headerToolbar": { "left": "", "center": "title", "right": "dayGridMonth,timeGridWeek" }, # Keep view switcher, title only
                "initialView": "dayGridMonth", "height": "800px", "selectable": True,
                 "initialDate": f"{selected_year_cal}-{selected_month_cal:02d}-01",
            }
            custom_css_cal = """
                .fc-event-main { white-space: normal !important; overflow: hidden; text-overflow: ellipsis; font-size: 0.85em; line-height: 1.2; }
                .fc-event { margin-bottom: 2px !important; padding: 1px 3px !important; border-radius: 4px; }
            """
            st.markdown(f"<style>{custom_css_cal}</style>", unsafe_allow_html=True)
            key_suffix_cal = f"{selected_year_cal}-{selected_month_cal}-{'_'.join(sorted(selected_cohorts_global))}-{'_'.join(sorted(selected_units_global))}-{'_'.join(sorted(selected_teachers_global))}"
            calendar_render_key = f"main_cal_v_{key_suffix_cal}".replace(" ","_").replace("(","_").replace(")","_").replace(".","_").replace("-","_").replace(":","").replace(",","")
            calendar_output_dict = calendar( events=calendar_events, options=calendar_options_dict, key=calendar_render_key )
    else:
        st.info("Master schedule is empty or filters not set. Add data or select filters in sidebar.")

with tab_table_view:
    st.header("🗓️ Schedule Table View")
    if master_schedule_df is not None and not master_schedule_df.empty and \
       table_view_start_date_widget and table_view_end_date_widget: # Use the date range from widget

        if not selected_cohorts_global:
            st.info("Please select at least one cohort in the sidebar.")
        else:
            st.subheader(f"Schedule Table from {table_view_start_date_widget.strftime('%B %d, %Y')} to {table_view_end_date_widget.strftime('%B %d, %Y')}")
            table_df = prepare_data_for_table_view(
                master_schedule_df.copy(),
                selected_cohorts_global,
                selected_units_global,
                selected_teachers_global,
                table_view_start_date_widget, # Pass the selected start date for table
                table_view_end_date_widget    # Pass the selected end date for table
            )
            if not table_df.empty:
                st.dataframe(table_df, use_container_width=True, height=600)
            else:
                st.info("No data matches filter criteria for the table view in the selected date range.")
    elif master_schedule_df is None or master_schedule_df.empty:
        st.info("Master schedule is empty. Add data via 'Data Management' tab.")
    else:
        st.info("Please select a valid date range in the sidebar for the table view.")

with tab_config:
    st.header("Event Color Configuration")
    cols_color_cfg = st.columns(len(st.session_state.event_colors)) # Renamed variable
    color_keys_cfg = list(st.session_state.event_colors.keys()) # Renamed variable
    config_changed_colors_cfg = False # Renamed variable
    for i, key_cfg in enumerate(color_keys_cfg): # Renamed variable
        new_color_cfg = cols_color_cfg[i].color_picker(f"{key_cfg} Color", st.session_state.event_colors[key_cfg], key=f"color_cfg_{key_cfg}") # Renamed variable
        if new_color_cfg != st.session_state.event_colors[key_cfg]:
            st.session_state.event_colors[key_cfg] = new_color_cfg
            config_changed_colors_cfg = True
    
    st.header("Teacher Assignments")
    st.markdown("Paste: COHORT_NAME_EXACT_FROM_SCHEDULE then UNIT_NUM Teacher")
    teacher_data_input_area_cfg = st.text_area("Teacher Assignment Data:", height=300, key="teacher_config_input_area_cfg") # Renamed variable
    config_changed_teachers_cfg = False # Renamed variable
    if st.button("Update Teacher Assignments From Text", key="update_teacher_config_btn_cfg"): # Renamed key
        if teacher_data_input_area_cfg:
            parsed_assignments, teachers_found = parse_teacher_assignment_data(teacher_data_input_area_cfg)
            st.session_state.teacher_assignments.update(parsed_assignments)
            st.session_state.all_known_teachers.update(teachers_found)
            config_changed_teachers_cfg = True
            st.success("Teacher assignments updated from text!")
        else: st.warning("No teacher data pasted.")
    
    if config_changed_colors_cfg or config_changed_teachers_cfg:
        save_config()

    if st.session_state.teacher_assignments:
        with st.expander("Current Teacher Assignments (from config)"):
            st.json(st.session_state.teacher_assignments)

with tab_data_management:
    st.header("Add New Cohort Schedule Data")
    st.markdown("""Paste: COHORT_NAME then DayOfWeek<Tab>MM/DD/YYYY<Tab>UnitActivity""")
    new_schedule_input_area_dm = st.text_area("Paste New Schedule Data Here:", height=400, key="new_schedule_text_area_input_dm") # Renamed variable
    if st.button("Add This Schedule to Master File", key="add_new_schedule_btn_dm"): # Renamed key
        if new_schedule_input_area_dm:
            new_df = parse_new_cohort_schedule_input(new_schedule_input_area_dm)
            if not new_df.empty:
                if append_to_master_schedule(new_df):
                    st.success(f"Added {len(new_df)} entries for '{new_df['CohortName'].iloc[0]}' to {MASTER_SCHEDULE_FILE}.")
                    master_schedule_df = load_master_schedule() # Crucial: Reload df for current session
                else: st.error("Failed to add data.")
            else: st.warning("No valid data parsed from input.")
        else: st.warning("No schedule data pasted.")
            
    st.subheader(f"Current Master Schedule ({MASTER_SCHEDULE_FILE})")
    if not master_schedule_df.empty:
        st.caption(f"Total entries: {len(master_schedule_df)}")
        st.dataframe(master_schedule_df.tail(100))
    else: st.caption(f"{MASTER_SCHEDULE_FILE} is empty or not found.")