#!/usr/bin/env python3
"""Build a run-level catalog of public food shotgun metagenomes.

Sources
  cfmd  curatedFoodMetagenomicData (github.com/SegataLab/cFMD): curated food metagenomes with
        food categories. The backbone of the catalog.
  ena   ENA Portal API. The INSDC archives mirror each other, so this also covers NCBI SRA and
        DDBJ. ENA can wildcard-search sample metadata and returns fastq URLs, sizes and MD5s.
          taxon    runs labeled with a food metagenome taxon (e.g. "food metagenome")
          keyword  runs labeled with another metagenome taxon whose isolation_source or
                   sample_title names a food (lower confidence: review before use)
  gsa   NGDC Genome Sequence Archive (China). Not mirrored to INSDC, so it is queried separately,
        through the run-info export behind its web search (GSA has no official API).

Tiers
  core     in cFMD, or labeled with a food taxon (food / food fermentation / milk / dairy /
           meat / wine / ... metagenome)
  review   labeled with a food-adjacent taxon (fermentation, food production, winery, silage,
           abattoir metagenome)
  keyword  found only by the keyword search

Writes, under --root (default: the data directory that contains this script):
  raw/{cfmd,ena,gsa}/            cached source responses (--refresh re-fetches them)
  catalog/food_shotgun_runs.tsv  one row per run, deduplicated by run accession
  catalog/food_shotgun_runs.csv  the same table for Excel (UTF-8 with BOM)
  catalog/cfmd_unresolved.tsv    cFMD samples with no public INSDC/GSA run accession
  catalog/summary.md             counts and download volume

Standard library only:
  python3 -I scripts/build_catalog.py [--refresh] [--skip-gsa] [--skip-keywords]
"""
import argparse
import collections
import csv
import datetime
import hashlib
import io
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# GSA drops connections from user agents containing "python-urllib", so keep "python" out of it.
UA = "netbio-food-catalog/0.1"
ENA_SEARCH = "https://www.ebi.ac.uk/ena/portal/api/search"
GSA_SEARCH = "https://ngdc.cncb.ac.cn/gsa/search"
GSA_RUNINFO = "https://ngdc.cncb.ac.cn/gsa/search/getRunInfoByCra"
GSA_HTTPS = "https://download.cncb.ac.cn/"
CFMD_BASE = "https://raw.githubusercontent.com/SegataLab/cFMD/main/"
CFMD_FILES = ("cFMD_metadata.tsv", "cFMD_metadata_rules.tsv", "cFMD_datasets.tsv")
METAGENOMES_TAXID = 408169  # NCBI taxonomy root of all "... metagenome" taxa

# Metagenome taxa that submitters use for food samples (NCBI taxonomy id -> name, tier).
FOOD_TAXA = {
    870726: ("food metagenome", "core"),
    1154581: ("food fermentation metagenome", "core"),
    1699855: ("food production metagenome", "review"),  # mostly plant surfaces, hides, enrichments
    1616037: ("milk metagenome", "core"),
    2966151: ("dairy metagenome", "core"),
    2826927: ("meat metagenome", "core"),
    1897733: ("food contamination metagenome", "core"),
    1658780: ("wine metagenome", "core"),
    2202140: ("egg metagenome", "core"),
    1868704: ("grain metagenome", "core"),
    1561046: ("honey metagenome", "core"),
    1326787: ("fermentation metagenome", "review"),  # also industrial and bioreactor fermentations
    2854027: ("winery metagenome", "review"),        # winery surfaces and equipment
    1804158: ("silage metagenome", "review"),        # animal feed
    3075926: ("abattoir metagenome", "review"),      # slaughterhouse environment
}
TAXON_CATEGORY = {
    "milk metagenome": "dairy", "dairy metagenome": "dairy", "meat metagenome": "meat",
    "wine metagenome": "alcohol", "honey metagenome": "other", "egg metagenome": "other",
}

# Searched in isolation_source and sample_title of runs labeled with any other metagenome taxon.
KEYWORDS = (
    "cheese", "kefir", "yogurt", "yoghurt", "koumiss", "raw milk", "whey", "kimchi", "sauerkraut",
    "pickle", "paocai", "sourdough", "kombucha", "vinegar", "natto", "miso", "tempeh", "doenjang",
    "soy sauce", "soybean paste", "fish sauce", "jeotgal", "salami", "sausage", "daqu", "baijiu",
    "jiuqu", "huangjiu", "makgeolli", "koji", "pu-erh", "cocoa", "cacao", "sake", "wine", "beer",
    "fermented food", "food sample",
)
# Keyword hits are dropped when the taxon or the text points to a host or a non-food environment.
NON_FOOD_TAXON = re.compile(
    r"gut|f(a)?ec|stool|human|mouse|murine|\brat\b|oral|skin|vagin|lung|blood|rumen|insect|plant|"
    r"root|rhizo|leaf|phyllo|soil|sediment|marine|seawater|freshwater|lake|river|wastewater|sludge|"
    r"biogas|bioreactor|compost|\bair\b|indoor|built|hot spring|activated", re.I)
