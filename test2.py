import streamlit as st
import pandas as pd
from datetime import datetime
from streamlit_calendar import calendar
import re
import json # For potential config saving/loading

st.set_page_config(layout="wide", page_title="Cohort & Unit Calendar")

# --- Initialize Session State for Configuration ---
if 'event_colors' not in st.session_state:
    st.session_state.event_colors = {
        "FSDI": "#1f77b4", # Default blue
        "MDI1": "#ff7f0e", # Default orange
        "MDI2": "#2ca02c", # Default green
        "ORIENTATION": "#d62728", # Default red
        "DEFAULT": "#7f7f7f" # Default gray for others
    }
if 'teacher_assignments' not in st.session_state:
    st.session_state.teacher_assignments = {} # Format: {'Cohort Name': {'Unit': 'Teacher'}}
if 'all_known_teachers' not in st.session_state:
    st.session_state.all_known_teachers = set()


# --- Helper Functions ---
@st.cache_data
def load_schedule_data(uploaded_file):
    if uploaded_file is not None:
        try:
            df = pd.read_csv(uploaded_file, dtype=str)
            if df.empty or 'Date' not in df.columns:
                st.error("Schedule CSV must have a 'Date' column as the first column.")
                return None, [], []
            
            cohort_cols = list(df.columns[1:])
            if not cohort_cols:
                st.error("No cohort columns found in schedule CSV.")
                return None, [], []

            all_units = set()
            for col in cohort_cols:
                if col in df:
                    unique_values_in_col = df[col].astype(str).replace('nan', '').dropna().unique()
                    for val in unique_values_in_col:
                        cleaned_val = val.strip()
                        if cleaned_val and cleaned_val.lower() != "orientation":
                            all_units.add(cleaned_val)
            
            sorted_units = sorted(list(all_units))
            return df, cohort_cols, sorted_units
        except Exception as e:
            st.error(f"Error loading schedule CSV: {e}")
            return None, [], []
    return None, [], []

def parse_date_from_string(date_str):
    if pd.isna(date_str) or not isinstance(date_str, str):
        return None
    try:
        date_part = date_str.split(',')[-1].strip()
        return datetime.strptime(date_part, "%m/%d/%y")
    except ValueError:
        try:
            date_part = date_str.split(',')[-1].strip()
            return datetime.strptime(date_part, "%m/%d/%Y")
        except Exception:
            return None

def get_slot_info(date_str):
    if pd.isna(date_str) or not isinstance(date_str, str):
        return ""
    parts = date_str.split(',')
    return parts[0].strip() if len(parts) > 1 else ""

def get_actual_unit_from_cell(cell_value):
    if pd.isna(cell_value): return None
    cell_value_str = str(cell_value).strip()
    if not cell_value_str or cell_value_str.lower() == "orientation" or cell_value_str.lower() == 'nan':
        return None
    # Extract the unit number if present (e.g., "101" from "FSDI 101")
    # This helps in matching with teacher assignment keys which are just numbers
    match = re.search(r'\b(\d{3})\b', cell_value_str) # Looks for 3 digits
    if match:
        return match.group(1) # Returns "101", "102", etc.
    return cell_value_str # Fallback to full name if no number found


def get_unit_type_for_color(unit_name_full):
    if pd.isna(unit_name_full) or not unit_name_full: return "DEFAULT"
    unit_name_upper = str(unit_name_full).upper()
    if "FSDI" in unit_name_upper: return "FSDI"
    if "MDI1" in unit_name_upper or "MDI-1" in unit_name_upper: return "MDI1" # Handle both MDI1 and MDI-1
    if "MDI2" in unit_name_upper or "MDI-2" in unit_name_upper: return "MDI2"
    if "ORIENTATION" in unit_name_upper: return "ORIENTATION"
    return "DEFAULT"


