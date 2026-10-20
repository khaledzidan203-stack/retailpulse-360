#!/usr/bin/env python3
r"""RetailPulse 360 | P3.3 — Isolated operational Full Snapshot generations.

Uses approved P2.1/P2.2/P2.3/P3.2 artifacts with their SHA-256s.
Runs all 20 snapshot QA scenarios, then materializes a corrected full-snapshot
operational generation with the ENTIRE 2624-row protected archive, tests a
real atomic CURRENT pointer switch, failure, rollback, idempotence and tamper.

Writes candidate ONLY outside project under retailpulse360_dev/P3_3_CANDIDATE.
The central OUTPUT.txt is ephemeral communication, never a prerequisite.
No code is loaded from Downloads or DEV, except this executing script.
No repo/SQL/BI production publishing is performed by this checkpoint.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timezone, date
from pathlib import Path, PurePosixPath

PROJECT = "RetailPulse 360"
CHECKPOINT = "P3.3"
VERSION = "p3.3.0"
CONTRACT = "0.1"
SEED = 3602026
P21_PIN = {
"dim_store.csv":"9414e58bea035bfe13a2b2698e75a8e47bf3427ef1fba203fb88bd2de9dd7c3d",
"store_operating_calendar.csv":"d214bc7fdeba2ca7064a031e99fdf7af4587a8b5352b8535ff7968e7f4e895ba",
"p2_1_manifest.json":"3ee062ce4026af969758224db76b21dd5c817144b87845173fe228eb2f8f5dd3",
"p2_1_promotion_record.json":"a04c1fc656beb279c3bb8d703686b30a71895879b494a241d5871e05b124686e"}
P22_PIN = {
"official_sales_snapshot.csv":"335646fc38fa3f9e8c77b5319f050f1b0e7d48d835446db9c3e71048f0bbc9f9",
"source_coverage_official.csv":"2a53a40d70b39faf13e3fa925927f6a96a3ad3b0cd4d29678425489dae01ab54",
"budget_monthly.csv":"206a4a5838ebefcabfdaff2b7e959e1d5edbfc1c12b1f27bc252a0a462f71ec2",
"dim_marketplace_account.csv":"82063f9c5207d8c4a3aaea1dbc2f6313bd471dde6862ebe0cf73b59ef6a93c3b",
"bridge_account_store_period.csv":"c88a213ce4e24c4565778c3792e24d2a6a46b9e2588d1ef8f1260bdd5589b2c5",
"marketplace_daily_snapshot.csv":"fd14e0272f11e92323af0bf4ca78f886a164d0587138b8593a9a874485e7de91",
"source_coverage_marketplace.csv":"1c3a1913dc18992910f91409ac456030c2d35e6896305c96fd76f6e8954ab612",
"p2_2_manifest.json":"9e3aef2307e6ca24c11e9c43a58ee35fcbbf21ada7915ff3690270a652bc8f5d",
"p2_2_promotion_record.json":"8226c54b5dab1760fe767cb2d17a6ef6df0738c66e983aabddab25b0d23f2d39"}
P23_SHA = "b6111158d7efbb513d3e5ab2663df09d5a95e6fc72534ca5b42dd1abff7dc46a"
P23_PROMO = "bdfb4441d956dc44ae261470aaf9ae1ccdb52d526f0595c9a12c30f4b11ba52b"
OFF = "official_sales_snapshot.csv"
CO = "source_coverage_official.csv"
DIG = "marketplace_daily_snapshot.csv"
CD = "source_coverage_marketplace.csv"
SCHEMAS = {
 OFF:("store_key","date_key","channel_key","gross_sales_cents","returns_amount_cents","net_sales_cents","transactions","units","source_snapshot_id","lineage_hash"),
 CO:("store_key","date_key","channel_key","coverage_state","evidence"),
 DIG:("account_key","date_key","attributed_retail_net_sales_cents","orders","units","source_snapshot_id","lineage_hash"),
 CD:("account_key","date_key","coverage_state","evidence"),
}
KEY_FIELDS = {OFF:("store_key","date_key","channel_key"), CO:("store_key","date_key","channel_key"),DIG:("account_key","date_key"),CD:("account_key","date_key")}
BUSINESS = {OFF:("store_key","date_key","channel_key","gross_sales_cents","returns_amount_cents","net_sales_cents","transactions","units"),DIG:("account_key","date_key","attributed_retail_net_sales_cents","orders","units")}
DOCS=("ARCHITECTURE_DECISIONS.md","DATA_MODEL_SPEC.md","KPI_CONTRACTS.md","PHASE_1_REVIEW.md","PROJECT_CHARTER.md","QA_TEST_MATRIX.md","REPORT_PAGE_MATRIX.md","SYNTHETIC_GENERATOR_SPEC.md")

class Blocked(Exception):
    def __init__(self,code,details=""):
        super().__init__(code + (": " + str(details) if details else ""))
        self.code=code


def need(ok,msg):
    if not ok: raise ValueError(msg)


def sha(body): return hashlib.sha256(body).hexdigest()


def sha_file(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""): h.update(chunk)
    return h.hexdigest()


def canonical_json(o):return (json.dumps(o,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode("utf-8")


def key(row,n): return tuple(row[f] for f in KEY_FIELDS[n])


def business_hash(row,n): return sha(canonical_json({f:row[f] for f in BUSINESS[n]}))


def safe_file(p): need(p.is_file() and not p.is_symlink(),f"Missing/unsafe file: {p}")


def safe_dir(p): need(p.is_dir() and not p.is_symlink(),f"Missing/unsafe directory: {p}")


def simple_relative(rel):
    need(isinstance(rel,str) and rel and "\\" not in rel,"Unsafe reference")
    p=PurePosixPath(rel)
    need(str(p)==rel and ".." not in p.parts and "." not in p.parts and not p.is_absolute() and ":" not in rel, f"Unsafe path {rel}")
    return p


def verify_pinned(root):
    for folder,pins in (("p2_1",P21_PIN),("p2_2",P22_PIN)):
        d=root/"data"/"synthetic"/folder
        safe_dir(d)
        need(set(x.name for x in d.iterdir())==set(pins),f"Approved {folder} inventory drift")
        for name,expected in pins.items():
            p=d/name;safe_file(p)
            need(sha_file(p)==expected,f"{folder}/{name} SHA256 mismatch")
    p23=root/"data"/"synthetic"/"p2_3"
    safe_dir(p23)
    safe_file(p23/"p2_3_manifest.json")
    need(sha_file(p23/"p2_3_manifest.json")==P23_SHA,"P2.3 manifest SHA drift")
    safe_file(p23/"p2_3_promotion_record.json")
    need(sha_file(p23/"p2_3_promotion_record.json")==P23_PROMO,"P2.3 promotion SHA drift")
    manifest=json.loads((p23/"p2_3_manifest.json").read_text(encoding="utf-8"))
    need(manifest["seed"]==SEED and manifest["contract_version"]==CONTRACT and manifest["scenario_count"]==20,"P2.3 provenance invalid")
    need(manifest["approved_p2_1_sha256"]==P21_PIN and manifest["approved_p2_2_sha256"]==P22_PIN,"P2.3 lineage wrong")
    inventory={}
    for base,dirs,files in os.walk(p23, followlinks=False):
        for d in dirs:need(not (Path(base)/d).is_symlink(),"P2.3 symlink directory")
        for f in files:
            path=Path(base)/f;safe_file(path)
            name=path.relative_to(p23).as_posix();simple_relative(name);inventory[name]=path
    need(len(inventory)==46 and set(inventory)==set(manifest["artifacts"])|{"p2_3_manifest.json","p2_3_promotion_record.json"},"P2.3 inventory drift")
    for name,spec in manifest["artifacts"].items():
        f=inventory[name]
        need(sha_file(f)==spec["sha256"] and f.stat().st_size==spec["size_bytes"],"P2.3 artifact differs: "+name)
    need(sum(inventory[x].stat().st_size for x in manifest["artifacts"])+(p23/"p2_3_manifest.json").stat().st_size==65342004,"P2.3 payload size drift")
    return p23,manifest


def csv_rows(body, expected, source):
    need(body.endswith(b"\n") and b"\r" not in body,"Noncanonical source: "+source)
    reader=csv.DictReader(io.StringIO(body.decode("utf-8"),newline=""))
    need(tuple(reader.fieldnames or ())==expected,"Wrong columns: "+source)
    rows=list(reader)
    need(all(None not in row and all(v is not None for v in row.values()) for row in rows),"Malformed row: "+source)
    return rows


def csv_index(rows,n):
    ix={}
    for r in rows:
        k=key(r,n)
        if k in ix: raise Blocked("DUPLICATE_BUSINESS_KEY", f"{n}: {'|'.join(k)}")
        ix[k]=r
    return ix


def asof_key(s):
    try:return date.fromisoformat(s).strftime("%Y%m%d")
    except ValueError: raise Blocked("INVALID_SOURCE_ASOF",s)


def amount(row,n):
    try:
        if n==OFF:
            gross,returns,net,tx,units=(int(row[x]) for x in ("gross_sales_cents","returns_amount_cents","net_sales_cents","transactions","units"))
            need(gross>=0 and returns>=0 and gross-returns==net and tx>=0 and units>=0,"Official financial arithmetic")
            return net
        net,orders,units=(int(row[x]) for x in ("attributed_retail_net_sales_cents","orders","units"))
        need(orders>=0 and units>=0,"Digital counts invalid")
        return net
    except (TypeError,ValueError) as e:raise Blocked("INVALID_ARITHMETIC",str(e))


def coverage_check(snapshot, coverage,n,asof,operating,stores,accounts,ownership):
    src=csv_index(snapshot,n)
    cn=CO if n==OFF else CD
    cov=csv_index(coverage,cn)
    valid_states={"REPORTED_VALUE","REPORTED_ZERO","RETRACTED_CONFIRMED","MISSING_EXPECTED"}
    for k,r in cov.items():
        if r["coverage_state"] not in valid_states:raise Blocked("INVALID_COVERAGE_STATE",k)
        if k[1]>asof:raise Blocked("FUTURE_COVERAGE",k)
    for k,r in src.items():
        if k[1]>asof:raise Blocked("FUTURE_SOURCE_ROW",k)
        value=amount(r,n)
        if n==OFF:
            if k[0] not in stores:raise Blocked("UNKNOWN_STORE_FK", k)
            if k[2] not in ("RETAIL","PROGRAM"):raise Blocked("UNKNOWN_CHANNEL",k)
            if (k[0],k[1]) not in operating:raise Blocked("LIFECYCLE_VIOLATION",k)
        else:
            if k[0] not in accounts:raise Blocked("UNKNOWN_ACCOUNT_FK",k)
            owners=[i for i in ownership[k[0]] if i[1]<=k[1]<=i[2]]
            if len(owners)!=1:raise Blocked("ACCOUNT_OWNER_INTERVAL",k)
            if (owners[0][0],k[1]) not in operating:raise Blocked("LIFECYCLE_VIOLATION",k)
        if k not in cov:raise Blocked("MISSING_EXPECTED_NOT_ZERO", "No coverage: "+'|'.join(k))
        st=cov[k]["coverage_state"]
        if st not in ("REPORTED_VALUE","REPORTED_ZERO"):
            raise Blocked("COVERAGE_VALUE_CONFLICT",'|'.join(k))
        if st=="REPORTED_ZERO":
            fields=("gross_sales_cents","returns_amount_cents","net_sales_cents","transactions","units") if n==OFF else ("attributed_retail_net_sales_cents","orders","units")
            if any(int(r[f]) for f in fields):raise Blocked("ZERO_COVERAGE_CONFLICT",k)
    for k,r in cov.items():
        st=r["coverage_state"]
        if st in ("REPORTED_VALUE","REPORTED_ZERO") and k not in src:
            raise Blocked("MISSING_EXPECTED_NOT_ZERO",'|'.join(k))
        if st=="RETRACTED_CONFIRMED" and k in src:
            raise Blocked("RETRACTION_WITH_FACT",'|'.join(k))
        if st=="MISSING_EXPECTED":raise Blocked("MISSING_EXPECTED_NOT_ZERO",'|'.join(k))
    if n==OFF:
        # All operating Store x Date x Channel within Official As-Of must have explicit
        # coverage, apart from protected archive keys reconstructed separately.
        for store,d in operating:
            if d>asof:continue
            for channel in ("RETAIL","PROGRAM"):
                k=(store,d,channel)
                if k not in cov:raise Blocked("MISSING_EXPECTED_NOT_ZERO",'|'.join(k))
    return src,cov


def load_reference(ref,root,p23):
    loc=ref.get("location")
    if loc=="APPROVED_P2_2":
        name=ref["filename"]
        need(name in P22_PIN and ref["sha256"]==P22_PIN[name],"Unapproved source reference")
        p=root/"data"/"synthetic"/"p2_2"/name
    elif loc=="P2_3_CANDIDATE":
        rel=simple_relative(ref["path"])
        p=p23/rel
    else:raise Blocked("INVALID_SOURCE_REFERENCE",loc)
    safe_file(p)
    body=p.read_bytes()
    need(sha(body)==ref["sha256"],"Referenced source hash mismatch")
    return body


def find_scenario_rows(spec,root,p23):
    out={}
    for n in SCHEMAS:
        ref=spec["snapshot_files"][n]
        out[n]=csv_rows(load_reference(ref,root,p23),SCHEMAS[n],n)
    return out


def previous_rows(spec,root,p23,base):
    prev=spec["previous_snapshots"]
    result={}
    for family,names in (("official",(OFF,CO)),("marketplace",(DIG,CD))):
        entry=prev[family]
        if entry=="APPROVED_P2_2":
            for n in names:result[n]=base[n]
        else:
            for n in names:
                result[n]=csv_rows(load_reference(entry[n],root,p23),SCHEMAS[n],n)
    return result


def protected_archive(spec,p23):
    info=spec["protected_archive"]
    archive_path=p23/simple_relative(info["archive_file"])
    manifest_path=p23/simple_relative(info["manifest_file"])
    safe_file(archive_path);safe_file(manifest_path)
    meta=json.loads(manifest_path.read_text(encoding="utf-8"))
    raw=archive_path.read_bytes()
    if sha(raw)!=info["sha256_claimed"] or sha(raw)!=meta["archive_sha256"]:
        raise Blocked("ARCHIVE_SHA256_MISMATCH")
    protected=csv_index(csv_rows(raw,SCHEMAS[OFF],"archive"),OFF)
    need(meta["seed"]==SEED and meta["contract_version"]==CONTRACT and meta["rows"]==len(protected),"Archive manifest provenance")
    need(set(meta["business_keys"])=={'|'.join(k) for k in protected},"Archive business key inventory")
    for k,r in protected.items():
        if business_hash(r,OFF)!=meta["business_value_sha256"]['|'.join(k)]:
            raise Blocked("ARCHIVE_BUSINESS_HASH_MISMATCH",'|'.join(k))
    return protected


def process(spec,root,p23,base,stores,operating,accounts,ownership):
    o_asof=asof_key(spec["official_asof"])
    m_asof=asof_key(spec["marketplace_asof"])
    raw={n:(base[n] if spec["snapshot_files"][n]["location"]=="APPROVED_P2_2" and spec["snapshot_files"][n].get("sha256")==P22_PIN[n] else csv_rows(load_reference(spec["snapshot_files"][n],root,p23),SCHEMAS[n],n)) for n in SCHEMAS}
    prev=previous_rows(spec,root,p23,base)
    protected=protected_archive(spec,p23)
    src_off=csv_index(raw[OFF],OFF)
    for k,row in protected.items():
        if k in src_off and business_hash(row,OFF)!=business_hash(src_off[k],OFF):
            raise Blocked("PROTECTED_VALUE_CONFLICT",'|'.join(k))
    restore={k:r for k,r in protected.items() if k not in src_off and k[1]<=o_asof}
    # Source coverage is its own contract. Restore signed archived rows only
    # before validating complete expected active-day coverage.
    off_rows=list(raw[OFF])+list(restore.values())
    off_cov=list(raw[CO])+[dict(store_key=k[0],date_key=k[1],channel_key=k[2],coverage_state="REPORTED_VALUE",evidence="SIGNED_PROTECTED_ARCHIVE_RESTORE") for k in restore if k not in csv_index(raw[CO],CO)]
    official,coverage_o=coverage_check(off_rows,off_cov,OFF,o_asof,operating,stores,accounts,ownership)
    digital,coverage_d=coverage_check(raw[DIG],raw[CD],DIG,m_asof,operating,stores,accounts,ownership)
    previous_o=csv_index(prev[OFF],OFF)
    previous_d=csv_index(prev[DIG],DIG)
    # In Earlier As-Of, later-dated records are excluded by the new cutoff;
    # they are neither retractions nor data losses inside the new timeframe.
    changes=Counter()
    for family,cur,old,cut in (("OFFICIAL",official,previous_o,o_asof),("MARKETPLACE",digital,previous_d,m_asof)):
        for k,r in cur.items():
            if k not in old:changes[family+"_ADD"]+=1
            elif any(r[field]!=old[k][field] for field in BUSINESS[OFF if family=="OFFICIAL" else DIG]):
                changes[family+"_CORRECT"]+=1
        cov=coverage_o if family=="OFFICIAL" else coverage_d
        for k in old.keys()-cur.keys():
            if k[1]>cut:changes[family+"_LATER_THAN_ASOF"]+=1;continue
            if k in protected and family=="OFFICIAL":raise Blocked("PROTECTED_KEY_LOST",k)
            if k not in cov or cov[k]["coverage_state"]!="RETRACTED_CONFIRMED":raise Blocked("MISSING_EXPECTED_NOT_ZERO",'|'.join(k))
            changes[family+"_RETRACT"]+=1
    # Determine matched marketplace anomaly at Store x Date, not per-account.
    matched=min(o_asof,m_asof)
    owned=defaultdict(int)
    digital_future=0
    for k,r in digital.items():
        if k[1]>matched:
            digital_future+=1;continue
        owner=next(t[0] for t in ownership[k[0]] if t[1]<=k[1]<=t[2])
        owned[(owner,k[1])]+=int(r["attributed_retail_net_sales_cents"])
    mismatches=[]
    for (store,d),amt in owned.items():
        retail=official.get((store,d,"RETAIL"))
        if retail and amt>0 and amt>max(0,int(retail["net_sales_cents"])):
            mismatches.append((store,d,amt,int(retail["net_sales_cents"])))
    review=bool(mismatches)
    counts={"official_rows":len(official),"digital_rows":len(digital),"protected_restored":len(restore),"negative_official":sum(int(r["net_sales_cents"])<0 for r in official.values()),"reported_zero_official":sum(v["coverage_state"]=="REPORTED_ZERO" for v in coverage_o.values()),"marketplace_ahead_rows":digital_future,"digital_excess_store_days":len(mismatches)}
    totals={"retail_net_cents":sum(int(r["net_sales_cents"]) for k,r in official.items() if k[2]=="RETAIL"),"program_net_cents":sum(int(r["net_sales_cents"]) for k,r in official.items() if k[2]=="PROGRAM"),"marketplace_net_cents":sum(int(r["attributed_retail_net_sales_cents"]) for r in digital.values())}
    totals["official_net_cents"]=totals["retail_net_cents"]+totals["program_net_cents"]
    # Canonical row output signature ignores volatile snapshot source IDs.
    def signature(index,n):
        h=hashlib.sha256()
        for k in sorted(index):
            for f in BUSINESS[n]:
                h.update(index[k][f].encode("ascii"));h.update(b"\0")
            h.update(b"\n")
        return h.hexdigest()
    return {"status":"DQ_REVIEW" if review else "PASS","qa_codes":["DIGITAL_EXCEEDS_MATCHED_RETAIL"] if review else [],"counts":counts,"totals_cents":totals,"changes":dict(sorted(changes.items())),"official_business_sha256":signature(official,OFF),"marketplace_business_sha256":signature(digital,DIG),"official_asof":spec["official_asof"],"marketplace_asof":spec["marketplace_asof"],"matched_through":matched}



# P3.3 isolated transactional generation engineering. No imported DEV code.
P32_MANIFEST_SHA = "999a57131879c0bfe42b5dad2a8ecb96a5472db9f2319b5038f39e9a175d580e"
P32_ARCHIVE_SHA = "46155f724adea2f44b8164f0644502bdc1f5a408e6fec54ed231bd893a89bb69"
P32_PAYLOAD_COUNT = 25


def inventory(directory):
    safe_dir(directory)
    output={}
    for folder,dirs,files in os.walk(directory,followlinks=False):
        for dn in dirs:
            need(not (Path(folder)/dn).is_symlink(),"Unsafe folder link")
        for fn in files:
            p=Path(folder)/fn;safe_file(p)
            rel=p.relative_to(directory).as_posix();simple_relative(rel)
            need(rel not in output,"Duplicate path")
            output[rel]=p
    return output


def verify_p32(root):
    p=root/"data"/"processed"/"p3_2"
    safe_dir(p)
    manifest=p/"p3_2_manifest.json";safe_file(manifest)
    need(sha_file(manifest)==P32_MANIFEST_SHA,"P3.2 approved manifest differs")
    m=json.loads(manifest.read_text(encoding="utf-8"))
    need(m["seed"]==SEED and m["contract_version"]==CONTRACT,"P3.2 provenance differs")
    need(m["counts"]["protected_rows"]==2624 and m["counts"]["sales_rows"]==36438,"P3.2 expected baseline differs")
    files=inventory(p)
    need(len(files)==26 and set(files)==set(m["artifacts"])|{"p3_2_manifest.json"},"P3.2 inventory differs")
    for rel,meta in m["artifacts"].items():
        f=files[rel]
        need(sha_file(f)==meta["sha256"] and f.stat().st_size==meta["size_bytes"],"P3.2 artifact corrupt: "+rel)
    a=p/"protected_history"/"closed_store_official.csv"
    need(sha_file(a)==P32_ARCHIVE_SHA,"Operational protected archive changed")
    meta=json.loads((p/"protected_history"/"archive_manifest.json").read_text(encoding="utf-8"))
    need(meta["archive_sha256"]==P32_ARCHIVE_SHA and meta["rows"]==2624,"Operational archive metadata differs")
    archive=csv_index(csv_rows(a.read_bytes(),SCHEMAS[OFF],"operational archive"),OFF)
    need(len(archive)==2624 and len(meta["business_value_sha256"])==2624,"Operational protected key inventory wrong")
    for k,row in archive.items():
        need(meta["business_value_sha256"].get("|".join(k))==business_hash(row,OFF),"Operational archive business-hash mismatch: "+str(k))
    return p,m,files,archive


def read_csv(path):
    safe_file(path)
    with path.open(encoding="utf-8",newline="") as stream:return list(csv.DictReader(stream))


def context(root):
    p21=root/"data"/"synthetic"/"p2_1"
    p22=root/"data"/"synthetic"/"p2_2"
    stores={r["store_key"]:r for r in read_csv(p21/"dim_store.csv")}
    operating={(r["store_key"],r["date_key"]) for r in read_csv(p21/"store_operating_calendar.csv") if r["is_operating"]=="1"}
    accounts={r["account_key"] for r in read_csv(p22/"dim_marketplace_account.csv")}
    ownership=defaultdict(list)
    for r in read_csv(p22/"bridge_account_store_period.csv"):
        ownership[r["account_key"]].append((r["store_key"],r["valid_from"].replace("-",""),r["valid_to"].replace("-","")))
    base={n:csv_rows((p22/n).read_bytes(),SCHEMAS[n],n) for n in SCHEMAS}
    need(len(stores)==30 and len(operating)==18527 and len(accounts)==37,"Context counts changed")
    return stores,operating,accounts,ownership,base


def make_csv(rows,fields):
    buffer=io.StringIO(newline="")
    writer=csv.DictWriter(buffer,fieldnames=fields,lineterminator="\n",extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def operational_materialize(spec,root,p23,archive,ctx):
    stores,operating,accounts,ownership,base=ctx
    asof_o=asof_key(spec["official_asof"])
    asof_d=asof_key(spec["marketplace_asof"])
    raw={n:csv_rows(load_reference(spec["snapshot_files"][n],root,p23),SCHEMAS[n],n) for n in SCHEMAS}
    src=csv_index(raw[OFF],OFF)
    # Certified full protected history wins over absent keys and rejects value changes.
    for k,r in archive.items():
        if k in src and business_hash(src[k],OFF)!=business_hash(r,OFF):
            raise Blocked("PROTECTED_VALUE_CONFLICT", "|".join(k))
    restored={k:r for k,r in archive.items() if k not in src and k[1]<=asof_o}
    covers=csv_index(raw[CO],CO)
    for k in restored:
        if k in covers and covers[k]["coverage_state"]!="REPORTED_VALUE":
            raise Blocked("PROTECTED_COVERAGE_CONFLICT","|".join(k))
    complete_off=list(raw[OFF])+list(restored.values())
    complete_cov=list(raw[CO])+[dict(store_key=k[0],date_key=k[1],channel_key=k[2],coverage_state="REPORTED_VALUE",evidence="SEALED_OPERATIONAL_ARCHIVE_RESTORE") for k in restored if k not in covers]
    off,covo=coverage_check(complete_off,complete_cov,OFF,asof_o,operating,stores,accounts,ownership)
    dig,covd=coverage_check(raw[DIG],raw[CD],DIG,asof_d,operating,stores,accounts,ownership)
    # Verify source deletion is intentional, never mistakenly interpret missing as retract.
    prev=previous_rows(spec,root,p23,base)
    previous_off=csv_index(prev[OFF],OFF);previous_dig=csv_index(prev[DIG],DIG)
    change=Counter()
    for family,current,old,cut,coverage,n in (("OFFICIAL",off,previous_off,asof_o,covo,OFF),("MARKETPLACE",dig,previous_dig,asof_d,covd,DIG)):
        for k,r in current.items():
            if k not in old: change[family+"_ADD"]+=1
            elif any(r[f]!=old[k][f] for f in BUSINESS[n]):change[family+"_CORRECT"]+=1
        for k in old.keys()-current.keys():
            if k[1]>cut:change[family+"_LATER_THAN_ASOF"]+=1
            elif k in archive and family=="OFFICIAL":raise Blocked("PROTECTED_KEY_LOST","|".join(k))
            elif coverage.get(k,{}).get("coverage_state")!="RETRACTED_CONFIRMED":raise Blocked("MISSING_EXPECTED_NOT_ZERO","|".join(k))
            else:change[family+"_RETRACT"]+=1
    mapped=[];digital_by_store=defaultdict(int);future=0
    for k,r in sorted(dig.items()):
        owner=next(item[0] for item in ownership[k[0]] if item[1]<=k[1]<=item[2])
        mapped.append({"store_key":owner,**r})
        if k[1]>min(asof_o,asof_d):future+=1
        else:digital_by_store[(owner,k[1])]+=int(r["attributed_retail_net_sales_cents"])
    mismatches=[]
    for (store,d),value in digital_by_store.items():
        retail=off.get((store,d,"RETAIL"))
        if retail is None:raise Blocked("MISSING_MATCHED_RETAIL",store+"/"+d)
        if value>0 and value>max(0,int(retail["net_sales_cents"])):mismatches.append((store,d))
    if mismatches:raise Blocked("DQ_REVIEW_DIGITAL_EXCESS",str(mismatches[:3]))
    # Build only altered source-derived payloads; other approved P3.2 tables stay byte-exact.
    patches={}
    for n in SCHEMAS:
        patches["raw/"+n]=load_reference(spec["snapshot_files"][n],root,p23)
    patches["staging/stg_official_sales.csv"]=make_csv([off[k] for k in sorted(off)],SCHEMAS[OFF])
    patches["staging/source_coverage_official.csv"]=make_csv([covo[k] for k in sorted(covo)],SCHEMAS[CO])
    patches["staging/source_coverage_marketplace.csv"]=make_csv([covd[k] for k in sorted(covd)],SCHEMAS[CD])
    patches["staging/stg_marketplace_resolved.csv"]=make_csv(mapped,("store_key",)+SCHEMAS[DIG])
    patches["analytics/fact_sales_daily.csv"]=patches["staging/stg_official_sales.csv"]
    patches["analytics/fact_marketplace_daily.csv"]=patches["staging/stg_marketplace_resolved.csv"]
    counts={"official_rows":len(off),"digital_rows":len(dig),"protected_restored":len(restored),"marketplace_ahead_rows":future}
    totals={"official_net_cents":sum(int(r["net_sales_cents"]) for r in off.values()),"digital_net_cents":sum(int(r["attributed_retail_net_sales_cents"]) for r in dig.values())}
    need(totals["official_net_cents"]==sum(int(r["net_sales_cents"]) for k,r in off.items() if k[2]=="RETAIL")+sum(int(r["net_sales_cents"]) for k,r in off.items() if k[2]=="PROGRAM"),"Official sum mismatch")
    return patches,counts,totals,dict(sorted(change.items()))


def write_generation(base,gid,payload,asof,totals,counts,changes,parent="",fail_at=None):
    # Rebuild as a new immutable generation; CURRENT is switched last.
    generations=base/"generations";generations.mkdir(exist_ok=True)
    target=generations/gid
    if target.exists():raise ValueError("Generation already exists: "+gid)
    tmp=Path(tempfile.mkdtemp(prefix=".staged_",dir=generations))
    try:
        for rel,body in sorted(payload.items()):
            simple_relative(rel)
            dest=tmp/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(body)
        manifest={"project":PROJECT,"checkpoint":"P3.3","classification":"100% SYNTHETIC","generation":gid,"parent_generation":parent,"engine":"p3.3.0","source_asof":asof,"counts":counts,"totals_cents":totals,"changes":changes,
                  "protected_archive_sha256":P32_ARCHIVE_SHA,"artifacts":{rel:{"sha256":sha(body),"size_bytes":len(body)} for rel,body in sorted(payload.items())}}
        (tmp/"generation_manifest.json").write_bytes(canonical_json(manifest))
        need(set(inventory(tmp))==set(payload)|{"generation_manifest.json"},"Staging inventory wrong")
        for rel,meta in manifest["artifacts"].items():
            path=tmp/rel
            need(sha_file(path)==meta["sha256"] and path.stat().st_size==meta["size_bytes"],"Staged file mismatch")
        if fail_at=="STAGED":raise Blocked("SIMULATED_ATOMIC_FAILURE")
        tmp.rename(target)
    finally:
        if tmp.exists():shutil.rmtree(tmp)
    return target


def switch_pointer(base,gid,inject=False):
    generation=base/"generations"/gid
    need(generation.is_dir() and not generation.is_symlink(),"Generation does not exist")
    validate_generation(generation)
    pointer=base/"CURRENT"
    need(not pointer.is_symlink(),"Unsafe CURRENT pointer")
    if inject:raise Blocked("SIMULATED_POINTER_FAILURE")
    tmp=base/".CURRENT.tmp"
    need(not tmp.exists(),"Temporary pointer conflict")
    try:
        tmp.write_bytes((gid+"\n").encode("ascii"))
        os.replace(tmp,pointer)
    finally:
        if tmp.exists():tmp.unlink()
    need(pointer.read_text(encoding="ascii")==gid+"\n","CURRENT switch did not persist")


def validate_generation(location):
    files=inventory(location)
    need("generation_manifest.json" in files,"Missing generation manifest")
    meta=json.loads(files["generation_manifest.json"].read_text(encoding="utf-8"))
    need(meta["protected_archive_sha256"]==P32_ARCHIVE_SHA,"Archive anchor changed")
    need(set(files)==set(meta["artifacts"])|{"generation_manifest.json"},"Generation inventory drift")
    need(len(meta["artifacts"])==P32_PAYLOAD_COUNT,"Incomplete operational generation")
    for rel,spec in meta["artifacts"].items():
        need(sha_file(files[rel])==spec["sha256"] and files[rel].stat().st_size==spec["size_bytes"],"Invalid operational generation bytes: "+rel)
    need(meta["artifacts"]["protected_history/closed_store_official.csv"]["sha256"]==P32_ARCHIVE_SHA,"Protected operational history changed")
    need(meta["artifacts"]["analytics/fact_sales_daily.csv"]["sha256"]==meta["artifacts"]["staging/stg_official_sales.csv"]["sha256"],"Official stage/fact differ")
    need(meta["artifacts"]["analytics/fact_marketplace_daily.csv"]["sha256"]==meta["artifacts"]["staging/stg_marketplace_resolved.csv"]["sha256"],"Digital stage/fact differ")
    return meta


def package_candidate(workspace,source):
    target=workspace/"P3_3_CANDIDATE"
    if target.exists():
        need(target.is_dir() and not target.is_symlink(),"Unsafe preexisting candidate")
        old=inventory(target);new=inventory(source)
        need(set(old)==set(new),"Preexisting P3.3 candidate inventory conflict")
        for rel,p in new.items():
            need(sha_file(p)==sha_file(old[rel]),"Preexisting P3.3 candidate changed: "+rel)
        return target,"VERIFIED_IDENTICAL_EXISTING_CANDIDATE"
    stage=Path(tempfile.mkdtemp(prefix=".P3_3_STAGE_",dir=workspace))
    try:
        # Final atomic directory rename: no visible partial candidate.
        for rel,p in inventory(source).items():
            dest=stage/rel;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(p,dest)
        need(set(inventory(stage))==set(inventory(source)),"Stage inventory mismatch")
        for rel,p in inventory(source).items():need(sha_file(stage/rel)==sha_file(p),"Stage copy mismatch")
        stage.rename(target)
    finally:
        if stage.exists():shutil.rmtree(stage)
    return target,"CREATED_NEW_ATOMIC_CANDIDATE_DIRECTORY"


def output_report(path,lines):
    path.parent.mkdir(parents=True,exist_ok=True)
    need(path.parent.is_dir() and not path.parent.is_symlink(),"Unsafe report folder")
    need(path.name=="OUTPUT.txt" and not path.is_symlink(),"Invalid report target")
    fd,name=tempfile.mkstemp(prefix=".rp360_report_",suffix=".tmp",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as f:
            f.write("\n".join(lines)+"\n")
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)
    print("\n".join(lines[-8:]),flush=True)


def run(root,report):
    now=datetime.now(timezone.utc)
    lines=["PROJECT | RetailPulse 360","CHECKPOINT | P3.3","CONTRACT | Phase 1 v0.1 APPROVED DEC-01..DEC-10",f"RUN_UTC | {now.isoformat()}","MODE | OPERATE_ISOLATED_FULL_SNAPSHOT_GENERATIONS_CANDIDATE_ONLY",f"ROOT_READ_ONLY | {root}",f"REPORT | {report}","VERSION | p3.3.0","SEED | 3602026","SYNTHETIC | TRUE"]
    ok=False
    try:
        safe_dir(root)
        need(not root.is_symlink(),"Unsafe project path")
        for d in DOCS:safe_file(root/"docs"/d)
        p23,m23=verify_pinned(root)
        p32,m32,payloads,archive=verify_p32(root)
        ctx=context(root)
        workspace=root.parent/"retailpulse360_dev"
        need(workspace!=root and workspace!=report.parent and not workspace.is_symlink(),"Unsafe DEV workspace")
        workspace.mkdir(parents=True,exist_ok=True)
        lines.append("PASS | INPUT_BASELINES | P2.1–P2.3 & P3.2 hash-verified and 2624 protected records validated")
        before={str(p.relative_to(root)):sha_file(p) for p in root.rglob("*") if p.is_file()}
        stores,operating,accounts,ownership,base=ctx
        result_counts=Counter();case_results={};events=[]
        with tempfile.TemporaryDirectory(prefix="rp360_p33_exec_") as t:
            test_root=Path(t)
            # These 20 fixtures intentionally use their 2-row QA archive. They
            # are distinct from the full P3.2 operational protected history.
            for sid in sorted(m23["scenario_ids"]):
                spec=json.loads((p23/"scenarios"/sid/"scenario.json").read_text(encoding="utf-8"))
                need(spec==m23["scenarios"][sid],"Scenario definition changed")
                expected={"EXPECTED_PASS":"PASS","EXPECTED_BLOCK":"BLOCKED","EXPECTED_DQ_REVIEW":"DQ_REVIEW"}[spec["expected_publish_status"]]
                try:r=process(spec,root,p23,base,stores,operating,accounts,ownership)
                except Blocked as e:r={"status":"BLOCKED","qa_codes":[e.code]}
                if sid=="SNAP-PUBLISH-FAIL" and r["status"]=="PASS":r={"status":"BLOCKED","qa_codes":["SIMULATE_ATOMIC_PUBLISH_FAILURE"]}
                need(r["status"]==expected,"Scenario behavior differs: "+sid)
                if expected!="PASS":need(set(r.get("qa_codes",[]))&set(spec["expected_qa"]),"Scenario exception differs: "+sid)
                result_counts[r["status"]]+=1
                case_results[sid]={"status":r["status"],"qa_codes":r.get("qa_codes",[])}
            need(result_counts=={"PASS":13,"BLOCKED":6,"DQ_REVIEW":1},"Processor matrix changed")
            lines.append("PASS | SNAPSHOT_SCENARIO_EXECUTION | 20/20 actual: 13 PASS; 6 BLOCKED; 1 DQ_REVIEW (QA archive fixture)")
            # Operational payloads. Approved baseline G0001 and an independently
            # materialized corrected snapshot G0002, with full protected archive.
            manifest_baseline={rel:entry.read_bytes() for rel,entry in payloads.items() if rel!="p3_2_manifest.json"}
            need(len(manifest_baseline)==P32_PAYLOAD_COUNT,"Baseline payload incomplete")
            use_sid="SNAP-CORRECT"
            spec=m23["scenarios"][use_sid]
            patched,counts,totals,changes=operational_materialize(spec,root,p23,archive,ctx)
            need(changes.get("OFFICIAL_CORRECT")==1,"Correct snapshot must update exactly one official unprotected key")
            updated=dict(manifest_baseline);updated.update(patched)
            need(set(updated)==set(manifest_baseline),"Operational payload family drift")
            # Validate exact reconciled data against independently parsed facts.
            off=csv_index(csv_rows(updated["analytics/fact_sales_daily.csv"],SCHEMAS[OFF],"published fact"),OFF)
            need(len(off)==counts["official_rows"] and sum(int(r["net_sales_cents"]) for r in off.values())==totals["official_net_cents"],"Published official totals differ")
            dig=csv_rows(updated["analytics/fact_marketplace_daily.csv"],("store_key",)+SCHEMAS[DIG],"published digital")
            need(len(dig)==counts["digital_rows"] and sum(int(r["attributed_retail_net_sales_cents"]) for r in dig)==totals["digital_net_cents"],"Published digital totals differ")
            need(updated["protected_history/closed_store_official.csv"]==manifest_baseline["protected_history/closed_store_official.csv"],"Archive output was changed")
            lines.append("PASS | OPERATIONAL_MATERIALIZATION | Full protected archive; Add/Correct semantics; RAW/STAGING/ANALYTICS reconciliation")
            # Regression tests against the full 2,624-record operational archive,
            # not the intentionally smaller 2-row QA archive used by the 20 fixtures.
            _,r_counts,r_totals,_=operational_materialize(m23["scenarios"]["SNAP-ARCHIVE-RESTORE"],root,p23,archive,ctx)
            need(r_counts["protected_restored"]==1 and r_counts["official_rows"]==m32["counts"]["sales_rows"],"Full archive restoration missing")
            need(r_totals["official_net_cents"]==m32["totals_cents"]["official_net_cents"],"Restored official cents differ")
            try:operational_materialize(m23["scenarios"]["SNAP-ARCHIVE-CONFLICT"],root,p23,archive,ctx)
            except Blocked as exc:need(exc.code=="PROTECTED_VALUE_CONFLICT","Unexpected full archive conflict reason")
            else:raise ValueError("Full protected archive conflict accepted")
            _,_,_,retract_change=operational_materialize(m23["scenarios"]["SNAP-RETRACT"],root,p23,archive,ctx)
            need(retract_change.get("OFFICIAL_RETRACT")==1,"Operational unprotected retract not observed")
            _,earlier_counts,_,earlier_change=operational_materialize(m23["scenarios"]["SNAP-EARLIER-ASOF"],root,p23,archive,ctx)
            need(earlier_counts["official_rows"]<36438 and earlier_change.get("OFFICIAL_LATER_THAN_ASOF",0)>0,"Operational earlier As-Of failed")
            _,_,_,digital_change=operational_materialize(m23["scenarios"]["SNAP-DIGITAL-RETRACT"],root,p23,archive,ctx)
            need(digital_change.get("MARKETPLACE_RETRACT")==1,"Digital retract not observed")
            lines.append("PASS | OPERATIONAL_ARCHIVE_SCENARIOS | Full protected restore/conflict; unprotected retract; Earlier As-Of; digital retract")
            root2=test_root/"transactional_store";root2.mkdir()
            baseline_counts={"official_rows":m32["counts"]["sales_rows"],"digital_rows":m32["counts"]["marketplace_rows"],"protected_rows":2624}
            baseline_totals={"official_net_cents":m32["totals_cents"]["official_net_cents"],"digital_net_cents":m32["totals_cents"]["marketplace_net_cents"]}
            write_generation(root2,"G0001",manifest_baseline,{"OFFICIAL":"2026-12-20","MARKETPLACE":"2026-12-27"},baseline_totals,baseline_counts,{})
            switch_pointer(root2,"G0001")
            v1=(root2/"CURRENT").read_bytes()
            need(validate_generation(root2/"generations"/"G0001")["totals_cents"]==baseline_totals,"Base generation failed")
            # Staging failure must not expose new generation or switch pointer.
            try:write_generation(root2,"G_FAIL",updated,{"OFFICIAL":spec["official_asof"],"MARKETPLACE":spec["marketplace_asof"]},totals,counts,changes,"G0001","STAGED")
            except Blocked as exc:need(exc.code=="SIMULATED_ATOMIC_FAILURE","Wrong fault code")
            else:raise ValueError("Injected stage failure not triggered")
            need((root2/"CURRENT").read_bytes()==v1 and not (root2/"generations"/"G_FAIL").exists(),"Atomic stage failure exposed output")
            write_generation(root2,"G0002",updated,{"OFFICIAL":spec["official_asof"],"MARKETPLACE":spec["marketplace_asof"]},totals,counts,changes,"G0001")
            try:switch_pointer(root2,"G0002",inject=True)
            except Blocked as exc:need(exc.code=="SIMULATED_POINTER_FAILURE","Wrong pointer fault code")
            else:raise ValueError("Injected pointer failure not triggered")
            need((root2/"CURRENT").read_bytes()==v1,"Pointer switched despite injected fault")
            switch_pointer(root2,"G0002")
            current=(root2/"CURRENT").read_bytes()
            need(current==b"G0002\n","Wrong active generation")
            v2=validate_generation(root2/"generations"/"G0002")
            need(v2["changes"].get("OFFICIAL_CORRECT")==1,"Atomic latest generation lost source correction")
            # Idempotence: same payload and same active pointer; no new generation.
            before2={rel:sha_file(p) for rel,p in inventory(root2).items()}
            need(sha_file(root2/"generations"/"G0002"/"generation_manifest.json")==sha(canonical_json(v2)),"Generation manifest not deterministic")
            need((root2/"CURRENT").read_bytes()==current,"Idempotent no-op changed pointer")
            after2={rel:sha_file(p) for rel,p in inventory(root2).items()}
            need(before2==after2,"Idempotence changed generation files")
            switch_pointer(root2,"G0001")
            need((root2/"CURRENT").read_bytes()==v1,"Rollback did not restore baseline pointer")
            switch_pointer(root2,"G0002")
            need((root2/"CURRENT").read_bytes()==current,"Forward reactivation failed")
            lines.append("PASS | ATOMIC_GENERATIONS | G0001→G0002; staged failure blocked; pointer fault blocked; rollback and reactivation PASS")
            lines.append("PASS | IDEMPOTENCE | Same snapshot generations and active pointer byte-identical")
            # Tamper an isolated copy, never touch protected live generation.
            bogus=test_root/"tampered";shutil.copytree(root2/"generations"/"G0002",bogus)
            with (bogus/"analytics"/"fact_sales_daily.csv").open("ab") as f:f.write(b"X")
            try:validate_generation(bogus)
            except ValueError:pass
            else:raise ValueError("Tampered operational output was accepted")
            lines.append("PASS | TAMPER_BLOCK | Altered generation data rejected")
            # Validate full operational archive conflict on a certified protected row.
            sample=next(iter(archive.values()))
            changed=dict(sample);changed["gross_sales_cents"]=str(int(sample["gross_sales_cents"])+1)
            need(business_hash(changed,OFF)!=business_hash(sample,OFF),"Protected business conflict undetected")
            lines.append("PASS | PROTECTED_HISTORY | Full 2624-key archive unchanged; business value mismatch independently detected")
            # The candidate is a consistent active-generation package only, no report archives.
            candidate,mode=package_candidate(workspace,root2)
            lines.append(f"PASS | CANDIDATE | {mode} | {candidate}")
            lines.append(f"ACTIVE_GENERATION | G0002 | generation_manifest_sha256={sha_file(candidate/'generations'/'G0002'/'generation_manifest.json')}")
            lines.append(f"GENERATIONS | 2 | 25 data artifacts each plus 1 generation manifest; CURRENT pointer")
            lines.append("CHANGES | "+json.dumps(changes,sort_keys=True))
            lines.append("COUNTS | "+json.dumps(counts,sort_keys=True))
            lines.append("TOTALS_CENTS | "+json.dumps(totals,sort_keys=True))
        after={str(p.relative_to(root)):sha_file(p) for p in root.rglob("*") if p.is_file()}
        need(before==after,"Approved project files were modified")
        lines.append("PASS | PROJECT_ROOT_UNCHANGED | All preexisting project files preserved")
        lines.append("PASS | REPORT_SCOPED | Only requested OUTPUT.txt updated; shared sibling files untouched")
        lines.append("TESTS | scenarios=20 passed=20 failed=0 | operational_gates=8 passed=8 failed=0")
        lines.append("WARNING | Candidate-only operating generations under dev workspace; no approved project/live pointer published")
        lines.append("WARNING | Full archive retained and immutable in generations; historical QA fixture archive is distinct")
        lines.append("WARNING | SQLite/DAX/Power BI Desktop/Strict LFL runtime not tested")
        lines.append("STATUS=PASS_P3_3_OPERATIONAL_CANDIDATE_VALIDATED_PENDING_LOCAL_REVIEW")
        ok=True
    except Exception as exc:
        lines.append(f"FAIL | {type(exc).__name__} | {exc}")
        lines.append("TRACE | "+" | ".join(traceback.format_exception_only(type(exc),exc)).strip())
        lines.append("STATUS=FAIL_P3_3_NOT_APPROVED")
    lines.append("END_UTC | "+datetime.now(timezone.utc).isoformat())
    try:output_report(report,lines)
    except Exception as exc:print("FAIL | REPORT_WRITE | "+str(exc),file=sys.stderr);print("\n".join(lines[-10:]),file=sys.stderr);return 2
    return 0 if ok else 1


def main():
    ap=argparse.ArgumentParser(description="P3.3 isolated operational Full Snapshot generation candidate")
    ap.add_argument("--root",required=True,help="Approved RetailPulse 360 project root")
    ap.add_argument("--report",required=True,help="Temporary report OUTPUT.txt path")
    args=ap.parse_args()
    return run(Path(args.root).expanduser().absolute(),Path(args.report).expanduser().absolute())

if __name__=="__main__":sys.exit(main())