NON_FOOD_TEXT = re.compile(
    r"stool|f(a)?eces|f(a)?ecal|\bgut\b|intestin|patient|infant|breast milk|human milk|\bmice\b|"
    r"mouse|\brats?\b|piglet|rumen|saliva|\boral\b|wastewater|sludge|manure|slurry|compost|"
    r"digester", re.I)

# Food category guess for runs outside cFMD, using cFMD's category names plus three extras
# (production_environment, feed, cereals_and_legumes). First match wins, so the order matters:
# a "poultry plant floor" swab is an environment sample, "soy sauce" is fermented, not soy.
CATEGORY_RULES = [(cat, re.compile(rx, re.I)) for cat, rx in (
    ("production_environment", r"\bfloors?\b|\bdrains?\b|\bwalls?\b|kni(fe|ves)|conveyor|"
                               r"cutting boards?|\bswabs?\b|equipment|\bmachines?\b|debagging|"
                               r"carrier tray|\bgloves?\b|\bhands\b|\baprons?\b|\bboots?\b|"
                               r"facility|factory|processing plant|slaughter|abattoir|\bhides?\b|"
                               r"ca?ecal|caeca|\bf(a)?eces\b|\bwastes?\b|wastewater|\bsinks?\b|"
                               r"\bsponges?\b|vp bag|vp machine|food contact|pit mud"),
    ("feed", r"\bfeeds?\b|silage|fodder|forage"),
    ("fermented_beverages", r"water kefir|kombucha|vinegar|kvass|pulque|tepache|chicha|tejuino|"
                            r"pu-?erh|dark tea|black tea|fu brick|\btea\b|fermented beverage"),
    ("alcohol", r"\bwine|\bbeer|\bsake\b|baijiu|daqu|xiaoqu|zaopei|jiupei|jiuqu|huangjiu|"
                r"makgeolli|cider|liquor|brew|\bmead\b"),
    ("dairy", r"chees|kefir|yog(h)?urt|koumiss|kumis|\bmilk|whey|dairy|\bcurd|butter|cream|nunu|"
              r"infant formula"),
    ("fermented_fish", r"fish sauce|jeotgal|fermented (fish|shrimp|seafood)|shrimp paste|yucha|"
                       r"garum"),
    ("fermented_legumes", r"soy ?sauce|soybean paste|bean paste|doubanjiang|\bmeju\b|doenjang|"
                          r"gochujang|\bmiso\b|natto|tempeh|douchi|sufu|fermented (soy|bean)|"
                          r"cheonggukjang"),
    ("fermented_fruits_and_vegetables", r"kimchi|sauerkraut|pickle|paocai|suancai|"
                                        r"fermented vegetable|table olive|brine.?fermented|"
                                        r"grape must"),
    ("fermented_grains", r"sourdough|\bkoji\b|\bogi\b|fermented (rice|grains?)|\bidli\b|"
                         r"\bdosa\b|injera|\bboza\b"),
    ("fermented_seeds", r"cocoa|cacao|coffee"),
    ("fermented_meat", r"salami|fermented sausage|fermented meat|\bnham\b|chorizo"),
    ("fermented_tubers_and_roots", r"cassava|\bgari\b|\bfufu\b"),
    ("probiotics", r"probiotic"),
    ("meat", r"\bmeat|\bbeef|\bpork|chicken|poultry|broiler|\bduck|turkey|\blamb\b|mutton|"
             r"\bveal\b|\bgoat|venison|carcass|sausage|\bham\b|bacon"),
    ("fish", r"\bfish|salmon|shrimp|prawn|seafood|oyster|anchov|tuna|squid|\bclams?\b|mussel"),
    ("fruits_and_vegetables", r"lettuce|spinach|sprout|vegetable|\bfruit|leafy|tomato|radish|"
                              r"\bproduce\b|salad|cucumber|cabbage|mango|avocado|peach|berr(y|ies)|"
                              r"\bapples?\b|melon|cantaloupe|papaya|pineapple|citrus|\boranges?\b|"
                              r"lemon|banana|\bolives?\b|carrot|potato|onion|\bkale\b|\bherbs?\b|"
                              r"basil|cilantro|coriander|parsley|celery|broccoli|cauliflower|"
                              r"\bpeels?\b|mushroom"),
    ("cereals_and_legumes", r"flour|wheat|\brice\b|maize|\bcorn\b|\bgrains?\b|cereal|\boats?\b|"
                            r"barley|sorghum|millet|soybeans?|\bsoy\b|lentil|chickpea|\bbeans?\b|"
                            r"peanut|almond|\bnuts?\b"),
    ("other", r"honey|\beggs?\b|spice"),
)]
NOT_FOOD_CATEGORIES = frozenset({"production_environment", "feed"})
# Some submitters typed contact details into sample titles; keep them out of the catalog.
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"\b(?:tel|tlf|phone|telefono|cell|mobile)\b[\s.:]*\+?\d[\d\s().-]{6,}\d",
                   re.I)
