# Benchmark walk-forward — vincitore partita (riepilogo)

File generato insieme a `match_winner_walk_forward_benchmark.json` dallo stesso comando; ogni numero e' copiato dal JSON. Non modificare a mano.

- Comando: `python -m backend.src.app.ml.benchmarks.match_winner_walk_forward`
- Generato: 2026-11-17T13:15:05.247358+00:00 (seed 42, 1000 ricampionamenti bootstrap)
- Dataset: `backend/data/processed/tennis_winner_dataset_with_odds_v3.csv.gz` — sha256 `752eebae8cf65796fe2fb69eec371b485c08acdc03dfee8bdd7ce1a81b545ee3`
- Righe: 338564 (1990-02-05 .. 2026-06-21); con quote valide: 99982 (2021-10-07 .. 2026-06-21)
- Righe di test (somma dei fold): 87504
- Ambiente: python 3.13.18, numpy 2.5.3, pandas 3.0.3, scikit_learn 1.9.0, xgboost 3.4.0
- Elo dinamico selezionato prima del primo fold: `dyn_k250_tau365` (K variabile con l'esperienza; `tau` = decadimento per inattivita', in giorni)

## Fold (finestra espandibile, un trimestre di test per fold)

| fold | test | fine train | righe train con quote | righe test | quota righe test con arricchimento ATP |
|---|---|---|---|---|---|
| 2023Q3 | 2023-07-01 .. 2023-09-30 | 2023-06-30 | 12478 | 12377 | 0.5018 |
| 2024Q4 | 2024-10-01 .. 2024-12-31 | 2023-09-28 | 24855 | 8494 | 0.4599 |
| 2025Q1 | 2025-01-01 .. 2025-03-31 | 2024-12-31 | 33349 | 10458 | 0.0 |
| 2025Q2 | 2025-04-01 .. 2025-06-30 | 2025-03-31 | 43807 | 13034 | 0.0 |
| 2025Q3 | 2025-07-01 .. 2025-09-30 | 2025-06-30 | 56841 | 14490 | 0.0 |
| 2025Q4 | 2025-10-01 .. 2025-12-31 | 2025-09-30 | 71331 | 10050 | 0.0 |
| 2026Q1 | 2026-01-01 .. 2026-03-31 | 2025-12-31 | 81381 | 10587 | 0.0 |
| 2026Q2 | 2026-04-01 .. 2026-06-30 | 2026-03-31 | 91968 | 8014 | 0.0 |

## Tabella principale (tutti i fold, stesse righe di test per ogni modello)

Delta log loss rispetto al mercato no-vig: negativo = meglio del mercato; IC 95% da bootstrap appaiato.

