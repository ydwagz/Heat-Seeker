#  Heat-Seeker

A Python-based application that combines a **Heat Risk Checker** and a **Fire Spread Simulator** to analyze weather conditions and simulate how wildfires spread.

---

##  Appearance - V1

<img width="372" height="831" alt="image" src="https://github.com/user-attachments/assets/d0df0792-1e80-45d9-aab7-3551d45ada19" />

---

## Appearance - V2

<img width="390" height="844" alt="image" src="https://github.com/user-attachments/assets/fddd2edf-25ae-49e1-b2a4-0eeaa0c36e92" />

---

##  How to set it up?

**1. Clone the repository**

Open up Git and write:

```bash
git clone https://github.com/ydwagz/Heat-Seeker.git
```

**2. Get Virtual environment**

```bash
py -m venv env
```

**3. Activate the env**

```bash
env\Scripts\activate
```

**4. Install librarie**

```bash
pip install requests
```

**5. Install librarie**

```bash
pip install requests python-dotenv
```

**6. Install librarie**

```bash
pip freeze > requirements.txt
```

**7. Install librarie**

```bash
pip install -r requirements.txt
```

**8. Install librarie**

```bash
pip install flet
```

**9. Install librarie**

```bash
pip install truststore
```

**10. Install librarie**

```bash
pip install os
```

**11. Install librarie**

```bash
pip install csv
```

---

#  Original Codes (without the App)

##  Heat Risk Checker

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

### How does it work?

it gets national Georgian Temperature and Humidity (from API ) , then it calculates the Heat Index with a complicated formula.

**(code was made by Luca Godadze)**

**API used:**

https://api.open-meteo.com/v1/forecast?latitude=41.72&longitude=44.79&current=temperature_2m,relative_humidity_2m

---

##  Fire Spread Simulator

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

### how does it work?

it makes a 10x10 grid (using 🌲), in that 10x10 grid there's a fire in the middle, that fire checks for its neighbors (trees around the fire),
then a neighbor tree has a % chance to catch on fire depending on the Winds direction. after the first round (neighbor trees catch fire) the original fire (🔥) goes out and becomes: "⚫"
then the program checks how many trees there are left and prints them out.

**(made by Luca Godadze)**

## Nasa FIRMS

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

## How does it work?
the code gets Nasa Firms API (https://firms.modaps.eosdis.nasa.gov/api/), this API is connected to a satellite (SOURCE = "VIIRS_NOAA21_NRT") which detects fires world wide and stores them in memory for 5 days. my code tells the satellite where to look and what information it wants to get out of it, in this case i'm looking at my home country Georgia (Sakartvelo) I tell it from (GEORGIA_BBOX = "39.9,41.0,46.8,43.6")
the numbers are a Box's coordinates around the country. but the country isnt a square so i asked AI to make it only track Georgia.
then I connected it to Google maps API, and now NASA FIRMS API and Google Maps API are connected and give me a precise location of wildfire. 

for testing purposes I gave the code a False alarm and it gave me a google maps location of the wild fire:

<img width="751" height="673" alt="image" src="https://github.com/user-attachments/assets/04109baf-28f9-487a-85ff-57d6bc970120" />
<img width="414" height="425" alt="image" src="https://github.com/user-attachments/assets/b78581a0-3b3e-4fd8-8dca-c5776a331511" />


---

# AI part

The Applications Design was made by AI. (Claude Code Opus 5.5)

Image icon was made by ChatGPT-6 open AI

<img width="473" height="401" alt="image" src="https://github.com/user-attachments/assets/be480192-ea4c-4484-9eb6-6fbc81c43647Ma