FREE_TEXT = ("isolation_source", "sample_title", "study_title", "center_name")
# Selective enrichment cultures (pathogen detection) do not reflect the food's own community.
ENRICHMENT = re.compile(r"enrich|\bbroths?\b|buffered peptone|\bBPW\b|\bTSB\b|"
                        r"selective (medium|agar)|quasi-?metagenom", re.I)

ENA_FIELDS = (
    "run_accession", "sample_accession", "experiment_accession", "study_accession",
    "secondary_study_accession", "tax_id", "scientific_name", "library_strategy", "library_source",
    "library_layout", "instrument_platform", "instrument_model", "read_count", "base_count",
    "fastq_bytes", "fastq_md5", "fastq_ftp", "isolation_source", "sample_title", "study_title",
    "country", "collection_date", "first_public", "center_name",
)
COLUMNS = (
    "run_accession", "recommended", "archive", "tier", "sources", "flags",
    "food_category", "food_type", "food_category_source", "fermented",
    "sample_accession", "experiment_accession", "study_accession", "secondary_study_accession",
    "scientific_name", "tax_id", "library_strategy", "library_source", "library_layout",
    "instrument_platform", "instrument_model", "read_count", "base_count", "fastq_bytes",
    "isolation_source", "sample_title", "study_title", "country", "collection_date",
    "first_public", "center_name", "cfmd_dataset", "cfmd_sample_id", "cfmd_filtered",
    "keyword_hit", "fastq_urls", "fastq_md5", "fastq_file_bytes",
)
RUN_RE = re.compile(r"^(SRR|ERR|DRR|CRR)\d+$")
TIER_ORDER = {"core": 0, "review": 1, "keyword": 2}
# Runs with these flags are left out of the default download set (same default in download_reads.py).
DEFAULT_SKIP_FLAGS = frozenset({"low_depth", "tiny_run", "no_fastq", "cfmd_filtered",
                                "enrichment", "not_food"})
LOW_DEPTH_BASES = 2e8   # per sample; below this a "WGS" run is often a mislabeled amplicon run
LOW_DEPTH_BYTES = 1.2e8  # same threshold in gzipped fastq bytes, when base counts are unknown
TINY_RUN_BASES, TINY_RUN_BYTES = 1e7, 6e6  # per run: stray runs (e.g. 1 read) inside big samples


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def sum_ints(field, sep=";"):
    vals = [to_int(x) for x in field.split(sep)] if field else []
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else None


def slug(s):
    return re.sub(r"\W+", "_", s).strip("_").lower()


def http(url, data=None, timeout=600, tries=6, pause=0.0):
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    last = None
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                text = r.read().decode("utf-8", "replace")
            time.sleep(pause)
            return text
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                raise
            last = e
        except OSError as e:  # URLError, timeouts, resets
            last = e
        if attempt < tries:
            wait = min(60, 5 * attempt)
            log(f"    retry {attempt}/{tries - 1} in {wait}s: {last}")
            time.sleep(wait)
    raise RuntimeError(f"giving up on {url}: {last}")


def cached(path, refresh, fetch):
    """Text stored at path; fetched and stored first when missing or when refresh is set."""
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8")
    text = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return text


# ---------------------------------------------------------------- sources

def load_cfmd(raw_dir, refresh):
    for name in CFMD_FILES:
        cached(raw_dir / name, refresh, lambda name=name: http(CFMD_BASE + name))
    with open(raw_dir / "cFMD_metadata.tsv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    runs, unresolved = {}, []
    for r in rows:
        accs = [a for a in re.split(r"[;,|\s]+", r["run_accession"].strip()) if RUN_RE.match(a)]
        if not accs:
            unresolved.append(r)
        for a in accs:
            runs.setdefault(a, r)
    return rows, runs, unresolved


def ena_search(params, cache_path, refresh, tries=6, timeout=600):
    data = {"result": "read_run", "fields": ",".join(ENA_FIELDS), "format": "tsv", "limit": "0",
            **params}
    text = cached(cache_path, refresh,
                  lambda: http(ENA_SEARCH, data, timeout=timeout, tries=tries, pause=0.2))
    if not text.strip():
        return []
    return list(csv.DictReader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE))


def ena_by_accession(accs, cache_dir, refresh):
    accs, rows = sorted(accs), []
    for i in range(0, len(accs), 200):
        chunk = accs[i:i + 200]
        key = hashlib.sha1(",".join(chunk).encode()).hexdigest()[:12]
        rows += ena_search({"includeAccessions": ",".join(chunk)}, cache_dir / f"acc_{key}.tsv",
                           refresh)
        log(f"    {min(i + 200, len(accs))}/{len(accs)}")
    return rows


