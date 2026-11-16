#!/usr/bin/env python3
"""Beneficial ownership calculator for Evercrest KYB reviews.

Computes indirect ownership through every layer, applies the UBO threshold
(25% standard, 10% offshore haven or FATF grey list) and the OFAC 50% Rule,
and prints the working in Markdown for the case report.

Input JSON:
{
  "subject": "TARGET",                      # id of the merchant entity
  "high_risk_jurisdiction": false,          # true -> 10% threshold
  "threshold": 25,                          # optional override
  "parties": [
    {"id": "TARGET", "name": "Target Ltd", "type": "entity", "country": "Seychelles"},
    {"id": "HOLD", "name": "Hold Co Ltd", "type": "entity", "country": "BVI"},
    {"id": "P1", "name": "Jane Doe", "type": "person", "sanctioned": false, "nominee": false,
     "nominee_for": null}
  ],
  "holdings": [
    {"owner": "HOLD", "owned": "TARGET", "pct": 60, "voting_pct": 60, "source": "Register of Members.pdf"},
    {"owner": "P1", "owned": "HOLD", "pct": 50, "source": "HOLD share register.pdf"}
  ]
}

Usage: python3 bo_calc.py case.json [--json]
"""
import argparse
import json
import sys

EPS = 1e-9


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def fmt(x):
    return f"{x:.2f}%"


def build(data):
    parties = {p["id"]: p for p in data["parties"]}
    owners_of = {}
    for h in data["holdings"]:
        for key in ("owner", "owned"):
            if h[key] not in parties:
                raise SystemExit(f"Holding refers to unknown party id: {h[key]}")
        owners_of.setdefault(h["owned"], []).append(h)
    return parties, owners_of


def paths_to(subject, parties, owners_of, field="pct"):
    """All ownership chains ending at subject. Returns list of (person_or_leaf, [holdings])."""
    results, warnings = [], []

    def walk(node, chain, seen):
        ups = owners_of.get(node, [])
        if not ups:
            if node != subject:
                results.append((node, chain))
            return
        for h in ups:
            o = h["owner"]
            if o in seen:
                warnings.append(f"Circular ownership detected at {parties[o]['name']}; chain cut.")
                continue
            new_chain = [h] + chain
            if parties[o].get("type") == "person":
                results.append((o, new_chain))
            else:
                walk(o, new_chain, seen | {o})

    walk(subject, [], {subject})
    return results, warnings


def chain_value(chain, field):
    v = 100.0
    for h in chain:
        v *= float(h.get(field, h.get("pct", 0)) if field == "voting_pct" else h.get("pct", 0)) / 100.0
    return v


def layer_checks(parties, owners_of):
    notes = []
    for owned, hs in owners_of.items():
        total = sum(float(h.get("pct", 0)) for h in hs)
        name = parties[owned]["name"]
        if total > 100 + EPS:
            notes.append(f"ERROR: holdings in {name} add up to {fmt(total)} (over 100%). Recheck the documents.")
        elif total < 100 - EPS:
            notes.append(f"Gap: only {fmt(total)} of {name} is accounted for. {fmt(100 - total)} untraced.")
    for pid, p in parties.items():
        if p.get("type") == "entity" and pid not in owners_of and any(
                h["owner"] == pid for hs in owners_of.values() for h in hs):
            notes.append(f"Untraced: no owners given for {p['name']}. Ownership not traced to natural persons.")
        if p.get("nominee"):
            behind = p.get("nominee_for")
            if behind and behind in parties:
                notes.append(f"Nominee: {p['name']} holds for {parties[behind]['name']}. Ownership attributed to the principal.")
            else:
                notes.append(f"Nominee: {p['name']} is a nominee with no principal named. Zero-nominee rule breach for offshore gaming; EDD trigger.")
        if p.get("bearer_shares"):
            notes.append(f"Bearer shares: {p['name']} has bearer shares. EDD trigger.")
    return notes


def ofac_50(subject, parties, owners_of):
    """Fixed-point OFAC 50% Rule. An entity is blocked if blocked persons own 50% or more of it
    in aggregate, directly or through other blocked entities."""
    blocked = {pid for pid, p in parties.items() if p.get("sanctioned")}
    working = []
    changed = True
    while changed:
        changed = False
        for owned, hs in owners_of.items():
            if owned in blocked:
                continue
            contrib = [h for h in hs if h["owner"] in blocked]
            total = sum(float(h["pct"]) for h in contrib)
            if total >= 50 - EPS:
                blocked.add(owned)
                changed = True
                parts = " + ".join(f"{parties[h['owner']]['name']} {float(h['pct']):g}%" for h in contrib)
                working.append(f"{parties[owned]['name']}: {parts} = {fmt(total)} owned by blocked persons, so BLOCKED.")
    # Report subject aggregate even if under 50
    subj_hs = owners_of.get(subject, [])
    subj_total = sum(float(h["pct"]) for h in subj_hs if h["owner"] in blocked)
    return blocked, working, subj_total


