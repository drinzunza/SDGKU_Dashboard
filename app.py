import streamlit as st
import pandas as pd
from datetime import datetime
from streamlit_calendar import calendar # Community component
import re # For parsing unit names

st.set_page_config(layout="wide", page_title="FSDI/MDI Cohort & Unit Calendar")

# --- Helper Functions ---
@st.cache_data # Cache the data loading
def load_data(uploaded_file):
    if uploaded_file is not None:
        try:
            # Explicitly set dtype to string for all columns during loading
            # This helps prevent pandas from auto-interpreting numbers as floats etc.
            df = pd.read_csv(uploaded_file, dtype=str)

            if df.empty or 'Date' not in df.columns:
                st.error("CSV must have a 'Date' column as the first column.")
                return None, [], []
            
            # All columns except the first one ('Date') are considered cohort columns
            cohort_cols = list(df.columns[1:]) # Get all column names from the second onwards
            
            if not cohort_cols:
                st.error("No cohort columns found (expected columns after 'Date').")
                return None, [], []

            # Extract unique unit names (e.g., FSDI 101, MDI-1 102) from the cohort columns
            all_units = set()
            for col in cohort_cols:
                # Ensure the column exists and handle potential missing values correctly
                if col in df:
                    # Drop NA before unique, and ensure values are strings
                    unique_values_in_col = df[col].astype(str).replace('nan', '').dropna().unique()
                    for val in unique_values_in_col:
                        cleaned_val = val.strip()
                        if cleaned_val and cleaned_val.lower() != "orientation":
                            all_units.add(cleaned_val)
            
            sorted_units = sorted(list(all_units))
            return df, cohort_cols, sorted_units
        except Exception as e:
            st.error(f"Error loading CSV: {e}")
            return None, [], []
    return None, [], []

def parse_date_from_string(date_str):
    if pd.isna(date_str) or not isinstance(date_str, str): # Added check for string type
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
    if pd.isna(date_str) or not isinstance(date_str, str): # Added check for string type
        return ""
    parts = date_str.split(',')
    return parts[0].strip() if len(parts) > 1 else ""

def get_actual_unit_from_cell(cell_value):
    if pd.isna(cell_value): # Pandas uses pd.NA or None for missing after dtype=str
        return None
    
    # Ensure cell_value is treated as a string
    cell_value_str = str(cell_value).strip()
    
    if not cell_value_str or cell_value_str.lower() == "orientation" or cell_value_str.lower() == 'nan':
        return None
    return cell_value_str


def generate_calendar_events(df, selected_cohorts, selected_units, selected_year, selected_month):
    events = []
    if df is None or df.empty:
        return events

    # Ensure 'parsed_date' column exists or is created
    if 'parsed_date' not in df.columns or df['parsed_date'].isnull().all(): # Re-parse if mostly null
        df['parsed_date'] = df['Date'].apply(parse_date_from_string)
        df_filtered_dates = df.dropna(subset=['parsed_date'])
    else:
        df_filtered_dates = df

    if df_filtered_dates.empty: # Check after parsing
        st.warning("No valid dates to process after parsing.")
        return events

    df_month = df_filtered_dates[
        (df_filtered_dates['parsed_date'].dt.year == selected_year) &
        (df_filtered_dates['parsed_date'].dt.month == selected_month)
    ]

    for index, row in df_month.iterrows():
        event_date = row['parsed_date']
        date_str_full = row['Date'] # This is already a string from CSV load
        slot_detail = get_slot_info(date_str_full)

        for cohort_name in selected_cohorts:
            if cohort_name in df_month.columns and pd.notna(row[cohort_name]):
                cell_content = str(row[cohort_name]).strip() # Ensure string for "nan" comparison
                
                if cell_content.lower() == 'nan': # Skip if cell content is string 'nan'
                    continue

                actual_unit_in_cell = get_actual_unit_from_cell(cell_content)

                if not selected_units or \
                   (actual_unit_in_cell and actual_unit_in_cell in selected_units) or \
                   (cell_content.lower() == "orientation" and "Orientation" in selected_units):

                    title = f"{cohort_name}: {cell_content}"
                    if "Saturday" in slot_detail:
                        if "(9 am - 12 pm)" in slot_detail:
                            title = f"{cohort_name} (AM): {cell_content}"
                        elif "(12 pm - 3 pm)" in slot_detail:
                            title = f"{cohort_name} (PM): {cell_content}"
                    
                    events.append({
                        "title": title,
                        "start": event_date.strftime("%Y-%m-%d"),
                    })
    return events

# --- Streamlit App UI ---
st.title("📅 SDGKU Unit Dashboard Calendar")

uploaded_file = st.file_uploader("Upload your FSDI_corrected_schedule.csv file", type="csv")

df, cohort_columns, available_units = load_data(uploaded_file)