def gsa_find_cras(name, cache_dir, refresh):
    """(total records, CRA accessions) for GSA-native (center NGDC) data of one organism."""
    def fetch():
        cras, total, page = set(), 0, 1
        while True:
            form = {"searchTerm": f"{name}[organism]", "searchField": "",
                    "additionalConditions": "", "centerSelected": "true",
                    "centerSelectedItem": "NGDC", "pageSize": "500", "from": str(page)}
            html = http(GSA_SEARCH, form, pause=1.0)
            m = re.search(r"Total Items:&nbsp;(\d+)", html)
            if m is None:  # no hits
                break
            total = int(m.group(1))
            for line in html.splitlines():
                if "example" not in line.lower():
                    cras.update(re.findall(r"\bCRA\d{6,}\b", line))
            if page * 500 >= total or page >= 100:
                break
            page += 1
        return "\n".join([f"total\t{total}", *sorted(cras)]) + "\n"
    lines = cached(cache_dir / f"search_{slug(name)}.txt", refresh, fetch).split("\n")
    return int(lines[0].split("\t")[1]), {x for x in lines[1:] if x}


def gsa_runinfo(cra, cache_dir, refresh):
    def fetch():
        for attempt in range(1, 5):
            text = http(GSA_RUNINFO, {"searchTerm": cra, "totalDatas": "9999",
                                      "downLoadCount": "9999"}, pause=1.0)
            if text.startswith("Run,"):
                return text
            log(f"    {cra}: empty run info, retry {attempt}/4")
            time.sleep(10 * attempt)
        raise RuntimeError(f"no run info for {cra}")
    text = cached(cache_dir / f"runinfo_{cra}.csv", refresh, fetch)
    return list(csv.DictReader(io.StringIO(text)))


GSA_BUCKETS = ("gsa5", "gsa4", "gsa3", "gsa2", "gsa6", "gsa1", "gsa")


def gsa_md5(cra, prefix, cache_dir, refresh):
    """(prefix, {file name: md5}) from the CRA's md5sum.txt; ({}) when unavailable.

    prefix is "<bucket>/<CRA>", taken from the run info's download path. That path is blank for
    many recent releases; the bucket is then found by probing where md5sum.txt exists."""
    def fetch():
        for p in [prefix] if prefix else [f"{b}/{cra}" for b in GSA_BUCKETS]:
            try:
                return f"#prefix\t{p}\n" + http(f"{GSA_HTTPS}{p}/md5sum.txt", tries=3, pause=0.5)
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
        raise RuntimeError("md5sum.txt not found in any bucket")
    try:
        text = cached(cache_dir / f"md5_{cra}.txt", refresh, fetch)
    except Exception as e:  # noqa: BLE001
        log(f"    {cra}: md5sum.txt unavailable ({e})")
        return prefix, {}
    md5s = {}
    for line in text.splitlines():
        if line.startswith("#prefix\t"):
            prefix = prefix or line.split("\t", 1)[1].strip()
            continue
        toks = line.split()
        md5 = next((t for t in toks if re.fullmatch(r"[0-9a-fA-F]{32}", t)), None)
        name = next((t for t in toks if t != md5), None)
        if md5 and name:
            md5s[name.rsplit("/", 1)[-1]] = md5.lower()
    return prefix, md5s


def gsa_kind(row):
    strategy = row.get("LibraryStrategy", "").strip().lower()
    source = row.get("LibrarySource", "").strip().upper()
    if "amplicon" in strategy:
        return "amplicon"
    if "rna" in strategy or "TRANSCRIPT" in source:
        return "rna"
    if strategy in ("wgs", "genome", "wga"):  # GSA often labels shotgun metagenomes "Genome"
        return "shotgun"
    return "other"


# ---------------------------------------------------------------- records

def blank():
    rec = {c: "" for c in COLUMNS}
    rec["sources"], rec["flag_set"] = set(), set()
    return rec


def from_ena(row):
    rec = blank()
    for f in ENA_FIELDS:
        if f in rec and f != "fastq_bytes":
            rec[f] = (row.get(f) or "").strip()
    urls = [u if u.startswith(("http://", "https://", "ftp://")) else "https://" + u
            for u in (row.get("fastq_ftp") or "").split(";") if u]
    sizes = row.get("fastq_bytes") or ""
    rec.update(archive="INSDC", fastq_urls=";".join(urls), fastq_file_bytes=sizes,
               fastq_bytes=str(sum_ints(sizes) or ""))
    return rec


