"""Shared helpers for the Evercrest KYB toolkit. Standard library only."""
import re
import unicodedata
from difflib import SequenceMatcher

HONORIFICS = {"mr", "mrs", "ms", "miss", "dr", "sir", "hon", "atty", "engr", "prof", "sheikh", "haji", "hajji"}

LEGAL_SUFFIXES = {
    "ltd", "limited", "llc", "l l c", "inc", "incorporated", "corp", "corporation", "co", "company",
    "plc", "gmbh", "ag", "sa", "s a", "sas", "sarl", "srl", "spa", "bv", "b v", "nv", "n v", "pte",
    "pty", "sdn", "bhd", "llp", "lp", "oy", "ab", "as", "a s", "aps", "kft", "sro", "s r o", "doo",
    "d o o", "ood", "eood", "jsc", "ojsc", "pjsc", "cjsc", "ooo", "zao", "oao", "kk", "kabushiki",
    "kaisha", "group", "holdings", "holding", "international", "intl", "the", "fze", "fzco", "fz",
    "llc fz", "dmcc", "wll", "ltda", "cia", "sl", "s l", "sc", "pvt", "private", "opc",
}

COUNTRIES = """AF AFG afghanistan|AL ALB albania|DZ DZA algeria|AD AND andorra|AO AGO angola|AG ATG antigua and barbuda|
AR ARG argentina|AM ARM armenia|AU AUS australia|AT AUT austria|AZ AZE azerbaijan|BS BHS bahamas|BH BHR bahrain|
BD BGD bangladesh|BB BRB barbados|BY BLR belarus|BE BEL belgium|BZ BLZ belize|BJ BEN benin|BM BMU bermuda|BT BTN bhutan|
BO BOL bolivia|BA BIH bosnia and herzegovina;bosnia|BW BWA botswana|BR BRA brazil|BN BRN brunei;brunei darussalam|
BG BGR bulgaria|BF BFA burkina faso|BI BDI burundi|CV CPV cabo verde;cape verde|KH KHM cambodia|CM CMR cameroon|CA CAN canada|
KY CYM cayman islands|CF CAF central african republic|TD TCD chad|CL CHL chile|CN CHN china;prc;people s republic of china|
CO COL colombia|KM COM comoros;anjouan|CG COG congo;republic of the congo;congo brazzaville|
CD COD democratic republic of the congo;drc;dr congo;congo kinshasa|CR CRI costa rica|CI CIV cote d ivoire;ivory coast|
HR HRV croatia|CU CUB cuba|CW CUW curacao|CY CYP cyprus|CZ CZE czechia;czech republic|DK DNK denmark|DJ DJI djibouti|
DM DMA dominica|DO DOM dominican republic|EC ECU ecuador|EG EGY egypt|SV SLV el salvador|GQ GNQ equatorial guinea|
ER ERI eritrea|EE EST estonia|SZ SWZ eswatini;swaziland|ET ETH ethiopia|FJ FJI fiji|FI FIN finland|FR FRA france|GA GAB gabon|
GM GMB gambia|GE GEO georgia|DE DEU germany|GH GHA ghana|GI GIB gibraltar|GR GRC greece|GD GRD grenada|GT GTM guatemala|
GG GGY guernsey|GN GIN guinea|GW GNB guinea bissau|GY GUY guyana|HT HTI haiti|HN HND honduras|HK HKG hong kong|HU HUN hungary|
IS ISL iceland|IN IND india|ID IDN indonesia|IR IRN iran;islamic republic of iran|IQ IRQ iraq|IE IRL ireland|IM IMN isle of man|
IL ISR israel|IT ITA italy|JM JAM jamaica|JP JPN japan|JE JEY jersey|JO JOR jordan|KZ KAZ kazakhstan|KE KEN kenya|KI KIR kiribati|
KP PRK north korea;dprk;democratic people s republic of korea|KR KOR south korea;republic of korea;korea|XK XKX kosovo|
KW KWT kuwait|KG KGZ kyrgyzstan|LA LAO lao pdr;laos;lao people s democratic republic|LV LVA latvia|LB LBN lebanon|
LS LSO lesotho|LR LBR liberia|LY LBY libya|LI LIE liechtenstein|LT LTU lithuania|LU LUX luxembourg|MO MAC macao;macau|
MG MDG madagascar|MW MWI malawi|MY MYS malaysia|MV MDV maldives|ML MLI mali|MT MLT malta|MH MHL marshall islands|
MR MRT mauritania|MU MUS mauritius|MX MEX mexico|FM FSM micronesia|MD MDA moldova|MC MCO monaco|MN MNG mongolia|
ME MNE montenegro|MA MAR morocco|MZ MOZ mozambique|MM MMR myanmar;burma|NA NAM namibia|NR NRU nauru|NP NPL nepal|
NL NLD netherlands|NZ NZL new zealand|NI NIC nicaragua|NE NER niger|NG NGA nigeria|MK MKD north macedonia;macedonia|
NO NOR norway|OM OMN oman|PK PAK pakistan|PW PLW palau|PS PSE palestine|PA PAN panama|PG PNG papua new guinea|
PY PRY paraguay|PE PER peru|PH PHL philippines|PL POL poland|PT PRT portugal|PR PRI puerto rico|QA QAT qatar|RO ROU romania|
RU RUS russia;russian federation|RW RWA rwanda|KN KNA saint kitts and nevis;st kitts and nevis|LC LCA saint lucia;st lucia|
VC VCT saint vincent and the grenadines|WS WSM samoa|SM SMR san marino|ST STP sao tome and principe|SA SAU saudi arabia|
SN SEN senegal|RS SRB serbia|SC SYC seychelles|SL SLE sierra leone|SG SGP singapore|SK SVK slovakia|SI SVN slovenia|
SB SLB solomon islands|SO SOM somalia|ZA ZAF south africa|SS SSD south sudan|ES ESP spain|LK LKA sri lanka|SD SDN sudan|
SR SUR suriname|SE SWE sweden|CH CHE switzerland|SY SYR syria;syrian arab republic|TW TWN taiwan|TJ TJK tajikistan|
TZ TZA tanzania|TH THA thailand|TL TLS timor leste;east timor|TG TGO togo|TO TON tonga|TT TTO trinidad and tobago|
TN TUN tunisia|TR TUR turkey;turkiye|TM TKM turkmenistan|TC TCA turks and caicos islands|TV TUV tuvalu|UG UGA uganda|
UA UKR ukraine|AE ARE united arab emirates;uae|GB GBR united kingdom;uk;great britain;britain;england;scotland;wales|
US USA united states;usa;united states of america;us|UY URY uruguay|UZ UZB uzbekistan|VU VUT vanuatu|VA VAT holy see;vatican|
VE VEN venezuela|VN VNM vietnam;viet nam|VG VGB virgin islands uk;british virgin islands;bvi|YE YEM yemen|ZM ZMB zambia|
ZW ZWE zimbabwe"""

