#!/usr/bin/env python3
import requests
import time
from typing import Dict, Optional

class ProvenanceValidator:
    """
    Automated DOI-to-Competence validation using the Crossref API.
    Ensures all literature ingested for semantic analysis is triangulated and verified.
    """
    def __init__(self, email_contact="morskamary-research@example.com"):
        self.base_url = "https://api.crossref.org/works/"
        self.headers = {"User-Agent": f"MorskamaryResearchData/1.0 (mailto:{email_contact})"}

    def validate_doi(self, doi: str) -> Dict[str, str]:
        """
        Validates a DOI against the Crossref API.
        Returns a status and metadata if verified.
        """
        if not doi or doi == "[CITATION_REQUIRED]":
            return {"status": "CITATION_REQUIRED"}
            
        try:
            # Clean DOI
            doi = doi.strip().replace("https://doi.org/", "")
            response = requests.get(f"{self.base_url}{doi}", headers=self.headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                message = data.get('message', {})
                return {
                    "status": "VERIFIED",
                    "title": message.get('title', [''])[0],
                    "publisher": message.get('publisher', 'Unknown'),
                    "type": message.get('type', 'Unknown'),
                    "year": str(message.get('created', {}).get('date-parts', [[0]])[0][0])
                }
            elif response.status_code == 404:
                return {"status": "INVALID_DOI"}
            else:
                return {"status": "API_ERROR", "code": str(response.status_code)}
        except requests.exceptions.RequestException as e:
            return {"status": "CONNECTION_FAILED", "error": str(e)}

if __name__ == "__main__":
    # Test validation
    validator = ProvenanceValidator()
    test_doi = "10.1016/j.marpol.2023.105678"
    print(f"Validating DOI: {test_doi}")
    result = validator.validate_doi(test_doi)
    print(f"Result: {result}")