def from_gsa(row):
    rec = blank()
    names = [n for n in row.get("FileName", "").split("|") if n]
    urls = [re.sub(r"^ftp://download\.big\.ac\.cn/", GSA_HTTPS, p)
            for p in row.get("Download_path", "").split("|") if p]
    sizes = row.get("FileSize", "").split("|") if names else []
    rec["_files"] = names  # to build URLs when Download_path is blank
    rec.update(
        run_accession=row["Run"], archive="GSA", sample_accession=row.get("BioSample", ""),
        experiment_accession=row.get("Experiment", ""), study_accession=row.get("BioProject", ""),
        secondary_study_accession=row.get("Submission", ""),
        scientific_name=row.get("ScientificName", ""), tax_id=row.get("TaxID", ""),
        library_strategy=row.get("LibraryStrategy", ""),
        library_source=row.get("LibrarySource", ""),
        library_layout=row.get("LibraryLayout", "").upper(),
        instrument_platform=row.get("Platform", "").upper().replace(" ", "_"),
        sample_title=row.get("SampleName", "") or row.get("Title", ""),
        first_public=row.get("ReleaseDate", ""), center_name=row.get("Organization", ""),
        fastq_urls=";".join(urls), fastq_file_bytes=";".join(sizes),
        fastq_bytes=str(sum_ints(";".join(sizes)) or ""),
    )
    return rec


def from_cfmd_only(run, r):
    rec = blank()
    rec.update(run_accession=run, archive="GSA" if run.startswith("CRR") else "INSDC",
               sample_accession=r["sample_accession"],
               experiment_accession=r["experiment_accession"],
               study_accession=r["project_accession"] or r["study_accession"],
               secondary_study_accession=r["study_accession"],
               library_layout=r["library_layout"], instrument_platform=r["sequencing_platform"],
               collection_date=r["collection_date"])
    rec["flag_set"].add("not_found_in_archive")
    return rec


def merge(catalog, rec, source):
    """Add rec to the catalog, or fill the gaps of the existing record for the same run."""
    cur = catalog.setdefault(rec["run_accession"], rec)
    if cur is not rec:
        for k, v in rec.items():
            if k in ("sources", "flag_set"):
                cur[k] |= v
            elif v and not cur.get(k):
                cur[k] = v
    cur["sources"].add(source)
    return cur


def apply_cfmd(rec, r):
    rec.update(food_category=r["category"], food_type=r["type"], food_category_source="cfmd",
               fermented=r["fermented/non-fermented"], cfmd_dataset=r["dataset_name"],
               cfmd_sample_id=r["sample_id"], cfmd_filtered=r["filtered"])
    rec["country"] = rec["country"] or r["country"]


def guess_category(rec, text):
    for cat, rx in CATEGORY_RULES:
        if rx.search(text):
            return cat
    return TAXON_CATEGORY.get(rec["scientific_name"], "")


def finalize(catalog):
    per_sample = collections.defaultdict(lambda: [0, 0, False])  # bases, bytes, bases unknown
    for rec in catalog.values():
        ps = per_sample[rec["sample_accession"] or rec["run_accession"]]
        bases = to_int(rec["base_count"])
        ps[0] += bases or 0
        ps[1] += to_int(rec["fastq_bytes"]) or 0
        ps[2] = ps[2] or bases is None
    for rec in catalog.values():
        for k in FREE_TEXT:
            rec[k] = PHONE.sub("[phone removed]", EMAIL.sub("[email removed]", rec[k]))
        f = rec["flag_set"]
        bases, size, unknown = per_sample[rec["sample_accession"] or rec["run_accession"]]
        if (not unknown and bases < LOW_DEPTH_BASES) or (unknown and 0 < size < LOW_DEPTH_BYTES):
            f.add("low_depth")
        run_bases, run_bytes = to_int(rec["base_count"]), to_int(rec["fastq_bytes"])
        if (run_bases is not None and run_bases < TINY_RUN_BASES) or \
                (run_bytes is not None and run_bytes < TINY_RUN_BYTES):
            f.add("tiny_run")
        if not rec["fastq_urls"]:
            f.add("no_fastq")
        elif not rec["fastq_md5"].replace(";", ""):
            f.add("no_md5")
        platform = rec["instrument_platform"].upper()
        if "NANOPORE" in platform or "PACBIO" in platform:
            f.add("long_read")
        if rec["cfmd_filtered"] == "yes":
            f.add("cfmd_filtered")
        source = rec["library_source"].upper()
        if source and source != "METAGENOMIC":
            f.add("source_" + slug(source))
        if "cfmd" in rec["sources"]:
            rec["tier"] = "core"
        else:
            taxon = FOOD_TAXA.get(to_int(rec["tax_id"]))
            rec["tier"] = taxon[1] if taxon else "keyword"
        text = " | ".join((rec["isolation_source"], rec["sample_title"], rec["study_title"]))
        if not rec["food_category"]:
            cat = guess_category(rec, text)
            if cat:
                rec["food_category"], rec["food_category_source"] = cat, "guess"
        if rec["food_category_source"] == "guess" and rec["food_category"] in NOT_FOOD_CATEGORIES:
            f.add("not_food")
        if "cfmd" not in rec["sources"] and ENRICHMENT.search(text):  # trust cFMD curation
            f.add("enrichment")
        rec["flags"] = ";".join(sorted(f))


def in_default_set(rec):
    return rec["tier"] == "core" and not (set(rec["flags"].split(";")) & DEFAULT_SKIP_FLAGS)


# ---------------------------------------------------------------- output

