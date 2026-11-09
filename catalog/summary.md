# Food shotgun metagenome catalog

Built 2026-11-09 by `scripts/build_catalog.py`. Sizes are gzipped FASTQ (TB = 10^12 bytes).


**Recommended set** (column `recommended` = yes, also what download_reads.py selects by default: tier core, without cfmd_filtered, enrichment, low_depth, no_fastq, not_food, tiny_run): **11,184 runs / 10,005 samples / 39.25 TB** (67.4 Tbp).


## By tier

| tier | runs | samples | TB | recommended |
|---|---|---|---|---|
| core | 13,672 | 12,421 | 40.48 | 11,184 |
| review | 4,212 | 4,055 | 11.40 | 0 |
| keyword | 948 | 829 | 2.94 | 0 |

## Recommended set by archive

| archive | runs | samples | TB |
|---|---|---|---|
| INSDC | 10,402 | 9,223 | 32.64 |
| GSA | 782 | 782 | 6.61 |

## Recommended set by food category

cFMD categories; for runs outside cFMD the category is guessed from isolation_source / titles (column *guessed*). `cereals_and_legumes` is an extra category; guessed `production_environment` and `feed` runs are flagged `not_food` and left out of the default set.

| category | runs | samples | TB | guessed |
|---|---|---|---|---|
| dairy | 4,103 | 3,590 | 12.32 | 1,801 |
| (unknown) | 1,465 | 1,356 | 8.81 | 0 |
| fruits_and_vegetables | 1,093 | 743 | 2.98 | 835 |
| meat | 1,067 | 1,033 | 3.83 | 873 |
| alcohol | 749 | 723 | 3.26 | 708 |
| fermented_beverages | 704 | 692 | 1.30 | 244 |
| fermented_fruits_and_vegetables | 501 | 405 | 1.44 | 439 |
| other | 477 | 477 | 0.43 | 459 |
| fish | 241 | 241 | 2.39 | 99 |
| fermented_grains | 167 | 161 | 0.59 | 88 |
| fermented_meat | 157 | 157 | 0.56 | 0 |
| fermented_legumes | 151 | 147 | 0.49 | 126 |
| fermented_seeds | 119 | 118 | 0.36 | 55 |
| cereals_and_legumes | 99 | 89 | 0.31 | 99 |
| probiotics | 36 | 19 | 0.04 | 5 |
| fermented_fish | 31 | 31 | 0.12 | 6 |
| fermented_tubers_and_roots | 24 | 24 | 0.02 | 0 |

## Which source found each run (all tiers)

| sources | runs |
|---|---|
| ena_taxon | 12,402 |
| cfmd;ena_taxon | 1,981 |
| cfmd | 1,759 |
| gsa_taxon | 1,477 |
| ena_keyword | 948 |
| cfmd;ena_keyword | 265 |

Of 4,005 cFMD runs in INSDC, 2,359 (59%) carry a core food taxon label; the rest are labeled e.g. plain `metagenome`, so an organism-name search alone misses them.


## Flags (all tiers)

| flag | runs |
|---|---|
| low_depth | 2,808 |
| not_food | 1,680 |
| source_genomic | 1,042 |
| tiny_run | 1,002 |
| source_other | 875 |
| long_read | 458 |
| enrichment | 293 |
| source_transcriptomic | 85 |
| gsa_strategy_other | 78 |
| no_fastq | 66 |
| cfmd_filtered | 61 |
| source_metatranscriptomic | 22 |
| filetype_bam | 11 |
| not_found_in_archive | 6 |
| source_viral_rna | 4 |

## Recommended set by platform

| platform | runs |
|---|---|
| ILLUMINA | 10,400 |
| BGISEQ | 437 |
| OXFORD_NANOPORE | 175 |
| ABI_SOLID | 68 |
| DNBSEQ | 53 |
| PACBIO_SMRT | 21 |
| ELEMENT | 17 |
| ION_TORRENT | 7 |
| LS454 | 6 |

## ENA taxon queries (WGS runs)

| taxon | tier | runs |
|---|---|---|
| food metagenome | core | 5,145 |
| food fermentation metagenome | core | 3,064 |
| food production metagenome | review | 1,642 |
| milk metagenome | core | 870 |
| dairy metagenome | core | 454 |
| meat metagenome | core | 483 |
| food contamination metagenome | core | 175 |
| wine metagenome | core | 133 |
| egg metagenome | core | 0 |
| grain metagenome | core | 12 |
| honey metagenome | core | 426 |
| fermentation metagenome | review | 1,625 |
| winery metagenome | review | 44 |
| silage metagenome | review | 238 |
| abattoir metagenome | review | 72 |

## ENA keyword queries

| keyword | hits | kept |
|---|---|---|
| cheese | 1,005 | 407 |
| kefir | 885 | 2 |
| yogurt | 604 | 5 |
| yoghurt | 3 | 0 |
| koumiss | 30 | 0 |
| raw milk | 0 | 0 |
| whey | 146 | 72 |
| kimchi | 262 | 0 |
| sauerkraut | 15 | 0 |
| pickle | 78 | 18 |
| paocai | 0 | 0 |
| sourdough | 147 | 80 |
| kombucha | 30 | 13 |
| vinegar | 37 | 1 |
| natto | 1 | 0 |
| miso | 16 | 6 |
| tempeh | 4 | 1 |
| doenjang | 0 | 0 |
| soy sauce | 0 | 0 |
| soybean paste | 0 | 0 |
| fish sauce | 0 | 0 |
| jeotgal | 0 | 0 |
| salami | 0 | 0 |
| sausage | 114 | 80 |
| daqu | 472 | 3 |
| baijiu | 285 | 120 |
| jiuqu | 0 | 0 |
| huangjiu | 2 | 2 |
| makgeolli | 0 | 0 |
| koji | 162 | 132 |
| pu-erh | 0 | 0 |
| cocoa | 102 | 10 |
| cacao | 68 | 10 |
| sake | 0 | 0 |
| wine | 2,231 | 232 |
| beer | 73 | 19 |
| fermented food | 0 | 0 |
| food sample | 0 | 0 |

## GSA (NGDC-native records per taxon)

| taxon | records | CRA |
|---|---|---|
| food metagenome | 1,076 | 14 |
| food fermentation metagenome | 1,785 | 28 |
| food production metagenome | 0 | 0 |
| milk metagenome | 230 | 8 |
| dairy metagenome | 53 | 4 |
| meat metagenome | 15 | 1 |
| food contamination metagenome | 0 | 0 |
| wine metagenome | 24 | 2 |
| egg metagenome | 0 | 0 |
| grain metagenome | 40 | 2 |
| honey metagenome | 38 | 1 |
| fermentation metagenome | 3,836 | 54 |
| winery metagenome | 0 | 0 |
| silage metagenome | 234 | 4 |
| abattoir metagenome | 0 | 0 |

GSA runs with a food taxon, by library strategy: other 3,838, shotgun 1,399, rna 166. Shotgun = WGS/Genome/WGA; `other` is kept only when METAGENOMIC and ≥1 GB (flag `gsa_strategy_other`). Download links rebuilt from file names for 1,314 runs whose export had no path.


## cFMD samples without a public run accession

166 samples (see `cfmd_unresolved.tsv`): NCBI 110, MG-RAST 54, (blank) 1, GSA 1.