| modello | n | log loss | Brier | ECE | accuratezza | delta log loss vs mercato [IC95] | fold migliori del mercato |
|---|---|---|---|---|---|---|---|
| `v4_like__enrichment_as_missing` | 87504 | 0.55666 | 0.18922 | 0.0054 | 0.7072 | -0.00241 [-0.00284, -0.00196] | 7/8 |
| `v4_like__trained_without_enrichment` | 87504 | 0.55669 | 0.18924 | 0.0049 | 0.7074 | -0.00238 [-0.00281, -0.00191] | 7/8 |
| `v4_like__enrichment_as_missing_and_rank_fallback` | 87504 | 0.55673 | 0.18924 | 0.0054 | 0.7072 | -0.00233 [-0.00275, -0.00188] | 7/8 |
| `v4_like__true_features` | 87504 | 0.55677 | 0.18927 | 0.0050 | 0.7068 | -0.00230 [-0.00275, -0.00184] | 6/8 |
| `v4_like__trained_without_enrichment__rank_fallback` | 87504 | 0.55678 | 0.18927 | 0.0048 | 0.7074 | -0.00228 [-0.00271, -0.00182] | 7/8 |
| `v4_like__trained_on_serving_available` | 87504 | 0.55680 | 0.18927 | 0.0054 | 0.7072 | -0.00226 [-0.00271, -0.00180] | 7/8 |
| `xgb_with_odds` | 87504 | 0.55704 | 0.18943 | 0.0056 | 0.7071 | -0.00202 [-0.00248, -0.00153] | 8/8 |
| `market_logit_recalibrated` | 87504 | 0.55720 | 0.18928 | 0.0084 | 0.7077 | -0.00186 [-0.00222, -0.00151] | 7/8 |
| `shrink50__v4_like_true__market` | 87504 | 0.55736 | 0.18931 | 0.0115 | 0.7073 | -0.00170 [-0.00192, -0.00149] | 8/8 |
| `lr_with_odds` | 87504 | 0.55771 | 0.18960 | 0.0082 | 0.7066 | -0.00135 [-0.00183, -0.00082] | 7/8 |
| `hgb_with_odds` | 87504 | 0.55820 | 0.18984 | 0.0053 | 0.7057 | -0.00086 [-0.00147, -0.00026] | 6/8 |
| `market_no_vig` | 87504 | 0.55906 | 0.18969 | 0.0181 | 0.7075 | riferimento | — |
| `hgb_with_odds_per_inferred_tour` | 87504 | 0.56078 | 0.19087 | 0.0034 | 0.7036 | +0.00172 [+0.00096, +0.00249] | 4/8 |
| `v4_like__serving_enrichment_zeros` | 87504 | 0.56300 | 0.19190 | 0.0370 | 0.7013 | +0.00394 [+0.00326, +0.00465] | 1/8 |
| `v4_like__serving_enrichment_zeros_and_rank_fallback` | 87504 | 0.56308 | 0.19192 | 0.0371 | 0.7010 | +0.00402 [+0.00336, +0.00474] | 1/8 |
| `hgb_no_odds_full_history` | 87504 | 0.58148 | 0.19921 | 0.0072 | 0.6881 | +0.02242 [+0.02098, +0.02396] | 1/8 |
| `lr_no_odds` | 87504 | 0.58357 | 0.20014 | 0.0041 | 0.6858 | +0.02451 [+0.02301, +0.02613] | 1/8 |
| `hgb_no_odds` | 87504 | 0.58403 | 0.20026 | 0.0053 | 0.6861 | +0.02496 [+0.02344, +0.02651] | 1/8 |
| `lr_no_odds_full_history` | 87504 | 0.58427 | 0.20040 | 0.0086 | 0.6862 | +0.02520 [+0.02366, +0.02680] | 1/8 |
| `elo_dynamic_logit` | 87504 | 0.59027 | 0.20297 | 0.0073 | 0.6809 | +0.03121 [+0.02955, +0.03282] | 1/8 |
| `elo_overall_dynamic` | 87504 | 0.59151 | 0.20351 | 0.0058 | 0.6790 | +0.03244 [+0.03074, +0.03412] | 1/8 |
| `elo_blend_dynamic` | 87504 | 0.59322 | 0.20426 | 0.0042 | 0.6771 | +0.03416 [+0.03235, +0.03580] | 0/8 |
| `elo_overall_k32` | 87504 | 0.60284 | 0.20817 | 0.0200 | 0.6700 | +0.04378 [+0.04206, +0.04547] | 0/8 |
| `dataset_elo_overall` | 87504 | 0.60284 | 0.20817 | 0.0202 | 0.6702 | +0.04378 [+0.04207, +0.04547] | 0/8 |
| `elo_blend_k32` | 87504 | 0.60727 | 0.20995 | 0.0350 | 0.6691 | +0.04821 [+0.04647, +0.04993] | 0/8 |
| `elo_surface_k32` | 87504 | 0.62553 | 0.21823 | 0.0152 | 0.6439 | +0.06647 [+0.06431, +0.06855] | 0/8 |
| `rank_logit` | 87504 | 0.66470 | 0.23531 | 0.0107 | 0.5867 | +0.10564 [+0.10307, +0.10808] | 0/8 |

