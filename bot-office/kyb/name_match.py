#!/usr/bin/env python3
"""Screening hit matcher: fuzzy name match plus strong identifier comparison.

Builds the "2 strong identifiers beyond the name" table from the OSINT SOP for every hit and
suggests a disposition. The analyst confirms; the script never closes a hit on its own.

Strong identifiers: DOB or incorporation date, nationality or country, address,
registration or ID number.

Input JSON:
{
  "subject": {"name": "Juan Dela Cruz", "type": "person", "dob": "1980-05-14",
              "nationality": "Philippines", "address": "Makati City, Philippines",
              "id_number": "P1234567A", "aliases": ["Juan D. Cruz"]},
  "hits": [
    {"source": "OFAC SDN", "hit_name": "DELA CRUZ, Juan", "dob": "1975",
     "nationality": "PH", "address": "", "id_number": "", "list_id": "12345"}
  ]
}
For an entity use "type": "entity", "incorporation_date", "country", "reg_number".

Usage: python3 name_match.py hits.json [--json]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from kyb_common import (name_score, compare_dates, compare_countries, compare_codes,  # noqa: E402
                        compare_addresses, md_table)


def flip_list_name(n):
    """'DELA CRUZ, Juan' -> 'Juan DELA CRUZ' (list style surname first)."""
    if n and n.count(",") == 1:
        last, first = [x.strip() for x in n.split(",")]
        return f"{first} {last}"
    return n


def best_name_score(subject, hit_name, entity):
    names = [subject["name"]] + list(subject.get("aliases", []))
    cands = {hit_name, flip_list_name(hit_name)}
    best = (0.0, subject["name"])
    for s in names:
        for h in cands:
            sc = name_score(s, h, entity)
            if sc > best[0]:
                best = (sc, s)
    return best


def assess(subject, hit):
    entity = subject.get("type", "person") == "entity"
    score, used = best_name_score(subject, hit.get("hit_name", ""), entity)
    if entity:
        idents = [
            ("Incorporation date", subject.get("incorporation_date"), hit.get("incorporation_date") or hit.get("dob"), compare_dates),
            ("Country", subject.get("country"), hit.get("country") or hit.get("nationality"), compare_countries),
            ("Address", subject.get("address"), hit.get("address"), compare_addresses),
            ("Registration no.", subject.get("reg_number"), hit.get("reg_number") or hit.get("id_number"), compare_codes),
        ]
    else:
        idents = [
            ("Date of birth", subject.get("dob"), hit.get("dob"), compare_dates),
            ("Nationality", subject.get("nationality"), hit.get("nationality"), compare_countries),
            ("Address", subject.get("address"), hit.get("address"), compare_addresses),
            ("ID number", subject.get("id_number"), hit.get("id_number"), compare_codes),
        ]
    rows, matched, mismatched, partial = [], [], [], []
    for label, sv, hv, fn in idents:
        res = fn(sv, hv)
        rows.append([label, sv or "-", (", ".join(hv) if isinstance(hv, list) else hv) or "-", res])
        if res == "Match":
            matched.append(label)
        elif res == "Mismatch":
            mismatched.append(label)
        elif res == "Partial":
            partial.append(label)

    band = "Strong" if score >= 90 else "Possible" if score >= 80 else "Weak"
    hard = [m for m in mismatched if m in ("Date of birth", "Incorporation date", "ID number", "Registration no.")]
    if band == "Weak":
        disp, why = "False Positive (suggested)", f"name similarity only {score}"
    elif hard and len(matched) >= 2:
        disp, why = "Inconclusive", f"{', '.join(matched)} match but {', '.join(hard)} differ (second ID document or data error?). RFI and escalate"
    elif hard:
        disp, why = "False Positive (suggested)", "differs on " + ", ".join(hard)
    elif len(matched) >= 2:
        disp, why = "True Match (suggested)", f"{len(matched)} strong identifiers match: " + ", ".join(matched)
        if mismatched:
            disp, why = "Inconclusive", f"{', '.join(matched)} match but {', '.join(mismatched)} differ"
    elif not matched and len(mismatched) >= 2:
        disp, why = "False Positive (suggested)", "differs on " + ", ".join(mismatched)
    else:
        n = len(matched)
        disp, why = "Inconclusive", f"only {n} strong identifier{'s' if n != 1 else ''} confirmed" + (
            f"; partial: {', '.join(partial)}" if partial else "") + ". RFI for identifiers, escalate if unresolved"
    return {"source": hit.get("source", ""), "list_id": hit.get("list_id", ""), "hit_name": hit.get("hit_name", ""),
            "matched_against": used, "name_score": score, "name_band": band, "identifiers": rows,
            "strong_matched": matched, "mismatched": mismatched, "suggested_disposition": disp, "reason": why}


def to_markdown(subject, results):
    out = [f"## Hit review: {subject['name']}", ""]
    summary = [[r["source"], r["hit_name"], f"{r['name_score']} ({r['name_band']})",
                len(r["strong_matched"]), r["suggested_disposition"], r["reason"]] for r in results]
    out.append(md_table(["Source", "Hit", "Name score", "Strong IDs matched", "Suggested disposition", "Reason"], summary))
    for r in results:
        out += ["", f"### {r['source']}: {r['hit_name']}" + (f" (list ID {r['list_id']})" if r["list_id"] else ""),
                md_table(["Identifier", "Subject", "Hit", "Result"], r["identifiers"])]
    out.append("\nRule: True Match needs at least 2 strong identifiers beyond the name. Suggestions are for the analyst to confirm.")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    with open(a.input, encoding="utf-8") as fh:
        data = json.load(fh)
    results = [assess(data["subject"], h) for h in data.get("hits", [])]
    print(json.dumps(results, indent=2) if a.json else to_markdown(data["subject"], results))


if __name__ == "__main__":
    main()
