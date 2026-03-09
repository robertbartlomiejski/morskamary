# Load Real Competence Data — Quick Reference

Your toolkit now loads and processes **real Blue Social Competences** from the University of Szczecin baseline.

---

## 📂 Available CSV Files

| File | What It Contains | Rows |
|------|-----------------|------|
| **Blue Social Competences Univ Szczecin - Overall Blue Competences Dimension.csv** | 16 competences across 4 dimensions (A,B,C,D) + 12 sectors | 25 |
| **Blue Social Competences Univ Szczecin - Blue Clusters for Microcredentials.csv** | Micro-credential clusters by sector | 20+ |
| **Blue Social Competences Univ Szczecin - Blue competences x blue economy sector.csv** | Competence × Sector mapping matrix | 12 sectors |

All in: `data/derived/`

---

## 🚀 How to Use

### **Option 1: Load & Analyze Real Data**
```bash
python main_real_data.py
```

**Output:**
- Loads 16 competences from University of Szczecin baseline
- Creates 3 sample micro-credentials
- Shows competence gaps for a worker transitioning sectors
- Recommends learning pathways

### **Option 2: Use the Loader in Your Own Code**
```python
from load_real_competences import load_blue_competences
from pathlib import Path

# Load competences
csv_path = Path("data/derived/Blue Social Competences Univ Szczecin - Overall Blue Competences Dimension.csv")
mapper = load_blue_competences(csv_path)

# Now use mapper for analysis
gaps = mapper.analyze_competence_gaps(
    available=["blue_comp_a_1", "blue_comp_c_3"],
    required_sector="renewable-energy"
)

print(f"Missing: {gaps['missing']}")
```

### **Option 3: Create Custom Scripts**
```python
from src.competence_mapper import CompetenceMapper
from src.core import Competence, BlueDynamicsAxis, CompetenceLevel

mapper = CompetenceMapper()

# Filter by axis
marine_skills = mapper.get_competences_by_axis(BlueDynamicsAxis.MARINE)
for skill in marine_skills:
    print(f"- {skill.name}")

# Get summary
summary = mapper.get_summary()
print(f"Total competences: {summary['total_competences']}")
```

---

## 📊 Data Loaded

**From the CSV, you get:**

### By TMBD Axis:
- **MARINE (M)**: 4 competences — ecological/biophysical
  - Sustainable resource management
  - Circular economy principles
  - Climate adaptation & coastal resilience
  - Ecosystem-based management

- **MARITIME (T)**: 8 competences — techno-economic/institutional
  - Data & digital proficiency
  - Digital communication
  - Cybersecurity & maritime safety
  - Open science & data sharing
  - Value chain thinking
  - Leadership & blue innovation
  - Blue finance & investment
  - Ethical & participatory governance

- **OCEANIC (O)**: 4 competences — planetary/governance
  - Ocean literacy
  - Blue systems thinking
  - Blue economy regulations
  - (Technical/practical abilities - foundational)

### By Sector (from CSV):
- Blue Biotech
- Coastal Tourism
- Desalination
- Infrastructure & Robotics
- Living Resources (Fisheries)
- Non-living Resources
- Renewable Energy
- Maritime Defence
- Maritime Transport
- Port Activities
- Research & Innovation
- Ship Repair

---

## 💡 Example Workflows

### **Workflow 1: Gap Analysis for Career Transition**
```python
mapper = load_blue_competences(csv_path)

# Worker transitioning from Fisheries to Renewable Energy
current_skills = ["blue_comp_c_1", "blue_comp_a_2"]  # Sustainable mgmt, Systems thinking
gaps = mapper.analyze_competence_gaps(current_skills, "renewable-energy")

print(f"You have: {gaps['available']}")
print(f"You need to learn: {gaps['missing']}")
```

### **Workflow 2: Sector-Specific Competence Requirements**
```python
# What competences does the renewable energy sector need?
required = mapper.get_sector_competences("renewable-energy")

for comp_id in required:
    comp = mapper.competences[comp_id]
    print(f"- {comp.name} ({comp.axis.name} axis)")
```

### **Workflow 3: Micro-Credential Design**
```python
from src.core import MicroCredential

cred = MicroCredential(
    id="cred_energy_001",
    title="Ocean Energy Transition Specialist",
    competences=required,  # Use gap analysis results
    description="12-week micro-credential for sustainable energy professionals",
    sector="renewable-energy",
)

mapper.add_credentials(cred)
```

---

## 🔧 Integration Points

### **What's Connected:**
✅ CSV data → `load_real_competences.py` → `CompetenceMapper` → Your analysis

### **Next Integration Targets:**
- [ ] Load **Blue competences x sector** matrix to auto-assign sector requirements
- [ ] Export competences/credentials to **Europass XML** format
- [ ] Connect to **LMS (Moodle, Canvas)** for learning management
- [ ] Store in **Azure Cosmos DB** for distributed access
- [ ] Create **API endpoint** for competence lookup

---

## 📁 Files You Now Have

```
morskamary/
├── load_real_competences.py   ← Loader function (reads CSV, creates Competence objects)
├── main_real_data.py          ← Full workflow demo with real data
├── main.py                    ← Original demo (sample data)
├── src/
│   ├── core.py               ← Data structures (Competence, MicroCredential, TMBD axes)
│   └── competence_mapper.py  ← Analysis API
├── data/
│   └── derived/
│       ├── Blue Social Competences Univ Szczecin - Overall Blue Competences Dimension.csv
│       ├── Blue Social Competences Univ Szczecin - Blue Clusters for Microcredentials.csv
│       └── Blue Social Competences Univ Szczecin - Blue competences x blue economy sector.csv
└── MANIFEST_SOURCES.csv      ← Index of all 1064 files in the project
```

---

## ✅ What You Can Do Now

1. **Load real competence data** from University of Szczecin baseline
2. **Analyze competence gaps** for workers/learners in blue economy
3. **Design micro-credentials** mapped to sectors and skill pathways
4. **Filter by TMBD axis** (Marine, Maritime, Oceanic)
5. **Get sector requirements** for all 12 blue economy sectors
6. **Create learning pathways** from gap analysis results

---

## 🌊 Ready to Go!

Run any of these commands:
```bash
# See real data in action
python main_real_data.py

# Or use in your own Python code
from load_real_competences import load_blue_competences
mapper = load_blue_competences(Path("data/derived/Blue Social Competences...csv"))

# Then analyze, create credentials, export, integrate...
```

**Your real data is loaded. Your toolkit is ready.** 🎉
