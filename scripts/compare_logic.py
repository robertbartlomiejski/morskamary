#!/usr/bin/env python3
import sys
from pathlib import Path

# Add repo root to path
sys.path.append(str(Path(__file__).parent.parent))

from enum import Enum
class TMBDAxis(Enum):
    MARINE = "MARINE"
    MARITIME = "MARITIME"
    OCEANIC = "OCEANIC"

# --- Original Logic (Simulated) ---
_ORIG_MARINE = {"ecosystem", "species", "biodiversity", "ecology"}
_ORIG_MARITIME = {"labour", "labor", "vessel", "port", "shipping"}
_ORIG_OCEANIC = {"governance", "policy", "sustainability", "justice"}

def original_detect(text):
    lower = text.lower()
    scores = {
        "MARINE": sum(1 for kw in _ORIG_MARINE if kw in lower),
        "MARITIME": sum(1 for kw in _ORIG_MARITIME if kw in lower),
        "OCEANIC": sum(1 for kw in _ORIG_OCEANIC if kw in lower),
    }
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "OCEANIC"

# --- Manus Logic ---
from scripts.emergent_sector_logic import enhance_detect_axis

# Test Cases
test_samples = [
    "Blue justice frameworks and social sustainability in the deep sea",
    "Smart-port automation and green retrofitting for shipping fleets",
    "Ocean citizenship and hydrosocial literacy in coastal communities",
    "Marine biodiversity monitoring using autonomous underwater vehicles"
]

print(f"{'Sample Text':<60} | {'Original':<10} | {'Manus-Enhanced':<15}")
print("-" * 90)
for sample in test_samples:
    orig = original_detect(sample)
    manus = enhance_detect_axis(sample)
    print(f"{sample[:58]:<60} | {orig:<10} | {manus:<15}")