def parse_teacher_assignment_data(raw_data):
    assignments = {}
    current_cohort = None
    teachers_found = set()

    for line in raw_data.splitlines():
        line = line.strip()
        if not line:
            continue

        # Check if the line is a cohort header (e.g., "Cohort 52", "FSDI Ch 54")
        # Make this flexible to match typical cohort naming conventions.
        # Using a more robust regex could be an improvement.
        # For now, checking for "Cohort" or "Ch" (common in your examples)
        if (line.upper().startswith("COHORT ") or "CH " in line.upper() or "Ch " in line) and not "\t" in line and not re.match(r"^\d{3}\s", line):
            current_cohort = line
            assignments[current_cohort] = {}
        elif current_cohort and ("\t" in line or len(line.split()) == 2): # Assuming unit and teacher are tab or space separated
            parts = re.split(r'\s+|\t', line, 1) # Split by any whitespace, max 1 split
            if len(parts) == 2:
                unit, teacher = parts[0].strip(), parts[1].strip()
                if unit and teacher:
                    # Store unit as the number part if possible, for easier matching
                    unit_key = unit # Default to what's parsed
                    match_unit_num = re.match(r'(\d+)', unit) # Match digits at start of unit
                    if match_unit_num:
                        unit_key = match_unit_num.group(1)

                    assignments[current_cohort][unit_key] = teacher
                    teachers_found.add(teacher)
    return assignments, teachers_found


def generate_calendar_events(df_schedule, selected_cohorts, selected_units_full_names, selected_teachers, selected_year, selected_month):
    events = []
    if df_schedule is None or df_schedule.empty: return events

    df = df_schedule.copy() # Work on a copy

    if 'parsed_date' not in df.columns or df['parsed_date'].isnull().all():
        df['parsed_date'] = df['Date'].apply(parse_date_from_string)
        df = df.dropna(subset=['parsed_date'])

    if df.empty: return events

    df_month = df[
        (df['parsed_date'].dt.year == selected_year) &
        (df['parsed_date'].dt.month == selected_month)
    ]

    for index, row in df_month.iterrows():
        event_date = row['parsed_date']
        date_str_full = row['Date']
        slot_detail = get_slot_info(date_str_full)

        for cohort_name_sched in selected_cohorts: # cohort_name_sched is like "FSDI Ch 54"
            if cohort_name_sched in df_month.columns and pd.notna(row[cohort_name_sched]):
                cell_content_full = str(row[cohort_name_sched]).strip() # Full unit name, e.g. "FSDI 101"
                if cell_content_full.lower() == 'nan': continue

                unit_key_for_teacher = get_actual_unit_from_cell(cell_content_full) # "101" or full if no number
                
                # --- Unit Filtering ---
                # selected_units_full_names contains full names like "FSDI 101"
                display_event_based_on_unit = False
                if not selected_units_full_names: # No unit filter selected
                    display_event_based_on_unit = True
                elif cell_content_full.lower() == "orientation" and "Orientation" in selected_units_full_names:
                    display_event_based_on_unit = True
                elif cell_content_full in selected_units_full_names:
                    display_event_based_on_unit = True
                
                if not display_event_based_on_unit:
                    continue # Skip if unit filter doesn't match

                # --- Teacher Assignment and Filtering ---
                teacher_name = ""
                # Find cohort key in teacher_assignments (match "FSDI Ch 54" with "FSDI Ch 54")
                cohort_key_for_teacher_assignment = cohort_name_sched # Assume exact match for now
                
                if cohort_key_for_teacher_assignment in st.session_state.teacher_assignments and \
                   unit_key_for_teacher in st.session_state.teacher_assignments[cohort_key_for_teacher_assignment]:
                    teacher_name = st.session_state.teacher_assignments[cohort_key_for_teacher_assignment][unit_key_for_teacher]

                if selected_teachers and teacher_name not in selected_teachers:
                    if not (not teacher_name and "Unassigned" in selected_teachers): # Show unassigned if "Unassigned" is selected
                         continue # Skip if teacher filter doesn't match

                # --- Event Title and Color ---
                title_parts = [cohort_name_sched, cell_content_full]
                if teacher_name:
                    title_parts.append(f"({teacher_name})")
                
                title = ": ".join(title_parts[:2]) # Cohort: Unit
                if len(title_parts) > 2: # Add teacher if present
                    title += f" {title_parts[2]}"

                if "Saturday" in slot_detail:
                    time_slot = " (Sat)"
                    if "(9 am - 12 pm)" in slot_detail: time_slot = " (Sat AM)"
                    elif "(12 pm - 3 pm)" in slot_detail: time_slot = " (Sat PM)"
                    title += time_slot

                event_type_for_color = get_unit_type_for_color(cell_content_full)
                color = st.session_state.event_colors.get(event_type_for_color, st.session_state.event_colors["DEFAULT"])
                
                events.append({
                    "title": title,
                    "start": event_date.strftime("%Y-%m-%d"),
                    "color": color,
                    "extendedProps": {"teacher": teacher_name, "cohort": cohort_name_sched, "unit": cell_content_full}
                })
    return events


