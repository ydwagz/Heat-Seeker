# Heat-Seeker

## How to set it up?

1. Open up Git and write: ```git clone https://github.com/ydwagz/Heat-Seeker.git```
2. Get Virtual environment: ``` py -m venv env```
3. Activate the env: ``` env\Scripts\activate```
4. install librarie: ```pip install requests```
5. install librarie: ```pip install requests python-dotenv```
6. install librarie: ```pip freeze > requirements.txt```
7. install librarie: ```pip install -r requirements.txt```
8. install librarie: ```pip install flet```

Appearance:
<img width="372" height="831" alt="image" src="https://github.com/user-attachments/assets/d0df0792-1e80-45d9-aab7-3551d45ada19" />

Original Codes(without the App):

Heat Risk Checker:

```
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

# How does it work?
it gets national Georgian Temperature and Humidity (from API ) , then it calculates the Heat Index with a complicated formula.
(code was made by Luca Godadze)
API used: "https://api.open-meteo.com/v1/forecast?latitude=41.72&longitude=44.79&current=temperature_2m,relative_humidity_2m"


Fire Spread Simulator:

```
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

# how does it work?
it makes a 10x10 grid (using 🌲), in that 10x10 grid there's a fire in the middle, that fire checks for its neighbors (trees around the fire),
then a neighbor tree has a % chance to catch on fire depending on the Winds direction. after the first round (neighbor trees catch fire) the original fire (🔥) goes out and becomes: "⚫"
then the program checks how many trees there are left and prints them out.
(made by Luca Godadze)


# AI part

The Applications Design was made by AI. (Claude Code Opus 5.5)
Image icon was made by ChatGPT-6 open AI
<img width="473" height="401" alt="image" src="https://github.com/user-attachments/assets/be480192-ea4c-4484-9deb-6fbc81c43647" />