_COUNTRY_INDEX = {}
for _chunk in COUNTRIES.replace("\n", "").split("|"):
    _parts = _chunk.strip().split(" ", 2)
    if len(_parts) < 3:
        continue
    _iso2, _iso3, _names = _parts
    for _key in [_iso2.lower(), _iso3.lower()] + [n.strip() for n in _names.split(";")]:
        _COUNTRY_INDEX.setdefault(_key, _iso3)


def fold(text):
    """Lower case, strip accents, turn punctuation into spaces."""
    if text is None:
        return ""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace("&", " and ").replace("'", " ")
    text = re.sub(r"[^0-9a-zЀ-ӿ؀-ۿ一-鿿]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def country_code(value):
    """Return ISO3 code for a country name or code, or the folded text if unknown."""
    key = fold(value)
    return _COUNTRY_INDEX.get(key, key.upper() if key else "")


def name_tokens(name, entity=False):
    toks = fold(name).split()
    toks = [t for t in toks if t not in HONORIFICS]
    if entity:
        joined = " " + " ".join(toks) + " "
        for suf in sorted(LEGAL_SUFFIXES, key=len, reverse=True):
            joined = joined.replace(" " + suf + " ", " ")
        toks = joined.split() or toks
    return toks


def _ratio(a, b):
    return SequenceMatcher(None, a, b).ratio()


def name_score(a, b, entity=False):
    """0 to 100 similarity between two names, order-insensitive, initials-aware."""
    ta, tb = name_tokens(a, entity), name_tokens(b, entity)
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return 100.0
    sorted_ratio = _ratio(" ".join(sorted(ta)), " ".join(sorted(tb)))
    joined_ratio = _ratio("".join(ta), "".join(tb))  # catches spacing differences

    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    pool = list(long_)
    parts = []
    for tok in short:
        best, best_i = 0.0, None
        for i, cand in enumerate(pool):
            if len(tok) == 1 or len(cand) == 1:
                r = 0.9 if tok[0] == cand[0] else 0.0
            else:
                r = _ratio(tok, cand)
            if r > best:
                best, best_i = r, i
        parts.append(best)
        if best_i is not None:
            pool.pop(best_i)
    aligned = sum(parts) / len(parts)
    coverage = len(short) / len(long_)
    # All tokens of the shorter name present: strong, but penalise missing tokens a little.
    aligned_score = aligned * (0.85 + 0.15 * coverage)
    if len(short) == 1 and len(long_) > 1:
        aligned_score *= 0.8  # a single shared token is weak evidence
    return round(100 * max(sorted_ratio, joined_ratio, aligned_score), 1)


MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(value):
    """Parse a date into (year, month, day) with None for unknown parts.
    Accepts YYYY-MM-DD, YYYY/MM/DD, DD Mon YYYY, Mon DD YYYY, YYYY, circa YYYY.
    Numeric DD/MM/YYYY is read day first; ambiguous formats should be given as ISO."""
    if value is None:
        return None
    s = fold(value)
    if not s:
        return None
    s = s.replace("circa", "").replace("approximately", "").replace("approx", "").strip()
    m = re.fullmatch(r"(\d{4}) (\d{1,2}) (\d{1,2})", s)
    if m:
        return (int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{1,2}) (\d{1,2}) (\d{4})", s)
    if m:
        return (int(m[3]), int(m[2]), int(m[1]))
    m = re.fullmatch(r"(\d{1,2}) ([a-z]+) (\d{4})", s)
    if m and m[2][:3] in MONTHS:
        return (int(m[3]), MONTHS[m[2][:3]], int(m[1]))
    m = re.fullmatch(r"([a-z]+) (\d{1,2}) (\d{4})", s)
    if m and m[1][:3] in MONTHS:
        return (int(m[3]), MONTHS[m[1][:3]], int(m[2]))
    m = re.fullmatch(r"([a-z]+) (\d{4})", s)
    if m and m[1][:3] in MONTHS:
        return (int(m[2]), MONTHS[m[1][:3]], None)
    m = re.fullmatch(r"(\d{4}) (\d{1,2})", s)
    if m:
        return (int(m[1]), int(m[2]), None)
    m = re.fullmatch(r"(\d{4})", s)
    if m:
        return (int(m[1]), None, None)
    m = re.fullmatch(r"(\d{4}) (?:to )?(\d{4})", s)
    if m:
        return ("range", int(m[1]), int(m[2]))
    return None


def compare_dates(a, b):
    """Return Match, Partial, Mismatch or Not available."""
    pa, pb = parse_date(a), parse_date(b)
    if not pa or not pb:
        return "Not available"
    if pa[0] == "range" or pb[0] == "range":
        rng, other = (pa, pb) if pa[0] == "range" else (pb, pa)
        if other[0] == "range":
            return "Partial" if not (rng[2] < other[1] or other[2] < rng[1]) else "Mismatch"
        return "Partial" if rng[1] <= other[0] <= rng[2] else "Mismatch"
    if pa[0] != pb[0]:
        return "Mismatch"
    for x, y in ((pa[1], pb[1]), (pa[2], pb[2])):
        if x is None or y is None:
            return "Partial"
        if x != y:
            return "Mismatch"
    return "Match"


def compare_codes(a, b):
    """Registration or ID numbers: exact match on alphanumerics."""
    na = re.sub(r"[^0-9A-Z]", "", str(a or "").upper())
    nb = re.sub(r"[^0-9A-Z]", "", str(b or "").upper())
    if not na or not nb:
        return "Not available"
    if na == nb:
        return "Match"
    if na.lstrip("0") == nb.lstrip("0"):
        return "Match"
    return "Mismatch"


def compare_countries(a, b):
    """a or b may be a single country or a list (for example several nationalities)."""
    la = a if isinstance(a, list) else [a]
    lb = b if isinstance(b, list) else [b]
    ca = {country_code(x) for x in la if x}
    cb = {country_code(x) for x in lb if x}
    ca.discard("")
    cb.discard("")
    if not ca or not cb:
        return "Not available"
    return "Match" if ca & cb else "Mismatch"


def compare_addresses(a, b):
    ta, tb = set(fold(a).split()), set(fold(b).split())
    if not ta or not tb:
        return "Not available"
    jac = len(ta & tb) / len(ta | tb)
    if jac >= 0.6:
        return "Match"
    if jac >= 0.25:
        return "Partial"
    return "Mismatch"


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in rows:
        out.append("| " + " | ".join(str(c).replace("|", "/") for c in r) + " |")
    return "\n".join(out)