# --- Main Application ---
st.sidebar.title("📅 Calendar Navigation")
schedule_file = st.sidebar.file_uploader("Upload Schedule CSV", type="csv", key="schedule_csv")
df_schedule, cohort_columns_from_csv, available_units_from_csv = load_schedule_data(schedule_file)


tab1, tab2 = st.tabs(["📅 Calendar View", "⚙️ Configuration"])

with tab2:
    st.header("Event Color Configuration")
    cols_color = st.columns(len(st.session_state.event_colors))
    color_keys = list(st.session_state.event_colors.keys())
    for i, key in enumerate(color_keys):
        new_color = cols_color[i].color_picker(f"{key} Color", st.session_state.event_colors[key], key=f"color_{key}")
        if new_color != st.session_state.event_colors[key]:
            st.session_state.event_colors[key] = new_color
            # st.experimental_rerun() # Rerun to apply color changes immediately

    st.header("Teacher Assignments")
    st.markdown("""
    Paste teacher assignments below. Format for each cohort:
    ```
    COHORT NAME EXACTLY AS IN CSV HEADER (e.g., FSDI Ch 54)
    UNIT_NUMBER <Tab_or_Spaces> TEACHER_NAME 
    101 Sam
    102 Sam
    ...
    MDI1 Ch 1 (12-3pm) 
    101 TeacherX 
    ...
    ```
    Separate different cohort assignments with blank lines or ensure the COHORT NAME header is present for each.
    Unit numbers (e.g., '101') will be extracted from units like 'FSDI 101' for matching.
    """)
    
    teacher_data_input = st.text_area("Paste Teacher Assignment Data Here:", height=300, key="teacher_data_input_area")
    
    if st.button("Update Teacher Assignments", key="update_teachers_btn"):
        if teacher_data_input:
            parsed_assignments, teachers_found = parse_teacher_assignment_data(teacher_data_input)
            st.session_state.teacher_assignments.update(parsed_assignments) # Merge with existing
            st.session_state.all_known_teachers.update(teachers_found)
            st.success("Teacher assignments updated!")
            # st.experimental_rerun()
        else:
            st.warning("No data provided to update.")

    if st.session_state.teacher_assignments:
        with st.expander("Current Teacher Assignments (Session State)"):
            st.json(st.session_state.teacher_assignments)
    else:
        st.caption("No teacher assignments loaded in the current session.")


