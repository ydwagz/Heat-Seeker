# Heat-Seeker

A Python-based application that combines a **Heat Risk Checker** and a **Fire Spread Simulator** to analyze weather conditions and simulate how wildfires spread.

---

## Appearance - V1

<img width="372" height="831" alt="image" src="https://github.com/user-attachments/assets/d0df0792-1e80-45d9-aab7-3551d45ada19" />

---

## Appearance - V2

<img width="390" height="844" alt="image" src="https://github.com/user-attachments/assets/fddd2edf-25ae-49e1-b2a4-0eeaa0c36e92" />

---

## How to Set It Up

**1. Clone the repository**

```bash
git clone https://github.com/ydwagz/Heat-Seeker.git
```

**2. Create a virtual environment**

```bash
py -m venv env
```

**3. Activate the virtual environment**

```bash
env\\Scripts\\activate
```

**4. Install the required dependencies**

```bash
pip install requests python-dotenv flet truststore
```

**5. Save the installed dependencies (optional)**

```bash
pip freeze > requirements.txt
```

**6. Install dependencies from the requirements file (when available)**

```bash
pip install -r requirements.txt
```

`os` and `csv` are part of Python's standard library, so they do not need to be installed separately.

---

# Original Code (Without the App)

## Heat Risk Checker

```python
import requests

def heat_risk_checker(T: float, RH: float):
    temp_c = T
    temp_f = temp_c * 9/5 + 32

    c_1 = -42.379
    c_2 = 2.04901523
    c_3 = 10.14333127
    c_4 = -0.22475541
    c_5 = -0.00683783
    c_6 = -0.05481717
    c_7 = 0.00122874
    c_8 = 0.00085282
    c_9 = -0.00000199

    hi = 0.5 * (temp_f + 61 + (temp_f - 68) * 1.2 + RH * 0.094)

    if hi >= 80:
        hi = c_1 + c_2 * temp_f + c_3 * RH  + c_4 * temp_f * (RH) + c_5 * temp_f**2 + c_6 * (RH)**2 + c_7 * temp_f**2 * (RH) + c_8 * temp_f * (RH)**2 + c_9 * temp_f**2 * (RH)**2  
        

    hi_c  = (hi - 32) / 9*5 

    if hi < 80:
        print("Safe")
    elif hi < 90:
        print('Caution')
    elif hi < 103:
        print("Extreme Caution")
    elif hi < 125:
        print("Danger")
    else:
        print("Extreme Danger")

    return f"F: {hi} \nC: {hi_c}"

response = requests.get("https://api.open-meteo.com/v1/forecast?latitude=41.72&longitude=44.79&current=temperature_2m,relative_humidity_2m")
data = response.json()  
current = data["current"]

print(f'time: {current["time"]}')
print(f'Temperature: {current["temperature_2m"]} C')
print(f'Humidity: {current["relative_humidity_2m"]} %')

idx = heat_risk_checker(current["temperature_2m"], current["relative_humidity_2m"])
print(idx)
```

### How It Works

It gets Georgia's temperature and humidity from an API, then calculates the Heat Index using a formula.

**Code by Luca Godadze.**

**API Used:**

https://api.open-meteo.com/v1/forecast?latitude=41.72&longitude=44.79&current=temperature_2m,relative_humidity_2m

---

## Fire Spread Simulator

