import os
import csv
import requests
from dotenv import load_dotenv
import time

load_dotenv()
key = os.getenv("FIRMS_KEY")\

firms = requests.get(f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/VIIRS_SNPP_NRT/10,-15,35,5/5")
firms_data = firms.text.splitlines()
print("Status:", firms.status_code)
print("Lines:", len(firms_data))
print(firms.text[:300])
reader = csv.DictReader(firms_data)


for row in reader:
    lat = row["latitude"]
    lon = row["longitude"]    
    location = requests.get(
        "https://nominatim.openstreetmap.org/reverse",
        params={"lat": lat, "lon": lon, "format": "json"},
        headers={"User-Agent": "HeatSeeker-student-project"},
    )
    location_data = location.json()
    address = location_data.get("address", {})

    print(row["acq_date"], lat, lon)
    print("Place:", address.get("state", "unknown"), address.get("country", "unknown"))
    print("Map", f'https://www.google.com/maps?q={lat},{lon}')

    time.sleep(1)