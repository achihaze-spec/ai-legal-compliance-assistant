#!/usr/bin/env python3
"""MRZ check digit validator (ICAO Doc 9303) for passports, ID cards and visas.

Supports TD3 (passport, 2 x 44), TD2 (2 x 36), TD1 (ID card, 3 x 30) and MRV-A / MRV-B visas.
Recomputes every check digit, parses the fields, flags expiry, and optionally compares the
MRZ data with the application.

A failed check digit is a strong forgery or tampering signal (or an OCR misread; the script
tests common OCR swaps). A pass is NOT proof the document is genuine: anyone can compute
check digits. Liveness and document authenticity still need the KYC platform.

Usage:
  python3 mrz_check.py --line "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<" --line "L898902C36UTO7408122F1204159ZE184226B<<<<<10"
  python3 mrz_check.py --file mrz.txt [--name "Anna Maria Eriksson" --dob 1974-08-12 --nationality UTO] [--json]
"""
import argparse
import datetime as dt
import json
import sys

sys.path.insert(0, __import__("os").path.dirname(__file__))
from kyb_common import name_score, compare_dates, compare_countries  # noqa: E402

WEIGHTS = (7, 3, 1)
OCR_DIGIT_FIX = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6"})


def char_value(c):
    if c.isdigit():
        return int(c)
    if "A" <= c <= "Z":
        return ord(c) - 55
    if c == "<":
        return 0
    raise ValueError(f"Invalid MRZ character: {c!r}")


def check_digit(field):
    return str(sum(char_value(c) * WEIGHTS[i % 3] for i, c in enumerate(field)) % 10)


def clean(line):
    return line.strip().upper().replace(" ", "").replace("«", "<")


def detect(lines):
    lens = [len(l) for l in lines]
    if len(lines) == 3 and all(n == 30 for n in lens):
        return "TD1"
    if len(lines) == 2 and all(n == 44 for n in lens):
        return "MRV-A" if lines[0][0] == "V" else "TD3"
    if len(lines) == 2 and all(n == 36 for n in lens):
        return "MRV-B" if lines[0][0] == "V" else "TD2"
    raise SystemExit(f"Unrecognised MRZ shape: {len(lines)} lines of lengths {lens}. "
                     "Expect 2x44 (passport), 2x36, or 3x30 (ID card).")


def yymmdd(s, kind):
    try:
        yy, mm, dd = int(s[0:2]), int(s[2:4]), int(s[4:6])
    except ValueError:
        return None
    now = dt.date.today()
    if kind == "dob":
        year = 2000 + yy if 2000 + yy <= now.year else 1900 + yy
    else:
        year = 2000 + yy if yy < 70 else 1900 + yy
    try:
        return dt.date(year, mm, dd)
    except ValueError:
        return None


def names(field):
    surname, _, given = field.partition("<<")
    return surname.replace("<", " ").strip(), given.replace("<", " ").strip()


def checks_for(kind, L):
    """Return (fields, checks) where checks = [(label, data, digit)]."""
    if kind in ("TD3", "MRV-A", "TD2", "MRV-B"):
        l1, l2 = L
        f = {"document_type": l1[0:2].rstrip("<"), "issuing_state": l1[2:5].rstrip("<"),
             "document_number": l2[0:9], "nationality": l2[10:13].rstrip("<"),
             "dob_raw": l2[13:19], "sex": l2[20], "expiry_raw": l2[21:27]}
        f["surname"], f["given_names"] = names(l1[5:])
        checks = [("Document number", l2[0:9], l2[9]), ("Date of birth", l2[13:19], l2[19]),
                  ("Expiry date", l2[21:27], l2[27])]
        if kind == "TD3":
            f["optional_data"] = l2[28:42].rstrip("<")
            pn_cd = l2[42]
            if not (pn_cd == "<" and set(l2[28:42]) == {"<"}):
                checks.append(("Personal number", l2[28:42], pn_cd))
            checks.append(("Composite", l2[0:10] + l2[13:20] + l2[21:43], l2[43]))
        elif kind == "TD2":
            f["optional_data"] = l2[28:35].rstrip("<")
            checks.append(("Composite", l2[0:10] + l2[13:20] + l2[21:35], l2[35]))
        else:
            f["optional_data"] = l2[28:].rstrip("<")
        return f, checks
    l1, l2, l3 = L
    f = {"document_type": l1[0:2].rstrip("<"), "issuing_state": l1[2:5].rstrip("<"),
         "dob_raw": l2[0:6], "sex": l2[7], "expiry_raw": l2[8:14], "nationality": l2[15:18].rstrip("<"),
         "optional_data": (l1[15:30] + "|" + l2[18:29]).replace("<", "").strip("|")}
    f["surname"], f["given_names"] = names(l3)
    doc, doc_cd = l1[5:14], l1[14]
    if doc_cd == "<":  # long document number continues in optional data
        tail = l1[15:30].split("<")[0]
        doc, doc_cd = doc + tail[:-1], tail[-1:] or "<"
    f["document_number"] = doc
    checks = [("Document number", doc, doc_cd), ("Date of birth", l2[0:6], l2[6]),
              ("Expiry date", l2[8:14], l2[14]),
              ("Composite", l1[5:30] + l2[0:7] + l2[8:15] + l2[18:29], l2[29])]
    return f, checks