```python
import random
import time

grid = []
Left_Trees = 0
grid_size = 10

for _ in range(grid_size):
    grid.append(["🌲"] * grid_size)
    
grid[4][4] = "🔥"

def get_neighbors(grid, row, col):
    neighbors = []
    up = row - 1, col
    down = row + 1, col
    left = row, col - 1
    right = row, col + 1

    candidates = [up, down, left, right]

    for r, c in candidates:
        if 0 <= r < len(grid) and 0 <= c < len(grid):
            neighbors.append((r, c))
            

    return neighbors

def spread(grid, wind):
    opposite = {"east": "west", "west": "east", "north": "south", "south": "north"}
    to_ignite = []
    to_burn_out = []
    
    for r in range(len(grid)):
        for c in range(len(grid)):

            if grid[r][c] == "🔥":
                to_burn_out.append((r, c))
                
                for nr, nc in get_neighbors(grid, r, c):
                    if grid[nr][nc] == "🌲":
                        if nc > c:
                            direction = "east"
                        elif nc < c:
                            direction = "west"
                        elif nr < r:
                            direction = "north"
                        else:
                            direction = "south"

                        if direction == wind:
                            chance = 0.9
                        elif direction == opposite[wind]:
                            chance = 0.1
                        else:
                            chance = 0.4

                        if random.random() < chance:
                            to_ignite.append((nr, nc)) 
                        

    for r, c in to_burn_out:                     
        grid[r][c] = "⚫" 
    for r, c in to_ignite:              
        grid[r][c] = "🔥"  

def has_fire(grid):
    global Left_Trees
    
    for r in range(len(grid)):
        for c in range(len(grid)):
            if grid[r][c] == "🔥":
                return True   
    for r in range(len(grid)):
        for c in range(len(grid)):     
            if grid[r][c] == "🌲":
                Left_Trees += 1
    
    return False  

def print_grid(grid):
    time.sleep(0.2)
    for row in grid:
        print("  ".join(row))
    print("------------------")

has_fire(grid)

while has_fire(grid):
    print_grid(grid)
    spread(grid, "south")
print_grid(grid)

print(f"{Left_Trees} Trees Survived")
```

### How It Works

It creates a 10x10 grid of trees, with a fire in the middle. The fire checks its neighboring trees. Each neighboring tree has a percentage chance of catching fire depending on the wind direction. After each round, the original fire goes out and becomes a burned-out cell. The program then counts and prints how many trees survived.

**Code by Luca Godadze.**

---

## NASA FIRMS

```python
import csv
import os
import time

import requests
import truststore
from dotenv import load_dotenv

truststore.inject_into_ssl()
load_dotenv()

FIRMS_KEY = os.getenv("FIRMS_KEY")
FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
SOURCE = "VIIRS_NOAA21_NRT"
DAYS = 5
GEORGIA_BBOX = "39.9,41.0,46.8,43.6"
COUNTRY_CODE = "ge"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "HeatSeeker-student-project"

def fetch_fires(bbox: str = GEORGIA_BBOX, days: int = DAYS) -> list[dict]:
    response = requests.get(f"{FIRMS_URL}/{FIRMS_KEY}/{SOURCE}/{bbox}/{days}", timeout=60)
    response.raise_for_status()
    if not response.text.startswith("latitude"):
        # FIRMS answers errors (bad key, bad area) with plain text and status 200
        raise RuntimeError(f"FIRMS refused the request: {response.text.strip()[:200]}")
    return list(csv.DictReader(response.text.splitlines()))

def look_up_address(lat: str, lon: str) -> dict:
    response = requests.get(
        NOMINATIM_URL,
        params={"lat": lat, "lon": lon, "format": "json", "accept-language": "en"},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("address", {})

def fires_in_georgia(fires: list[dict]) -> list[dict]:
    addresses = {}
    kept = []
    for fire in fires:
        cell = (round(float(fire["latitude"]), 2), round(float(fire["longitude"]), 2))
        if cell not in addresses:
            addresses[cell] = look_up_address(fire["latitude"], fire["longitude"])
            time.sleep(1)  # Nominatim allows at most 1 request per second
        address = addresses[cell]
        if address.get("country_code") == COUNTRY_CODE:
            kept.append({**fire, "address": address})
    return kept

def place_name(address: dict) -> str:
    settlement = next(
        (address[k] for k in ("village", "town", "city", "hamlet", "municipality", "county") if k in address),
        None,
    )
    region = address.get("state")
    return ", ".join(part for part in (settlement, region) if part) or "Georgia"

def detection_time(fire: dict) -> str:
    hhmm = fire["acq_time"].zfill(4)
    return f"{fire['acq_date']} {hhmm[:2]}:{hhmm[2:]} UTC"

def main():
    if not FIRMS_KEY:
        raise SystemExit("FIRMS_KEY is missing. Add it to Application/.env.")

    fires = fetch_fires()
    georgia = fires_in_georgia(fires)
    skipped = len(fires) - len(georgia)

    print(f"{len(georgia)} fires detected in Georgia in the last {DAYS} days.")
    if skipped:
        print(f"Skipped {skipped} detections just across the border.")

    for fire in sorted(georgia, key=detection_time, reverse=True):
        lat, lon = fire["latitude"], fire["longitude"]
        print()
        print(f"{detection_time(fire)}  {place_name(fire['address'])}")
        print(f"  https://www.google.com/maps?q={lat},{lon}")

if __name__ == "__main__":
    main()

```

