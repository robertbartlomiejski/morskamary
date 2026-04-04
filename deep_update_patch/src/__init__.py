"""
morskamary: Blue Sociology Evidence Base

Python library for maritime competence mapping and micro-credential design
based on Blue Sociology principles and the Tripartite Model of Blue Dynamics (TMBD).
"""

__version__ = "0.2.0"
__author__ = "Robert Bartłomiejski"

from src.core import (  # noqa: F401
    BlueDynamicsAxis,
    Competence,
    CompetenceLevel,
    MicroCredential,
    RequirementKind,
    SectorRequirement,
    SourceRef,
)
from src.competence_mapper import CompetenceMapper  # noqa: F401
