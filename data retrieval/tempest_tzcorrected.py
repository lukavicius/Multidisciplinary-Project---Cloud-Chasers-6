import requests
import pandas as pd
import io
import time

# --- YOUR CREDENTIALS ---
DEVICE_ID = "XXXX" # Replace with your actual device ID
TOKEN = "XXXX" # Replace with your actual token

# How many days back do you want to pull?
DAYS_HISTORY = 10

all_data = []

# Exact columns returned by WeatherFlow JSON for Tempest devices
TEMPEST_COLUMNS = [
    'timestamp', 'wind_lull', 'wind_avg', 'wind_gust', 'wind_dir',
    'wind_interval', 'pressure', 'temperature', 'humidity', 'lux',
    'uv', 'solar_radiation', 'precip', 'precip_type', 'strike_distance',
    'strike_count', 'battery', 'report_interval', 'local_daily_precip',
    'precip_final', 'local_daily_precip_final', 'precip_analysis_type'
]

print(f"Downloading {DAYS_HISTORY} days of data. This will take a few minutes...")

for day_offset in range(DAYS_HISTORY):
    # Notice we removed &format=csv so the API defaults to standard JSON
    url = f"https://swd.weatherflow.com/swd/rest/observations/device/{DEVICE_ID}?day_offset={day_offset}&token={TOKEN}"

    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()

        # Check if 'obs' array exists and has data
        # Check if 'obs' array exists and has data
        if 'obs' in data and len(data['obs']) > 0:
            df = pd.DataFrame(data['obs'])

            # How many columns do we know the names for?
            num_known_cols = len(TEMPEST_COLUMNS)

            # Slice the dataframe to ONLY keep the columns we have names for
            df = df.iloc[:, :num_known_cols]

            # Apply the column names safely
            df.columns = TEMPEST_COLUMNS
            all_data.append(df)

            print(f"Successfully downloaded day offset: {day_offset}")
        else:
            print(f"No observations found for day offset: {day_offset}")
    else:
        print(f"Failed to get data for day {day_offset}. Status Code: {response.status_code}")

    # Sleep for 1.5 seconds to respect the API rate limits
    time.sleep(1.5)

if len(all_data) > 0:
    print("Stitching data together...")
    full_df = pd.concat(all_data, ignore_index=True)

    # Convert the UNIX timestamp (UTC epoch seconds) to Guatemala local time
    full_df['timestamp'] = (
        pd.to_datetime(full_df['timestamp'], unit='s', utc=True)
        .dt.tz_convert('America/Guatemala')
        .dt.tz_localize(None)   # drop the "-06:00" suffix so Excel reads it cleanly
    )

    # Set the timestamp as the index (required for the resampling step)
    full_df.set_index('timestamp', inplace=True)

    # Sort chronologically (oldest to newest)
    full_df.sort_index(inplace=True)

    # Resample the data to exactly 15-Minute buckets ('15min')
    fifteen_min_df = full_df.resample('15min').mean(numeric_only=True)
    start_date = fifteen_min_df.index.min().strftime("%Y-%m-%d")
    end_date = fifteen_min_df.index.max().strftime("%Y-%m-%d")

    # Save the final result to your computer
    file_name = f"tempest_{start_date}_{end_date}_15min.csv"
    fifteen_min_df.to_csv(file_name)
    print(f"Done! Saved all 15-minute data to {file_name}")
else:
    print("Error: No data was downloaded. Stopping script.")