## How It Works
The code retrieves data from the NASA FIRMS API (https://firms.modaps.eosdis.nasa.gov/api/). The API provides satellite observations from the VIIRS NOAA-21 NRT source, which detects thermal anomalies and potential fires worldwide. The request uses a bounding box to identify detections around Georgia (Sakartvelo): `GEORGIA_BBOX = "39.9,41.0,46.8,43.6"`.

Because Georgia's borders do not form a rectangle, the code applies additional geographical filtering to keep detections within the country's territory. It then uses location information and Google Maps links to show where the detected hotspots are located. 

For testing purposes, I gave the code a false alarm, and it returned a Google Maps location for the detected fire:

<img width="751" height="673" alt="image" src="https://github.com/user-attachments/assets/04109baf-28f9-487a-85ff-57d6bc970120" />
<img width="414" height="425" alt="image" src="https://github.com/user-attachments/assets/b78581a0-3b3e-4fd8-8dca-c5776a331511" />

**APIs Used:**

Nominatim: https://nominatim.openstreetmap.org/reverse

Google Maps: https://www.google.com/maps

NASA FIRMS: https://firms.modaps.eosdis.nasa.gov/api/area/csv

## Smart Fire Monitoring & Prevention

The application integrates NASA's FIRMS (Fire Information for Resource Management System) API with Google Maps to monitor wildfire activity across Georgia (Sakartvelo).

The system uses satellite data from VIIRS NOAA-21 NRT, which detects thermal anomalies and potential fire hotspots around the world. NASA FIRMS provides access to these satellite observations, including near-real-time fire data.

The system defines a geographical bounding box around Georgia using the following coordinates:

```python
GEORGIA_BBOX = "39.9,41.0,46.8,43.6"
```

Since Georgia's geographical shape does not follow a simple rectangle, additional geographical filtering is applied to ensure that monitoring focuses specifically on the country's territory.

The collected NASA FIRMS data is integrated with Google Maps, allowing users to visualize detected fire hotspots and identify their geographical locations on an interactive map.

### Weather-Based Fire Risk Assessment

In addition to satellite monitoring, the application presents weather conditions that can significantly influence wildfire risk.

For example, under the following illustrative conditions in Tbilisi:

- Temperature: 35°C
- Relative humidity: 18%
- Weather: Hot and dry

The application displays the following illustrative fire-risk indicators:

| Risk Scenario | Indicator | Explanation |
|---|---:|---|
| General forest fire risk | 55% | High temperatures and low humidity create favorable conditions for vegetation to dry out and become more susceptible to ignition. |
| Glass waste scenario | 75% | Discarded glass can, under specific conditions, concentrate sunlight and potentially contribute to ignition. The risk depends on the type and shape of the glass, its position, sunlight, and surrounding dry vegetation. |
| Cigarette butt scenario | 85% | A discarded cigarette butt can ignite dry grass, leaves, and other combustible materials, especially during hot and dry weather. |

> These percentages are conceptual risk indicators for the demonstration. They are intended to illustrate how environmental conditions and human behavior can influence fire danger, rather than represent scientifically validated probabilities.

### CSR – Creating Awareness and Preventing Wildfires

Beyond technology and monitoring, this project has an important Corporate Social Responsibility (CSR) purpose. Our goal is not simply to detect fires after they start, but to help prevent them by educating and engaging the public.

Through the application, we want to raise awareness about two often-overlooked sources of potential fire danger.

#### Glass Waste in Forests

Leaving glass bottles and broken glass in forests is not harmless. Under certain environmental conditions, glass can contribute to fire ignition. Visitors should take all glass waste with them and dispose of it properly.

#### Discarded Cigarette Butts

A cigarette butt thrown into dry grass or forest vegetation can become a source of ignition. We want to encourage smokers to never discard cigarette butts in nature and always use appropriate disposal bins.

### Our Mission

To combine satellite technology, geographical intelligence, weather information, and public awareness into one integrated wildfire monitoring and prevention platform.

**Detect fires. Understand risks. Change behavior. Protect Georgia's forests.**

---

---

# AI Assistance

The application's design was created with AI assistance (Claude Code Opus 5.5).

The application icon was created with ChatGPT by OpenAI.

<img width="473" height="401" alt="image" src="https://github.com/user-attachments/assets/be480192-ea4c-4484-9eb6-6fbc81c43647Ma