Legenda: `market_no_vig` = probabilita' di mercato senza margine; `elo_overall_k32` = Elo (K=32); `elo_surface_k32` = Elo per superficie; `elo_overall_dynamic` / `elo_blend_dynamic` = Elo con K variabile e decadimento; `lr_*` = regressione logistica; `hgb_*` / `xgb_*` = gradient boosting; `*_no_odds` senza quote, `*_with_odds` con quote; `v4_like__*` = stessi algoritmi e stesse 38 feature dell'artefatto v4, riaddestrati dentro ogni fold (non e' l'artefatto di produzione).

## Segmento: `surface` (log loss / Brier)

| surface | n | `market_no_vig` | `elo_overall_k32` | `elo_surface_k32` | `elo_overall_dynamic` | `lr_no_odds` | `hgb_no_odds` | `lr_with_odds` | `hgb_with_odds` | `v4_like__true_features` | `v4_like__serving_enrichment_zeros_and_rank_fallback` |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Clay | 34185 | 0.5552 / 0.1882 | 0.6017 / 0.2077 | 0.6216 / 0.2164 | 0.5900 / 0.2029 | 0.5814 / 0.1992 | 0.5809 / 0.1990 | 0.5534 / 0.1880 | 0.5540 / 0.1883 | 0.5522 / 0.1876 | 0.5597 / 0.1908 |
| Clay (Indoor) | 438 | 0.5495 / 0.1854 | 0.5803 / 0.1982 | 0.6866 / 0.2468 | 0.5603 / 0.1905 | 0.5632 / 0.1904 | 0.5667 / 0.1916 | 0.5505 / 0.1860 | 0.5527 / 0.1863 | 0.5532 / 0.1863 | 0.5633 / 0.1907 |
| Grass | 1968 | 0.5934 / 0.2040 | 0.6303 / 0.2200 | 0.6693 / 0.2385 | 0.6210 / 0.2152 | 0.6082 / 0.2104 | 0.6132 / 0.2128 | 0.5962 / 0.2052 | 0.5983 / 0.2061 | 0.5974 / 0.2056 | 0.6005 / 0.2071 |
| Hard | 44133 | 0.5584 / 0.1893 | 0.6009 / 0.2073 | 0.6189 / 0.2152 | 0.5892 / 0.2025 | 0.5815 / 0.1992 | 0.5821 / 0.1994 | 0.5569 / 0.1891 | 0.5572 / 0.1893 | 0.5561 / 0.1888 | 0.5621 / 0.1913 |
| Hard (Indoor) | 4910 | 0.5930 / 0.2042 | 0.6261 / 0.2186 | 0.6661 / 0.2367 | 0.6217 / 0.2165 | 0.6171 / 0.2148 | 0.6185 / 0.2151 | 0.5950 / 0.2052 | 0.5942 / 0.2049 | 0.5919 / 0.2040 | 0.5944 / 0.2050 |
| unknown | 1870 | 0.5229 / 0.1751 | 0.5855 / 0.2011 | 0.6870 / 0.2469 | 0.5705 / 0.1954 | 0.5636 / 0.1920 | 0.5695 / 0.1942 | 0.5198 / 0.1744 | 0.5228 / 0.1755 | 0.5210 / 0.1751 | 0.5266 / 0.1778 |

## Segmento: `period` (log loss / Brier)