def resolve_nominees(parties, holdings):
    """Re-point holdings by a nominee to the named principal."""
    out = []
    for h in holdings:
        p = parties[h["owner"]]
        if p.get("nominee") and p.get("nominee_for") in parties:
            h = dict(h, owner=p["nominee_for"], via_nominee=p["name"])
        out.append(h)
    return out


def run(data):
    parties, _ = build(data)
    holdings = resolve_nominees(parties, data["holdings"])
    owners_of = {}
    for h in holdings:
        owners_of.setdefault(h["owned"], []).append(h)
    subject = data["subject"]
    threshold = data.get("threshold") or (10 if data.get("high_risk_jurisdiction") else 25)

    chains, warnings = paths_to(subject, parties, owners_of)
    totals, voting, working = {}, {}, {}
    for leaf, chain in chains:
        v = chain_value(chain, "pct")
        vv = chain_value(chain, "voting_pct")
        totals[leaf] = totals.get(leaf, 0) + v
        voting[leaf] = voting.get(leaf, 0) + vv
        steps = " x ".join(f"{float(h['pct']):g}%" for h in chain)
        route = " > ".join([parties[chain[0]["owner"]]["name"]] + [parties[h["owned"]]["name"] for h in chain])
        working.setdefault(leaf, []).append(f"{route}: {steps} = {fmt(v)}")

    direct = {h["owner"]: float(h["pct"]) for h in owners_of.get(subject, [])}
    rows = []
    for leaf in sorted(totals, key=lambda k: -totals[k]):
        p = parties[leaf]
        is_person = p.get("type") == "person"
        eff = max(totals[leaf], voting[leaf])
        ubo = is_person and eff >= threshold - EPS
        rows.append({
            "id": leaf, "name": p["name"], "type": p.get("type"),
            "direct_pct": round(direct.get(leaf, 0.0), 4),
            "indirect_pct": round(totals[leaf] - direct.get(leaf, 0.0), 4),
            "total_pct": round(totals[leaf], 4),
            "voting_pct": round(voting[leaf], 4),
            "ubo": ubo,
            "untraced_entity": not is_person,
            "working": working[leaf],
        })

    blocked, ofac_working, subj_blocked_pct = ofac_50(subject, parties, owners_of)
    return {
        "subject": parties[subject]["name"],
        "threshold": threshold,
        "rows": rows,
        "ubos": [r["name"] for r in rows if r["ubo"]],
        "layer_notes": layer_checks(parties, owners_of) + warnings,
        "ofac": {
            "sanctioned_inputs": [parties[b]["name"] for b in blocked if parties[b].get("sanctioned")],
            "blocked_entities": [parties[b]["name"] for b in blocked if not parties[b].get("sanctioned")],
            "subject_blocked": subject in blocked,
            "subject_aggregate_pct": round(subj_blocked_pct, 4),
            "working": ofac_working,
        },
    }


def to_markdown(r):
    out = [f"## Beneficial ownership: {r['subject']}",
           f"UBO threshold applied: {r['threshold']}% (25% standard, 10% offshore haven or FATF grey list).", ""]
    out.append("| Party | Type | Direct % | Indirect % | Total % | Voting % | UBO |")
    out.append("|---|---|---|---|---|---|---|")
    for row in r["rows"]:
        ubo = "Yes" if row["ubo"] else ("Not traced" if row["untraced_entity"] else "No")
        out.append(f"| {row['name']} | {row['type']} | {fmt(row['direct_pct'])} | {fmt(row['indirect_pct'])} | "
                   f"{fmt(row['total_pct'])} | {fmt(row['voting_pct'])} | {ubo} |")
    out += ["", "### Working"]
    for row in r["rows"]:
        out.append(f"- **{row['name']}**")
        for w in row["working"]:
            out.append(f"  - {w}")
        if len(row["working"]) > 1:
            out.append(f"  - Sum of paths = {fmt(row['total_pct'])}")
    if not r["ubos"]:
        out += ["", f"No natural person meets {r['threshold']}%. KYC the senior managing officials and name one person with significant control."]
    if r["layer_notes"]:
        out += ["", "### Structure notes"] + [f"- {n}" for n in r["layer_notes"]]
    o = r["ofac"]
    out += ["", "### OFAC 50% Rule"]
    if not o["sanctioned_inputs"]:
        out.append("No party is marked sanctioned in the input. 50% Rule not engaged on current evidence.")
    else:
        out.append("Sanctioned persons in the structure: " + ", ".join(o["sanctioned_inputs"]) + ".")
        out += [f"- {w}" for w in o["working"]] or ["- No entity reaches 50% aggregate blocked ownership."]
        verdict = "BLOCKED: Reject, stop, escalate to MLRO immediately, no tip-off." if o["subject_blocked"] else \
            f"Not blocked under the 50% Rule ({fmt(o['subject_aggregate_pct'])} aggregate). Still a sanctions exposure: escalate."
        out.append(f"**Subject:** {verdict}")
    out.append("Note: OFAC aggregates at 50% or more. EU and UK tests use more than 50% plus control; assess separately.")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case")
    ap.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    a = ap.parse_args()
    result = run(load(a.case))
    print(json.dumps(result, indent=2) if a.json else to_markdown(result))


if __name__ == "__main__":
    sys.exit(main())