def evaluate(lines, app=None):
    L = [clean(l) for l in lines if l.strip()]
    kind = detect(L)
    fields, checks = checks_for(kind, L)
    results = []
    for label, data, given in checks:
        try:
            calc = check_digit(data)
        except ValueError as e:
            results.append({"field": label, "data": data, "given": given, "calculated": None,
                            "result": "Fail", "note": str(e)})
            continue
        ok = calc == given
        note = ""
        if not ok and label != "Composite":
            fixed = data.translate(OCR_DIGIT_FIX) if label != "Document number" else data
            given_fixed = given.translate(OCR_DIGIT_FIX)
            if label == "Document number":
                fixed = data.translate(str.maketrans({"O": "0", "Q": "0"}))
            if check_digit(fixed) == given_fixed and (fixed != data or given_fixed != given):
                note = f"Passes if read as {fixed}/{given_fixed}: likely OCR misread. Recheck the image."
        results.append({"field": label, "data": data, "given": given, "calculated": calc,
                        "result": "Pass" if ok else "Fail", "note": note})

    dob = yymmdd(fields["dob_raw"], "dob")
    exp = yymmdd(fields["expiry_raw"], "exp")
    fields["date_of_birth"] = dob.isoformat() if dob else "invalid"
    fields["expiry_date"] = exp.isoformat() if exp else "invalid"
    today = dt.date.today()
    flags = []
    if exp and exp < today:
        flags.append(f"Document expired on {exp.isoformat()}.")
    if not dob or not exp:
        flags.append("A date field is not a valid calendar date.")
    if fields["sex"] not in "MFX<":
        flags.append(f"Sex field '{fields['sex']}' is not M, F, X or <.")
    if any(r["result"] == "Fail" for r in results):
        flags.append("Check digit failure: strong forgery or tampering signal unless explained by an OCR misread. Treat ID as Discrepancy and escalate.")

    comparison = []
    if app:
        full = f"{fields['given_names']} {fields['surname']}".strip()
        if app.get("name"):
            s = name_score(app["name"], full)
            comparison.append(["Name", app["name"], full, f"{'Match' if s >= 90 else 'Partial' if s >= 80 else 'Mismatch'} ({s})"])
        if app.get("dob"):
            comparison.append(["Date of birth", app["dob"], fields["date_of_birth"], compare_dates(app["dob"], fields["date_of_birth"])])
        if app.get("nationality"):
            comparison.append(["Nationality", app["nationality"], fields["nationality"], compare_countries(app["nationality"], fields["nationality"])])
        if app.get("document_number"):
            comparison.append(["Document number", app["document_number"], fields["document_number"].rstrip("<"),
                               "Match" if app["document_number"].upper().replace(" ", "") == fields["document_number"].rstrip("<") else "Mismatch"])
    overall = "Pass" if all(r["result"] == "Pass" for r in results) else "Fail"
    return {"format": kind, "overall": overall, "checks": results, "fields": fields,
            "flags": flags, "application_comparison": comparison}


def to_markdown(r):
    f = r["fields"]
    out = [f"## MRZ check ({r['format']}): {r['overall']}",
           f"{f['given_names']} {f['surname']} | {f['document_type']} {f['document_number'].rstrip('<')} | "
           f"issuer {f['issuing_state']} | nationality {f['nationality']} | DOB {f['date_of_birth']} | "
           f"sex {f['sex']} | expiry {f['expiry_date']}", "",
           "| Field | MRZ data | Given | Calculated | Result | Note |", "|---|---|---|---|---|---|"]
    for c in r["checks"]:
        out.append(f"| {c['field']} | `{c['data']}` | {c['given']} | {c['calculated']} | {c['result']} | {c['note']} |")
    if r["application_comparison"]:
        out += ["", "| Attribute | Application | MRZ | Result |", "|---|---|---|---|"]
        out += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in r["application_comparison"]]
    if r["flags"]:
        out += ["", "Flags:"] + [f"- {x}" for x in r["flags"]]
    out.append("\nA pass confirms internal consistency only, not authenticity. Liveness and document checks stay with the KYC platform.")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--line", action="append", default=[])
    ap.add_argument("--file")
    ap.add_argument("--name")
    ap.add_argument("--dob")
    ap.add_argument("--nationality")
    ap.add_argument("--document-number")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    lines = a.line
    if a.file:
        with open(a.file, encoding="utf-8") as fh:
            lines += [l for l in fh.read().splitlines() if l.strip()]
    if not lines:
        ap.error("give --line twice or three times, or --file")
    app = {k: v for k, v in {"name": a.name, "dob": a.dob, "nationality": a.nationality,
                             "document_number": a.document_number}.items() if v}
    r = evaluate(lines, app or None)
    print(json.dumps(r, indent=2) if a.json else to_markdown(r))


if __name__ == "__main__":
    main()