| period | n | `market_no_vig` | `elo_overall_k32` | `elo_surface_k32` | `elo_overall_dynamic` | `lr_no_odds` | `hgb_no_odds` | `lr_with_odds` | `hgb_with_odds` | `v4_like__true_features` | `v4_like__serving_enrichment_zeros_and_rank_fallback` |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2023Q3 | 12377 | 0.5635 / 0.1917 | 0.6152 / 0.2135 | 0.6365 / 0.2231 | 0.6010 / 0.2075 | 0.5936 / 0.2044 | 0.5966 / 0.2055 | 0.5627 / 0.1918 | 0.5676 / 0.1937 | 0.5636 / 0.1922 | 0.5758 / 0.1976 |
| 2024Q4 | 8494 | 0.5444 / 0.1835 | 0.6017 / 0.2077 | 0.6242 / 0.2177 | 0.5863 / 0.2012 | 0.5748 / 0.1963 | 0.5796 / 0.1979 | 0.5427 / 0.1834 | 0.5418 / 0.1831 | 0.5401 / 0.1825 | 0.5464 / 0.1848 |
| 2025Q1 | 10458 | 0.5977 / 0.2058 | 0.6073 / 0.2103 | 0.6312 / 0.2208 | 0.5973 / 0.2062 | 0.5910 / 0.2036 | 0.5930 / 0.2044 | 0.6000 / 0.2066 | 0.5985 / 0.2059 | 0.5988 / 0.2058 | 0.6016 / 0.2071 |
| 2025Q2 | 13034 | 0.5642 / 0.1918 | 0.6084 / 0.2106 | 0.6271 / 0.2189 | 0.6000 / 0.2070 | 0.5899 / 0.2027 | 0.5895 / 0.2026 | 0.5629 / 0.1917 | 0.5635 / 0.1919 | 0.5618 / 0.1913 | 0.5699 / 0.1947 |
| 2025Q3 | 14490 | 0.5490 / 0.1853 | 0.5986 / 0.2063 | 0.6171 / 0.2145 | 0.5870 / 0.2017 | 0.5803 / 0.1987 | 0.5777 / 0.1976 | 0.5470 / 0.1851 | 0.5467 / 0.1852 | 0.5455 / 0.1847 | 0.5524 / 0.1874 |
| 2025Q4 | 10050 | 0.5414 / 0.1822 | 0.5913 / 0.2029 | 0.6102 / 0.2114 | 0.5790 / 0.1980 | 0.5700 / 0.1944 | 0.5688 / 0.1938 | 0.5378 / 0.1815 | 0.5370 / 0.1815 | 0.5365 / 0.1811 | 0.5393 / 0.1820 |
| 2026Q1 | 10587 | 0.5554 / 0.1882 | 0.5947 / 0.2048 | 0.6210 / 0.2163 | 0.5854 / 0.2011 | 0.5796 / 0.1985 | 0.5805 / 0.1989 | 0.5532 / 0.1877 | 0.5544 / 0.1882 | 0.5528 / 0.1877 | 0.5565 / 0.1893 |
| 2026Q2 | 8014 | 0.5542 / 0.1881 | 0.6030 / 0.2083 | 0.6403 / 0.2249 | 0.5929 / 0.2041 | 0.5854 / 0.2009 | 0.5838 / 0.2002 | 0.5525 / 0.1878 | 0.5524 / 0.1879 | 0.5516 / 0.1876 | 0.5577 / 0.1904 |

## Segmento: `market_balance` (log loss / Brier)

| market_balance | n | `market_no_vig` | `elo_overall_k32` | `elo_surface_k32` | `elo_overall_dynamic` | `lr_no_odds` | `hgb_no_odds` | `lr_with_odds` | `hgb_with_odds` | `v4_like__true_features` | `v4_like__serving_enrichment_zeros_and_rank_fallback` |
|---|---|---|---|---|---|---|---|---|---|---|---|
| balanced_0.40-0.60 | 24851 | 0.6860 / 0.2465 | 0.7065 / 0.2561 | 0.7136 / 0.2593 | 0.7120 / 0.2582 | 0.7087 / 0.2566 | 0.7083 / 0.2566 | 0.6875 / 0.2472 | 0.6872 / 0.2470 | 0.6866 / 0.2467 | 0.6910 / 0.2489 |
| unbalanced | 62653 | 0.5087 / 0.1672 | 0.5617 / 0.1892 | 0.5906 / 0.2020 | 0.5437 / 0.1818 | 0.5339 / 0.1778 | 0.5347 / 0.1779 | 0.5062 / 0.1668 | 0.5070 / 0.1671 | 0.5053 / 0.1665 | 0.5123 / 0.1693 |

## Segmento: `min_prior_matches` (log loss / Brier)