with tab1:
    st.title("📅 Cohort & Unit Dashboard Calendar")

    if df_schedule is not None and not df_schedule.empty:
        # --- Date Parsing and Month/Year Selection ---
        if 'parsed_date' not in df_schedule.columns or df_schedule['parsed_date'].isnull().all():
            df_schedule['parsed_date'] = df_schedule['Date'].astype(str).apply(parse_date_from_string)
            df_schedule = df_schedule.dropna(subset=['parsed_date'])

        if df_schedule.empty or df_schedule['parsed_date'].isnull().all():
            st.warning("No valid dates in schedule CSV after parsing.")
        else:
            min_date = df_schedule['parsed_date'].min()
            available_year_months = sorted(list(set(
                (d.year, d.month) for d in pd.to_datetime(df_schedule['parsed_date'].dropna().unique()) if pd.notna(d)
            )))
            
            if not available_year_months:
                st.warning("No valid dates available for month/year selection.")
            else:
                # Month/Year selection in sidebar
                month_year_options = { f"{datetime(year, month, 1).strftime('%B %Y')}": (year, month) for year, month in available_year_months }
                current_dt = datetime.now()
                default_ym_str = f"{datetime(min_date.year, min_date.month, 1).strftime('%B %Y')}"
                if (current_dt.year, current_dt.month) in available_year_months:
                    current_month_str = f"{datetime(current_dt.year, current_dt.month, 1).strftime('%B %Y')}"
                    if current_month_str in month_year_options: default_ym_str = current_month_str
                
                selected_month_year_str = st.sidebar.selectbox(
                    "Select Month and Year:", options=list(month_year_options.keys()),
                    index=list(month_year_options.keys()).index(default_ym_str) if default_ym_str in month_year_options else 0,
                    key="month_year_select"
                )
                selected_year, selected_month = month_year_options[selected_month_year_str]

                # --- Filter Options in Sidebar ---
                st.sidebar.header("🎓 Filter Options")
                
                units_for_selection_ui = ["Orientation"] + available_units_from_csv
                selected_units_display = st.sidebar.multiselect(
                    "Select Units/Activities:", options=sorted(list(set(units_for_selection_ui))), default=[],
                    key="unit_multiselect"
                ) # Empty default = show all units for selected cohorts

                # Teacher filter
                teacher_filter_options = ["Unassigned"] + sorted(list(st.session_state.all_known_teachers))
                selected_teachers_filter = st.sidebar.multiselect(
                    "Filter by Teacher:", options=teacher_filter_options, default=[],
                    key="teacher_multiselect"
                ) # Empty default = show all teachers

                selected_cohorts = st.sidebar.multiselect(
                    "Select Cohorts:", options=cohort_columns_from_csv, default=cohort_columns_from_csv,
                    key="cohort_multiselect"
                )
                

                # --- Calendar Display ---
                if not selected_cohorts:
                    st.info("Please select at least one cohort to display data.")
                else:
                    st.subheader(f"Schedule for {selected_month_year_str}")
                    
                    calendar_events = generate_calendar_events(
                        df_schedule, selected_cohorts, selected_units_display, 
                        selected_teachers_filter, selected_year, selected_month
                    )

                    if not calendar_events:
                        st.info(f"No events match the current filter criteria for this month.")
                    
                    calendar_options = {
                        "headerToolbar": { "left": "", "center": "title", "right": "dayGridMonth,timeGridWeek" }, # Added week view
                        "initialView": "dayGridMonth",
                        "initialDate": f"{selected_year}-{selected_month:02d}-01",
                        "height": "800px",
                        "eventTimeFormat": { # For week view
                            'hour': 'numeric',
                            'minute': '2-digit',
                            'meridiem': 'short'
                        },
                        "slotMinTime": "08:00:00",
                        "slotMaxTime": "22:00:00",
                        "selectable": True, # Allows clicking on days/slots
                        # "eventClick": # Could add JS callback for event clicks
                    }
                    
                    custom_css = """
                        .fc-event-main { white-space: normal !important; overflow: hidden; text-overflow: ellipsis; font-size: 0.85em; line-height: 1.2; }
                        .fc-event { margin-bottom: 2px !important; padding: 1px 3px !important; border-radius: 4px; }
                        .fc-timegrid-event .fc-event-main { font-size: 0.75em; } /* Smaller font for timegrid events */
                    """
                    st.markdown(f"<style>{custom_css}</style>", unsafe_allow_html=True)

                    key_suffix = f"{selected_year}-{selected_month}-{'_'.join(sorted(selected_cohorts))}-{'_'.join(sorted(selected_units_display))}-{'_'.join(sorted(selected_teachers_filter))}"
                    calendar_key = f"main_calendar_{key_suffix}".replace(" ","_").replace("(","_").replace(")","_").replace(".","_").replace("-","_")


                    calendar_output = calendar( events=calendar_events, options=calendar_options, key=calendar_key )
                    # st.write(calendar_output) # For debugging callbacks

                    # --- Raw Data Expander (Simplified for brevity, can be enhanced) ---
                    # For now, raw data will NOT reflect teacher or deep unit filtering easily without complex melts
                    # It will show based on selected cohorts and month.
                    with st.expander("Show Raw Schedule Data for Selected Month & Cohorts"):
                        df_display_month_cohort = df_schedule[
                            (df_schedule['parsed_date'].dt.year == selected_year) &
                            (df_schedule['parsed_date'].dt.month == selected_month)
                        ]
                        cols_to_show = ['Date'] + [c for c in selected_cohorts if c in df_display_month_cohort.columns]
                        st.dataframe(df_display_month_cohort[cols_to_show].dropna(subset=[c for c in selected_cohorts if c in df_display_month_cohort.columns], how='all'))
    else:
        st.info("👈 Please upload the Schedule CSV file in the sidebar to begin.")