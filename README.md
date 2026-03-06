# Reneweble Data Center: Digital Twin ♻️

Research-oriented, out-of-the-box digital twin for hyperscaler AI data centers. 

Motivation:  This is an international research project between indian and german university Students. The goal is to support SDG 7 for sutainable energy. 

### The granualar Goal is to:

1. Enable permanently renewable data centers.
2. Identify regions in which data centers could endanger the renewable energy supply.
3. Impose vacancies for energy suppliers

## Optical Example's: 

<img width="400" height="200" alt="image" src="https://github.com/user-attachments/assets/1723be62-0391-4e4b-bcaa-fc2921659d51" />
<img width="400" height="200" alt="image" src="https://github.com/user-attachments/assets/ef255e00-f033-4fef-9d06-13b0178e3220" />

## Testing Guide 📚
1. Git Clone in selected folder with Terminal - cd 
```bash
git clone https://github.com/<your username>/Digital-Twin-Renewable-Data-Center.git
```
2. Activate Backend in projectfolder 
 ```bash
cd Digital-Twin-Renewable-Data-Center
.venv/bin/uvicorn backend.app:app --reload
```
3. Active Frontend in second terminal window (again in projectfolder)
```bash
  cd frontend
  npm run dev
```
4. Open Localhost
```bash
http://localhost:5173/
```
## Architecture 🏛️

### FrondEnd: WebAPP (Library tbd)
1. Digital Twin Model with Components (Cooling, Racks etc.) - modeled e.g. in Blender 
2. Control elements for User Input to simulated Weather situation etc. 
3. Map to select simulated Region ([Interactive Choropleth Map](https://leafletjs.com/examples/choropleth/))

### BackEnd:
1. Demand Algorithm (math 🧮) <br/>
   1.1. Component Demand (1000 Server AI-Stack)  
   1.2. Usage Prediction Metric - usage allocation on racksystems 
2. Weather model (spatial 🌍) <br/> 
   2.1. Temperature for location - influence on cooling usage
4. Powergrid model (spatial 🌍) <br/> 
   4.1. Renewable Tagged Powerplants  <br/>
   4.2. MegaWatts per year calculated down to constant supply

## Data Pipeline 🛣️

### RestAPI:
1. Direct API's from Data Providers
2. Self hosted PostgREST API for storage allocation and as backup


## Data Backbone 🦴

- Global Energygrid: [https://datasets.wri.org/datasets/global-power-plant-database](https://datasets.wri.org/datasets/global-power-plant-database?map=eyJhY3RpdmVMYXllckdyb3VwcyI6W3siZGF0YXNldElkIjoiNTM2MjNkZmQtM2RmNi00ZjE1LWEwOTEtNjc0NTdjZGI1NzFmIiwibGF5ZXJzIjpbIjJhNjk0Mjg5LWZlYzktNGJmZS1hNmQyLTU2YzM4NjRlYzM0OSJdfV0sImJhc2VtYXAiOiJsaWdodCIsImJvdW5kYXJpZXMiOmZhbHNlLCJib3VuZHMiOnsiYmJveCI6bnVsbCwib3B0aW9ucyI6e319LCJsYWJlbHMiOiJkYXJrIiwibGF5ZXJzUGFyc2VkIjpbWyIyYTY5NDI4OS1mZWM5LTRiZmUtYTZkMi01NmMzODY0ZWMzNDkiLHsiYWN0aXZlIjp0cnVlLCJsYXllclNvdXJjZSI6bnVsbCwib3BhY2l0eSI6MSwidmlzaWJpbGl0eSI6dHJ1ZSwiekluZGV4IjoxMX1dXSwidmlld1N0YXRlIjp7ImxhdGl0dWRlIjo0My41ODg2NjU5MzAyNjMxNSwibG9uZ2l0dWRlIjotOTcuMTQ0ODg5OTcxMjU5MjcsInpvb20iOjMuODcyNDIwNDQwNzcyNDQ1fX0%3D) <br/>
Structure: |country|country_long|name|gppd_idnr|capacity_mw|latitude|longitude|fuel1|fuel2|fuel3|fuel4|
- Global Weather: 