| min_prior_matches | n | `market_no_vig` | `elo_overall_k32` | `elo_surface_k32` | `elo_overall_dynamic` | `lr_no_odds` | `hgb_no_odds` | `lr_with_odds` | `hgb_with_odds` | `v4_like__true_features` | `v4_like__serving_enrichment_zeros_and_rank_fallback` |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 1640 | 0.3468 / 0.1042 | 0.6398 / 0.2244 | 0.6519 / 0.2306 | 0.6334 / 0.2193 | 0.4375 / 0.1376 | 0.4471 / 0.1421 | 0.3427 / 0.1046 | 0.3387 / 0.1046 | 0.3368 / 0.1034 | 0.3433 / 0.1055 |
| 1-4 | 4447 | 0.4126 / 0.1291 | 0.5934 / 0.2038 | 0.6166 / 0.2141 | 0.5375 / 0.1802 | 0.5087 / 0.1680 | 0.4928 / 0.1608 | 0.4088 / 0.1289 | 0.4108 / 0.1300 | 0.4077 / 0.1286 | 0.4146 / 0.1314 |
| 5-19 | 10572 | 0.4795 / 0.1561 | 0.5540 / 0.1861 | 0.5856 / 0.1999 | 0.5193 / 0.1725 | 0.5139 / 0.1702 | 0.5164 / 0.1713 | 0.4753 / 0.1555 | 0.4752 / 0.1557 | 0.4739 / 0.1551 | 0.4810 / 0.1577 |
| 20-49 | 13505 | 0.5348 / 0.1788 | 0.5619 / 0.1901 | 0.5852 / 0.2001 | 0.5545 / 0.1877 | 0.5536 / 0.1873 | 0.5539 / 0.1873 | 0.5325 / 0.1784 | 0.5335 / 0.1789 | 0.5319 / 0.1782 | 0.5382 / 0.1810 |
| 50+ | 57340 | 0.5969 / 0.2056 | 0.6212 / 0.2163 | 0.6423 / 0.2259 | 0.6165 / 0.2143 | 0.6135 / 0.2130 | 0.6146 / 0.2134 | 0.5965 / 0.2057 | 0.5970 / 0.2058 | 0.5958 / 0.2053 | 0.6019 / 0.2080 |

## Calibrazione (10 intervalli di uguale ampiezza sulla probabilita' del giocatore 1)

`market_no_vig` — ECE 0.0181

| intervallo | n | probabilita' media | frequenza osservata |
|---|---|---|---|
| 0.0-0.1 | 1580 | 0.0828 | 0.0335 |
| 0.1-0.2 | 6827 | 0.1497 | 0.1122 |
| 0.2-0.3 | 9659 | 0.2515 | 0.2256 |
| 0.3-0.4 | 11355 | 0.3515 | 0.3421 |
| 0.4-0.5 | 12248 | 0.4482 | 0.4446 |
| 0.5-0.6 | 12603 | 0.5514 | 0.5492 |
| 0.6-0.7 | 12335 | 0.6489 | 0.6635 |
| 0.7-0.8 | 10774 | 0.7493 | 0.7715 |
| 0.8-0.9 | 8134 | 0.8504 | 0.8873 |
| 0.9-1.0 | 1989 | 0.9180 | 0.9723 |

`v4_like__true_features` — ECE 0.0050

| intervallo | n | probabilita' media | frequenza osservata |
|---|---|---|---|
| 0.0-0.1 | 3712 | 0.0622 | 0.0539 |
| 0.1-0.2 | 6975 | 0.1495 | 0.1437 |
| 0.2-0.3 | 8928 | 0.2539 | 0.2516 |
| 0.3-0.4 | 9967 | 0.3599 | 0.3524 |
| 0.4-0.5 | 12194 | 0.4440 | 0.4470 |
| 0.5-0.6 | 13168 | 0.5509 | 0.5511 |
| 0.6-0.7 | 10057 | 0.6515 | 0.6618 |
| 0.7-0.8 | 10554 | 0.7460 | 0.7516 |
| 0.8-0.9 | 7306 | 0.8491 | 0.8525 |
| 0.9-1.0 | 4643 | 0.9416 | 0.9507 |

`v4_like__serving_enrichment_zeros_and_rank_fallback` — ECE 0.0371