def write_tsv(path, header, rows):
    def clean(v):
        return re.sub(r"[\t\r\n]+", " ", str(v))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\t".join(header) + "\n")
        for r in rows:
            f.write("\t".join(clean(r.get(h, "")) for h in header) + "\n")


def write_csv(path, header, rows):
    """The same table as CSV with a UTF-8 BOM, which Excel opens directly."""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow([re.sub(r"[\t\r\n]+", " ", str(r.get(h, ""))) for h in header])


def stats(recs):
    samples = {r["sample_accession"] or r["run_accession"] for r in recs}
    size = sum(to_int(r["fastq_bytes"]) or 0 for r in recs)
    bases = sum(to_int(r["base_count"]) or 0 for r in recs)
    return len(recs), len(samples), size, bases


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def tb(n):
    return f"{n / 1e12:,.2f}"


def summarize(recs, ctx):
    md = [f"# Food shotgun metagenome catalog\n\nBuilt {datetime.date.today().isoformat()} "
          f"by `scripts/build_catalog.py`. Sizes are gzipped FASTQ (TB = 10^12 bytes).\n"]
    default = [r for r in recs if in_default_set(r)]
    n, s, size, bases = stats(default)
    md.append(f"**Recommended set** (column `recommended` = yes, also what download_reads.py "
              f"selects by default: tier core, without "
              f"{', '.join(sorted(DEFAULT_SKIP_FLAGS))}): **{n:,} runs / {s:,} samples / "
              f"{tb(size)} TB** ({bases / 1e12:,.1f} Tbp).\n")

    rows = []
    for tier in TIER_ORDER:
        sub = [r for r in recs if r["tier"] == tier]
        n, s, size, _ = stats(sub)
        nd = sum(1 for r in sub if in_default_set(r))
        rows.append((tier, f"{n:,}", f"{s:,}", tb(size), f"{nd:,}"))
    md.append("## By tier\n\n" + table(("tier", "runs", "samples", "TB", "recommended"), rows))

    rows = []
    for archive in ("INSDC", "GSA"):
        n, s, size, _ = stats([r for r in default if r["archive"] == archive])
        rows.append((archive, f"{n:,}", f"{s:,}", tb(size)))
    md.append("## Recommended set by archive\n\n" + table(("archive", "runs", "samples", "TB"), rows))

    by_cat = collections.defaultdict(list)
    for r in default:
        by_cat[r["food_category"] or "(unknown)"].append(r)
    rows = []
    for cat, sub in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
        n, s, size, _ = stats(sub)
        guessed = sum(1 for r in sub if r["food_category_source"] == "guess")
        rows.append((cat, f"{n:,}", f"{s:,}", tb(size), f"{guessed:,}"))
    md.append("## Recommended set by food category\n\ncFMD categories; for runs outside cFMD the "
              "category is guessed from isolation_source / titles (column *guessed*). "
              "`cereals_and_legumes` is an extra category; guessed `production_environment` "
              "and `feed` runs are flagged `not_food` and left out of the default set.\n\n"
              + table(("category", "runs", "samples", "TB", "guessed"), rows))

    combos = collections.Counter(";".join(sorted(r["sources"])) for r in recs)
    md.append("## Which source found each run (all tiers)\n\n"
              + table(("sources", "runs"), [(k, f"{v:,}") for k, v in combos.most_common()]))
    cfmd_insdc = [r for r in recs if "cfmd" in r["sources"] and r["archive"] == "INSDC"]
    labeled = sum(1 for r in cfmd_insdc
                  if FOOD_TAXA.get(to_int(r["tax_id"]), ("", ""))[1] == "core")
    if cfmd_insdc:
        md.append(f"Of {len(cfmd_insdc):,} cFMD runs in INSDC, {labeled:,} "
                  f"({100 * labeled / len(cfmd_insdc):.0f}%) carry a core food taxon label; the "
                  f"rest are labeled e.g. plain `metagenome`, so an organism-name search alone "
                  f"misses them.\n")

    flags = collections.Counter(fl for r in recs for fl in r["flags"].split(";") if fl)
    md.append("## Flags (all tiers)\n\n" + table(("flag", "runs"),
                                                [(k, f"{v:,}") for k, v in flags.most_common()]))
    platforms = collections.Counter(r["instrument_platform"] or "(unknown)" for r in default)
    md.append("## Recommended set by platform\n\n"
              + table(("platform", "runs"), [(k, f"{v:,}") for k, v in platforms.most_common()]))

    if ctx.get("ena_taxon_counts"):
        md.append("## ENA taxon queries (WGS runs)\n\n" + table(
            ("taxon", "tier", "runs"),
            [(a, b, f"{c:,}") for a, b, c in ctx["ena_taxon_counts"]]))
    if ctx.get("keyword_counts"):
        md.append("## ENA keyword queries\n\n" + table(
            ("keyword", "hits", "kept"), [(a, f"{b:,}", f"{c:,}") for a, b, c in
                                          ctx["keyword_counts"]]))
    if ctx.get("gsa_counts"):
        md.append("## GSA (NGDC-native records per taxon)\n\n" + table(
            ("taxon", "records", "CRA"), [(a, f"{b:,}", f"{c:,}") for a, b, c in
                                          ctx["gsa_counts"]]))
        kinds = ctx["gsa_kinds"]
        md.append("GSA runs with a food taxon, by library strategy: " + ", ".join(
            f"{k} {v:,}" for k, v in kinds.most_common())
                  + ". Shotgun = WGS/Genome/WGA; `other` is kept only when METAGENOMIC and "
                    "≥1 GB (flag `gsa_strategy_other`). Download links rebuilt from file names "
                    f"for {ctx.get('gsa_urls_built', 0):,} runs whose export had no path.\n")
    unresolved = ctx.get("unresolved", [])
    if unresolved:
        by_origin = collections.Counter(r["database_origin"] or "(blank)" for r in unresolved)
        md.append(f"## cFMD samples without a public run accession\n\n{len(unresolved)} samples "
                  f"(see `cfmd_unresolved.tsv`): "
                  + ", ".join(f"{k} {v}" for k, v in by_origin.most_common()) + ".\n")
    if ctx.get("failures"):
        md.append("## Failures (re-run to retry; cached results are reused)\n\n"
                  + "\n".join(f"- {x}" for x in ctx["failures"]))
    return "\n\n".join(md) + "\n"


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent,
                    help="data directory (default: parent of scripts/)")
    ap.add_argument("--refresh", action="store_true", help="re-fetch all cached source data")
    ap.add_argument("--skip-gsa", action="store_true", help="do not query GSA")
    ap.add_argument("--skip-keywords", action="store_true", help="skip the ENA keyword search")
    a = ap.parse_args()
    raw, out = a.root / "raw", a.root / "catalog"
    out.mkdir(parents=True, exist_ok=True)
    catalog, ctx = {}, collections.defaultdict(list)

    log("[1/5] cFMD metadata")
    cfmd_rows, cfmd_runs, unresolved = load_cfmd(raw / "cfmd", a.refresh)
    ctx["unresolved"] = unresolved
    log(f"    {len(cfmd_rows):,} samples; {len(cfmd_runs):,} runs with a public accession; "
        f"{len(unresolved)} samples without")

    log("[2/5] ENA: WGS runs labeled with food metagenome taxa")
    for taxid, (name, tier) in FOOD_TAXA.items():
        rows = ena_search({"query": f'tax_tree({taxid}) AND library_strategy="WGS"'},
                          raw / "ena" / f"taxon_{taxid}.tsv", a.refresh)
        for row in rows:
            merge(catalog, from_ena(row), "ena_taxon")
        ctx["ena_taxon_counts"].append((name, tier, len(rows)))
        log(f"    {name:<32} {len(rows):>6,}")

    if a.skip_keywords:
        log("[3/5] ENA keyword search skipped")
    else:
        log("[3/5] ENA: keyword search in isolation_source / sample_title")
        for term in KEYWORDS:
            query = (f'tax_tree({METAGENOMES_TAXID}) AND library_strategy="WGS" AND '
                     f'(isolation_source="*{term}*" OR sample_title="*{term}*")')
            try:
                rows = ena_search({"query": query}, raw / "ena" / f"keyword_{slug(term)}.tsv",
                                  a.refresh, tries=3, timeout=300)
            except Exception as e:  # noqa: BLE001
                ctx["failures"].append(f"ENA keyword '{term}': {e}")
                log(f"    {term}: failed ({e})")
                continue
            kept = 0
            # ENA wildcards match inside words ("*wine*" hits "swine"): require a word start.
            word = re.compile(r"\b" + re.escape(term), re.I)
            for row in rows:
                if to_int(row.get("tax_id")) in FOOD_TAXA:
                    continue  # already found by the taxon search
                if not word.search(f"{row.get('isolation_source') or ''} "
                                   f"{row.get('sample_title') or ''}"):
                    continue
                text = " ".join(row.get(k) or "" for k in
                                ("isolation_source", "sample_title", "study_title"))
                if NON_FOOD_TAXON.search(row.get("scientific_name") or "") or \
                        NON_FOOD_TEXT.search(text):
                    continue
                rec = merge(catalog, from_ena(row), "ena_keyword")
                hits = set(filter(None, rec["keyword_hit"].split(";"))) | {term}
                rec["keyword_hit"] = ";".join(sorted(hits))
                kept += 1
            ctx["keyword_counts"].append((term, len(rows), kept))
            log(f"    {term:<16} {len(rows):>6,} hits {kept:>6,} kept")

    log("[4/5] cFMD runs not found above: metadata and URLs from ENA")
    missing = [r for r in cfmd_runs if r not in catalog and not r.startswith("CRR")]
    for row in ena_by_accession(missing, raw / "ena", a.refresh) if missing else []:
        merge(catalog, from_ena(row), "cfmd")

    if a.skip_gsa:
        log("[5/5] GSA skipped")
    else:
        log("[5/5] GSA (NGDC): runs labeled with food metagenome taxa")
        cras = {r["study_accession"] for run, r in cfmd_runs.items()
                if run.startswith("CRR") and r["study_accession"].startswith("CRA")}
        for taxid, (name, tier) in FOOD_TAXA.items():
            try:
                total, found = gsa_find_cras(name, raw / "gsa", a.refresh)
            except Exception as e:  # noqa: BLE001
                ctx["failures"].append(f"GSA search '{name}': {e}")
                log(f"    {name}: failed ({e})")
                continue
            ctx["gsa_counts"].append((name, total, len(found)))
            log(f"    {name:<32} {total:>6,} records in {len(found):,} CRA")
            cras |= found
        kinds, gsa_recs, gsa_prefix = collections.Counter(), collections.defaultdict(list), {}
        for i, cra in enumerate(sorted(cras), 1):
            try:
                rows = gsa_runinfo(cra, raw / "gsa", a.refresh)
            except Exception as e:  # noqa: BLE001
                ctx["failures"].append(f"GSA run info {cra}: {e}")
                log(f"    {cra}: failed ({e})")
                continue
            for row in rows:
                run = row.get("Run", "")
                if row.get("Center") != "NGDC" or not run.startswith("CRR"):
                    continue
                in_cfmd = run in cfmd_runs
                if to_int(row.get("TaxID")) not in FOOD_TAXA and not in_cfmd:
                    continue
                kind = gsa_kind(row)
                kinds[kind] += 1
                metagenomic_big = (row.get("LibrarySource", "").upper() == "METAGENOMIC" and
                                   (sum_ints(row.get("FileSize", "").replace("|", ";")) or 0)
                                   >= 1e9)
                if not (kind == "shotgun" or in_cfmd or (kind == "other" and metagenomic_big)):
                    continue
                rec = from_gsa(row)
                if kind == "other":
                    rec["flag_set"].add("gsa_strategy_other")
                ftype = row.get("FileType", "").strip().lower()
                if ftype and ftype not in ("fastq", "fq"):
                    rec["flag_set"].add(f"filetype_{slug(ftype)}")
                rec = merge(catalog, rec, "cfmd" if in_cfmd else "gsa_taxon")
                m = re.search(r"download\.big\.ac\.cn/(.+?/CRA\d+)/", row.get("Download_path", ""))
                if m:
                    gsa_prefix.setdefault(cra, m.group(1))
                gsa_recs[cra].append(rec)
            if i % 20 == 0 or i == len(cras):
                log(f"    run info {i}/{len(cras)} CRA")
        ctx["gsa_kinds"] = kinds
        log("    md5sum.txt per CRA (and the storage bucket where the export has no path)")
        built = 0
        for cra, recs in gsa_recs.items():
            prefix, md5s = gsa_md5(cra, gsa_prefix.get(cra), raw / "gsa", a.refresh)
            for rec in recs:
                if rec["fastq_urls"]:
                    names = [u.rsplit("/", 1)[-1] for u in rec["fastq_urls"].split(";") if u]
                else:
                    names = rec.get("_files") or []
                    # only when md5sum.txt lists the files, i.e. they exist under that prefix
                    if prefix and names and all(n in md5s for n in names):
                        rec["fastq_urls"] = ";".join(
                            f"{GSA_HTTPS}{prefix}/{rec['run_accession']}/{n}" for n in names)
                        built += 1
                rec["fastq_md5"] = ";".join(md5s.get(n, "") for n in names)
        ctx["gsa_urls_built"] = built

    for run, r in cfmd_runs.items():
        rec = catalog.get(run) or merge(catalog, from_cfmd_only(run, r), "cfmd")
        rec["sources"].add("cfmd")
        apply_cfmd(rec, r)

    finalize(catalog)
    recs = sorted(catalog.values(), key=lambda r: (TIER_ORDER[r["tier"]], r["archive"],
                                                   r["study_accession"], r["run_accession"]))
    for r in recs:
        r["recommended"] = "yes" if in_default_set(r) else "no"
        r["sources"] = ";".join(sorted(r["sources"]))
    write_tsv(out / "food_shotgun_runs.tsv", COLUMNS, recs)
    write_csv(out / "food_shotgun_runs.csv", COLUMNS, recs)
    for r in recs:
        r["sources"] = set(r["sources"].split(";"))
    write_tsv(out / "cfmd_unresolved.tsv",
              ("dataset_name", "sample_id", "category", "type", "database_origin",
               "sample_accession", "run_accession", "study_accession", "project_accession",
               "n_of_bases"), unresolved)
    (out / "summary.md").write_text(summarize(recs, ctx), encoding="utf-8")
    log(f"done: {len(recs):,} runs -> {out / 'food_shotgun_runs.tsv'}")
    log(f"summary: {out / 'summary.md'}")


if __name__ == "__main__":
    main()