if df is not None and not df.empty:
    st.sidebar.header("🗓️ Calendar View Options")
    
    # --- Date Parsing and Month/Year Selection ---
    # It's critical that 'parsed_date' is created and valid
    if 'parsed_date' not in df.columns or df['parsed_date'].isnull().all():
         df['parsed_date'] = df['Date'].astype(str).apply(parse_date_from_string) # Ensure Date is str
         df = df.dropna(subset=['parsed_date'])

    if df.empty or ('parsed_date' in df and df['parsed_date'].empty) or df['parsed_date'].isnull().all():
        st.warning("No valid dates found in the uploaded CSV after parsing. Please check the 'Date' column format.")
    else:
        min_date = df['parsed_date'].min()
        available_year_months = sorted(list(set(
            (d.year, d.month) for d in pd.to_datetime(df['parsed_date'].dropna().unique()) if pd.notna(d) # Dropna before unique
        )))
        
        if not available_year_months:
            st.warning("No valid dates available for month/year selection.")
        else:
            month_year_options = {
                f"{datetime(year, month, 1).strftime('%B %Y')}": (year, month)
                for year, month in available_year_months
            }
            current_dt = datetime.now()
            default_ym_str = f"{datetime(min_date.year, min_date.month, 1).strftime('%B %Y')}"
            if (current_dt.year, current_dt.month) in available_year_months:
                current_month_str = f"{datetime(current_dt.year, current_dt.month, 1).strftime('%B %Y')}"
                if current_month_str in month_year_options:
                     default_ym_str = current_month_str

            selected_month_year_str = st.sidebar.selectbox(
                "Select Month and Year:",
                options=list(month_year_options.keys()),
                index=list(month_year_options.keys()).index(default_ym_str) if default_ym_str in month_year_options else 0
            )
            selected_year, selected_month = month_year_options[selected_month_year_str]

            # --- Cohort and Unit Selection ---
            st.sidebar.header("🎓 Filter Options")
            if not cohort_columns:
                st.sidebar.warning("No cohort columns available for selection.")
                selected_cohorts = []
            else:
                selected_cohorts = st.sidebar.multiselect(
                    "Select Cohorts:",
                    options=cohort_columns, # These are your new column names
                    default=cohort_columns
                )
            
            units_for_selection = ["Orientation"] + available_units
            
            if not selected_cohorts:
                 selected_units = []
                 st.sidebar.info("Select cohorts to enable unit filtering.")
            elif not units_for_selection:
                st.sidebar.warning("No units found for filtering.")
                selected_units = []
            else:
                selected_units = st.sidebar.multiselect(
                    "Select Units/Activities (leave empty to show all for selected cohorts):",
                    options=sorted(list(set(units_for_selection))),
                    default=[]
                )

            # --- Calendar Display ---
            if not selected_cohorts:
                st.info("Please select at least one cohort to display data.")
            else:
                st.subheader(f"Schedule for {selected_month_year_str}")
                
                calendar_events = generate_calendar_events(df.copy(), selected_cohorts, selected_units, selected_year, selected_month)

                if not calendar_events:
                    if selected_units:
                         st.info(f"No events scheduled for the selected cohorts AND units in this month.")
                    else:
                         st.info(f"No events scheduled for the selected cohorts in this month.")
                
                calendar_options = {
                    "headerToolbar": { "left": "", "center": "title", "right": "" },
                    "initialView": "dayGridMonth",
                    "initialDate": f"{selected_year}-{selected_month:02d}-01",
                    "height": "700px",
                }
                
                custom_css = """
                    .fc-event-main { white-space: normal !important; overflow: hidden; text-overflow: ellipsis; font-size: 0.8em; line-height: 1.2; }
                    .fc-event { margin-bottom: 1px !important; padding: 1px 2px !important; }
                """
                st.markdown(f"<style>{custom_css}</style>", unsafe_allow_html=True)

                calendar_key_parts = [
                    f"cal-{selected_year}-{selected_month}",
                    "cohorts-" + "_".join(sorted(selected_cohorts)).replace(" ","_").replace("(","_").replace(")","_"), # Sanitize key
                    "units-" + "_".join(sorted(selected_units)).replace(" ","_") # Sanitize key
                ]
                calendar_key = "-".join(calendar_key_parts)

                calendar_widget = calendar(
                    events=calendar_events,
                    options=calendar_options,
                    key=calendar_key 
                )
                
                # --- Raw Data Expander ---
                with st.expander("Show Raw Data for Selected Month, Cohorts, and Units"):
                    # Filter df for the current month first
                    df_current_month_view = df[
                        (df['parsed_date'].dt.year == selected_year) &
                        (df['parsed_date'].dt.month == selected_month)
                    ].copy() # Use a copy to avoid SettingWithCopyWarning

                    if not df_current_month_view.empty:
                        if selected_units:
                            # Create a boolean mask for rows to keep
                            # Row should be kept if ANY of the selected cohort columns for that row
                            # contain one of the selected units (or is Orientation).
                            mask = pd.Series([False] * len(df_current_month_view), index=df_current_month_view.index)
                            for cohort_col_iter in selected_cohorts:
                                if cohort_col_iter in df_current_month_view:
                                    # Check for Orientation
                                    is_orientation = (df_current_month_view[cohort_col_iter].astype(str).str.lower() == "orientation") & ("Orientation" in selected_units)
                                    # Check for other selected units
                                    is_selected_unit = df_current_month_view[cohort_col_iter].astype(str).isin([u for u in selected_units if u.lower() != "orientation"])
                                    mask |= (is_orientation | is_selected_unit)
                            
                            df_display_filtered_by_unit = df_current_month_view[mask]
                            
                            display_cols_raw = ['Date'] + [col for col in selected_cohorts if col in df_display_filtered_by_unit.columns]
                            st.dataframe(df_display_filtered_by_unit[display_cols_raw].dropna(subset=[col for col in selected_cohorts if col in df_display_filtered_by_unit.columns], how='all'))

                        else: # No unit filter, show all for selected cohorts from the month's view
                            display_cols_raw = ['Date'] + [col for col in selected_cohorts if col in df_current_month_view.columns]
                            st.dataframe(df_current_month_view[display_cols_raw].dropna(subset=[col for col in selected_cohorts if col in df_current_month_view.columns], how='all'))
                    else:
                        st.write("No data for this month to display.")

else:
    if uploaded_file is None:
        st.info("👈 Please upload the CSV file to begin.")