| intervallo | n | probabilita' media | frequenza osservata |
|---|---|---|---|
| 0.0-0.1 | 3409 | 0.0620 | 0.0510 |
| 0.1-0.2 | 7162 | 0.1503 | 0.1412 |
| 0.2-0.3 | 8471 | 0.2548 | 0.2488 |
| 0.3-0.4 | 14314 | 0.3551 | 0.3705 |
| 0.4-0.5 | 15345 | 0.4508 | 0.4908 |
| 0.5-0.6 | 11844 | 0.5502 | 0.6027 |
| 0.6-0.7 | 12805 | 0.6488 | 0.7235 |
| 0.7-0.8 | 6438 | 0.7434 | 0.8176 |
| 0.8-0.9 | 3974 | 0.8485 | 0.8855 |
| 0.9-1.0 | 3742 | 0.9425 | 0.9580 |

## Scostamento train/serve (stesso modello addestrato nel fold, due modi di valorizzare le feature in test)

Log loss e Brier: positivo = il candidato e' peggiore del riferimento. Accuratezza: candidato − riferimento.

| candidato | riferimento | delta log loss [IC95] | delta Brier [IC95] | accuratezza (delta [IC95]) | abs(delta p) medio / p95 | pronostici invertiti | fold peggiori |
|---|---|---|---|---|---|---|---|
| `v4_like__serving_enrichment_zeros` | `v4_like__true_features` | +0.00624 [+0.00551, +0.00696] | +0.00263 [+0.00233, +0.00293] | 0.7013 vs 0.7068 (-0.00558 [-0.00743, -0.00369]) | 0.03854 / 0.09930 | 0.07968 | 8/8 |
| `v4_like__serving_enrichment_zeros_and_rank_fallback` | `v4_like__true_features` | +0.00632 [+0.00558, +0.00704] | +0.00266 [+0.00234, +0.00297] | 0.7010 vs 0.7068 (-0.00582 [-0.00767, -0.00390]) | 0.03881 / 0.09983 | 0.08060 | 8/8 |
| `v4_like__enrichment_as_missing` | `v4_like__true_features` | -0.00011 [-0.00023, +0.00001] | -0.00005 [-0.00010, -0.00000] | 0.7072 vs 0.7068 (+0.00038 [+0.00002, +0.00073]) | 0.00187 / 0.01328 | 0.00269 | 0/8 |
| `v4_like__enrichment_as_missing_and_rank_fallback` | `v4_like__true_features` | -0.00003 [-0.00017, +0.00010] | -0.00003 [-0.00009, +0.00003] | 0.7072 vs 0.7068 (+0.00040 [-0.00006, +0.00083]) | 0.00353 / 0.01857 | 0.00424 | 4/8 |
| `v4_like__trained_without_enrichment` | `v4_like__true_features` | -0.00008 [-0.00022, +0.00005] | -0.00003 [-0.00009, +0.00003] | 0.7074 vs 0.7068 (+0.00056 [+0.00005, +0.00107]) | 0.00520 / 0.01786 | 0.00598 | 2/8 |
| `v4_like__trained_without_enrichment__rank_fallback` | `v4_like__true_features` | +0.00002 [-0.00014, +0.00017] | +0.00001 [-0.00006, +0.00007] | 0.7074 vs 0.7068 (+0.00055 [+0.00001, +0.00111]) | 0.00585 / 0.02060 | 0.00642 | 4/8 |
| `v4_like__trained_on_serving_available` | `v4_like__true_features` | +0.00003 [-0.00012, +0.00019] | +0.00001 [-0.00006, +0.00007] | 0.7072 vs 0.7068 (+0.00039 [-0.00016, +0.00096]) | 0.00619 / 0.02095 | 0.00686 | 3/8 |
| `v4_like__trained_on_serving_available` | `v4_like__serving_enrichment_zeros_and_rank_fallback` | -0.00629 [-0.00700, -0.00554] | -0.00265 [-0.00296, -0.00233] | 0.7072 vs 0.7010 (+0.00621 [+0.00438, +0.00798]) | 0.03826 / 0.09881 | 0.07994 | 0/8 |
| `v4_like__enrichment_as_missing_and_rank_fallback` | `v4_like__serving_enrichment_zeros_and_rank_fallback` | -0.00635 [-0.00706, -0.00561] | -0.00268 [-0.00299, -0.00238] | 0.7072 vs 0.7010 (+0.00622 [+0.00431, +0.00801]) | 0.03810 / 0.09821 | 0.07984 | 0/8 |
| `hgb_with_odds_per_inferred_tour` | `hgb_with_odds` | +0.00258 [+0.00197, +0.00319] | +0.00103 [+0.00079, +0.00127] | 0.7036 vs 0.7057 (-0.00206 [-0.00328, -0.00073]) | 0.02739 / 0.08351 | 0.03792 | 7/8 |

