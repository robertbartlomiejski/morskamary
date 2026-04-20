# Baseline Validation: TMBD Axis Classification

## Cel
Zweryfikować baseline dla klasyfikacji osi TMBD (`MARINE`, `MARITIME`, `OCEANIC`) przed dalszym strojenie modelu.

## Konfiguracja eksperymentu
- **Zbiór danych**: kompetencje z `data/derived/Blue Social Competences Univ Szczecin - Overall Blue Competences Dimension.csv`.
- **Liczba próbek**: 39.
- **Etykiety (ground truth)**: mapowanie `ID` -> oś przez regułę:
  - `A -> OCEANIC`
  - `B -> MARITIME`
  - `C -> MARINE`
  - `D -> MARITIME`
- **Model baseline**: deterministyczny klasyfikator regułowy (`src/axis_classifier.py`) delegujący do `map_dimension_to_axis` przy dostępnej informacji o wymiarze.
- **Walidacja**: 5-fold CV, `shuffle=True`, `random_state=42`.
- **Metryka główna**: accuracy.

## Wyniki baseline
- **CV accuracy (mean)**: **1.00**
- **CV accuracy (std)**: **0.00**

## Interpretacja
Wynik 1.00 wynika z faktu, że baseline wykorzystuje tę samą regułę mapującą, która służy do budowy etykiet referencyjnych. Jest to punkt odniesienia dla kolejnych eksperymentów opartych o klasyfikację z treści abstraktów (bez bezpośredniej informacji o wymiarze).

## Następny krok
Przygotować alternatywny benchmark tekstowy (np. TF-IDF + Logistic Regression), gdzie wejściem jest opis kompetencji, a nie kod wymiaru.