`serving_enrichment_zeros` = le 13 colonne di arricchimento ATP valgono 0 (cio' che il serving passa oggi al modello); `rank_fallback` = differenze di ranking a 0 (nessun file ranking disponibile); `enrichment_as_missing` = colonne dichiarate mancanti e gestite dagli imputer del modello.

## Artefatto di produzione: sensibilita' al riempimento (IN-SAMPLE)

`backend/data/models/v4/voting_ensemble.pkl` (sha256 `5918cf84aaf4a136c58ed481f5f52e92e7f4a8c9bc736177ce9454ddf3a949ad`), 66633 righe dal 2025-01-01. L'artefatto e' stato addestrato su questo dataset: i valori assoluti sono ottimistici, contano solo le differenze tra varianti.

| variante | n | log loss | Brier | ECE | accuratezza | probabilita' media |
|---|---|---|---|---|---|---|
| `dataset_values` | 66633 | 0.55268 | 0.18790 | 0.0060 | 0.7084 | 0.5102 |
| `serving_enrichment_zeros` | 66633 | 0.55527 | 0.18888 | 0.0252 | 0.7071 | 0.4925 |
| `serving_enrichment_zeros_and_rank_fallback` | 66633 | 0.55580 | 0.18908 | 0.0252 | 0.7066 | 0.4928 |
| `enrichment_as_missing` | 66633 | 0.55268 | 0.18790 | 0.0060 | 0.7084 | 0.5102 |
| `enrichment_as_missing_and_rank_fallback` | 66633 | 0.55325 | 0.18811 | 0.0061 | 0.7082 | 0.5101 |
| `market_no_vig` | 66633 | 0.56009 | 0.19011 | 0.0179 | 0.7070 | 0.512 |

mean target = 0.5121

## Controlli anti-leakage e avvertenze

- Folds are chronological: a model is fitted only on rows dated before the first day of its test quarter.
- Imputers, scalers and encoders are part of the fitted pipeline (train rows only).
- Elo variants and prior-match counts are recomputed here in date order; every row of a calendar date is read before any result of that date is applied (the rating is updated after the prediction).
- Dataset form / head-to-head / ranking columns are pre-match by construction (dataset_builder applies the same same-day batching; ranking snapshot dated on or before the match).
- Dynamic-Elo hyper-parameters are selected on the 730 days that precede the first test fold.
- The inferred-circuit label uses only earlier-dated matches.
- Post-match columns (atp_score, atp_minutes, profit / edge columns) are never features.
- avg_* odds columns are the bookmaker average of the snapshot stored on fixture.odds. The dataset has no capture timestamp: historical fixtures get their odds from get_odds calls made on or after the match day (service/import_fixtures.py), so they are presumably the last pre-match quote (closing) but this cannot be verified offline. At serving time the model reads the snapshot available when the prediction is generated (hours or days before the match): market-based contenders are therefore likely better informed here than they would be in production.
- ATP enrichment (age, height, hand, tourney level, round, best_of, match_found) exists only where a row was matched to the Sackmann files (see folds[].test_enrichment_matched_share). In a fold where the share is 0 the 'true features' are missing values handled by the fitted imputers, not real player data: there the train/serve comparison measures 'declared missing' against 'filled with 0'.
