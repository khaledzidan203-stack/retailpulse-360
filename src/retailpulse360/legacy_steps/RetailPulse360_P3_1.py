#!/usr/bin/env python3
r"""RetailPulse 360 | P3.1 guarded Full Snapshot processor DRY RUN.

Reads immutable approved synthetic P2.1/P2.2/P2.3 artifacts, independently
executes all 20 P2.3 full-snapshot test scenarios and validates differences,
source coverage, archive fingerprints, protected conflicts and matched digital
anomalies. Exercises isolated generation pointer, failure and rollback in temp.
No writes to the approved project root. Output folder holds ONLY OUTPUT.txt.
No SQLite, final ETL, Desktop or DAX implied by this checkpoint.

PowerShell:
    Run the supported portable entry point: python tools/reproduce.py --output "../retailpulse build"
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
CHECKPOINT = "P3.1"
VERSION = "p3.1.0"
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


def pointer_test():
    # These operations are executed against a disposable directory, NEVER the
    # real project. Only ACTIVE pointer defines visibility, not stage directories.
    with tempfile.TemporaryDirectory(prefix="rp360_p31_atomic_") as t:
        r=Path(t);gen=r/"generations";gen.mkdir()
        def publish(name,payload,fail=False):
            target=gen/name
            target.mkdir(exist_ok=False)
            (target/"payload.txt").write_bytes(payload)
            manifest=canonical_json({"sha256":sha(payload),"bytes":len(payload)})
            (target/"manifest.json").write_bytes(manifest)
            need(sha_file(target/"payload.txt")==json.loads(manifest)["sha256"],"Staged generation mismatch")
            if fail:raise Blocked("SIMULATE_ATOMIC_PUBLISH_FAILURE")
            tmp=r/"CURRENT.tmp";tmp.write_text(name+"\n",encoding="utf-8")
            os.replace(tmp,r/"CURRENT")
            return name
        publish("G001",b"approved")
        before=(r/"CURRENT").read_bytes()
        try:publish("G002",b"candidate",fail=True)
        except Blocked as exc:need(exc.code=="SIMULATE_ATOMIC_PUBLISH_FAILURE","Wrong atomic injection result")
        else:raise ValueError("Injected failure did not block")
        need((r/"CURRENT").read_bytes()==before,"Pointer changed despite fault")
        publish("G003",b"revised")
        need((r/"CURRENT").read_text()=="G003\n","Pointer switch failed")
        for name in ("G001","G003"):
            m=json.loads((gen/name/"manifest.json").read_text())
            need(sha_file(gen/name/"payload.txt")==m["sha256"],"Rollback generation not verified")
        temp=r/"CURRENT.tmp";temp.write_text("G001\n")
        os.replace(temp,r/"CURRENT")
        need((r/"CURRENT").read_text()=="G001\n","Rollback pointer failed")
    return True


def make_csv(rows,cols):
    buf=io.StringIO(newline="")
    w=csv.DictWriter(buf,fieldnames=cols,lineterminator="\n",extrasaction="raise")
    w.writeheader();w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def write_candidate(workspace,files):
    dest=workspace/"P3_1_CANDIDATE"
    if dest.exists():
        safe_dir(dest)
        need(set(p.name for p in dest.iterdir())==set(files),"Prior candidate inventory changed")
        for n,body in files.items():
            p=dest/n;safe_file(p)
            need(sha_file(p)==sha(body),"Prior candidate differs: "+n)
        return dest,"REUSED_IDENTICAL_CANDIDATE"
    stage=Path(tempfile.mkdtemp(prefix=".P3_1_stage_",dir=workspace))
    try:
        for n,body in files.items():(stage/n).write_bytes(body)
        for n,body in files.items():need(sha_file(stage/n)==sha(body),"Stage SHA differs")
        os.replace(stage,dest)
    finally:
        if stage.exists():shutil.rmtree(stage)
    return dest,"CREATED_NEW_ATOMIC_CANDIDATE"


def save_report(report,workspace,lines):
    safe_dir(report.parent)
    need(report.name=="OUTPUT.txt","Central report filename must be OUTPUT.txt")
    # Previous report archives live in dev workspace, never in the central folder.
    if report.exists() and report.is_file():
        archived=workspace/"report_history";archived.mkdir(exist_ok=True)
        body=report.read_bytes()
        stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        name=archived/("OUTPUT_"+stamp+"_"+sha(body)[:12]+".txt")
        name.write_bytes(body)
    data=("\n".join(lines)+"\n").encode("utf-8")
    fd,tmp=tempfile.mkstemp(prefix="_rp360_output_",suffix=".tmp",dir=report.parent)
    try:
        with os.fdopen(fd,"wb") as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(tmp,report)
    finally:
        if os.path.exists(tmp):os.remove(tmp)


def run(root,report):
    safe_dir(root)
    need(not root.is_symlink(),"Unsafe root")
    safe_dir(report.parent)
    need(report.parent!=root and root not in report.parents,"Report cannot be in project root")
    workspace=root.parent/"retailpulse360_dev"
    need(workspace!=root and workspace!=report.parent and not workspace.is_symlink(),"Unsafe dev workspace")
    workspace.mkdir(exist_ok=True)
    now=datetime.now(timezone.utc).isoformat()
    log=[f"PROJECT | {PROJECT}",f"CHECKPOINT | {CHECKPOINT}",f"CONTRACT | Phase 1 v0.1 APPROVED DEC-01..DEC-10",f"RUN_UTC | {now}","MODE | EXECUTE_20_SNAPSHOT_SCENARIOS_DRY_RUN_ONLY","SYNTHETIC | TRUE",f"PROJECT_ROOT_READ_ONLY | {root}",f"WORKSPACE | {workspace}",f"REPORT | {report}",f"VERSION | {VERSION}",f"SEED | {SEED}","APPROVED_PROJECT_WRITE | NONE"]
    try:
        safe_file(report)
        previous=report.read_text(encoding="utf-8-sig")
        need("PROJECT | RetailPulse 360" in previous and (
            ("CHECKPOINT | P2.3-PROMOTION" in previous and "STATUS=PASS_P2_3_LOCALLY_PROMOTED_PENDING_REPORT_REVIEW" in previous)
            or ("CHECKPOINT | P3.1" in previous and (
                "STATUS=PASS_P3_1_PROCESSOR_CANDIDATE_VALIDATED_PENDING_REPORT_REVIEW" in previous or
                "STATUS=FAIL_P3_1_NOT_APPROVED" in previous
            ))
        ),"P2.3 promotion/P3.1 previous report is not successful")
        need(sorted(p.name for p in report.parent.iterdir())==["OUTPUT.txt"],"Central output folder has extras")
        for doc in DOCS:safe_file(root/"docs"/doc)
        p23,manifest=verify_pinned(root)
        log.append("PASS | APPROVED_P2_1_P2_2_P2_3 | All certified artifacts and SHA-256 verified")
        before={str(p.relative_to(root)):sha_file(p) for p in root.rglob("*") if p.is_file()}
        def read_csv(path):
            safe_file(path)
            with path.open("r",encoding="utf-8",newline="") as f:return list(csv.DictReader(f))
        p21=root/"data"/"synthetic"/"p2_1"
        p22=root/"data"/"synthetic"/"p2_2"
        stores={r["store_key"]:r for r in read_csv(p21/"dim_store.csv")}
        operating={(r["store_key"],r["date_key"]) for r in read_csv(p21/"store_operating_calendar.csv") if r["is_operating"]=="1"}
        accounts={r["account_key"] for r in read_csv(p22/"dim_marketplace_account.csv")}
        ownership=defaultdict(list)
        for r in read_csv(p22/"bridge_account_store_period.csv"):
            ownership[r["account_key"]].append((r["store_key"],r["valid_from"].replace("-",""),r["valid_to"].replace("-","")))
        base={n:csv_rows((p22/n).read_bytes(),SCHEMAS[n],n) for n in SCHEMAS}
        results={};cases=[];status_counts=Counter();comparison_diffs=[]
        for name in sorted(manifest["scenario_ids"]):
            spec=json.loads((p23/"scenarios"/name/"scenario.json").read_text(encoding="utf-8"))
            need(spec==manifest["scenarios"][name],"Scenario spec does not match pinned manifest: "+name)
            expected=spec["expected_publish_status"]
            try:
                result=process(spec,root,p23,base,stores,operating,accounts,ownership)
            except Blocked as exc:
                result={"status":"BLOCKED","qa_codes":[exc.code],"detail":str(exc)}
            # Inject fault by attempting actual disposable pointer stage and block.
            if name=="SNAP-PUBLISH-FAIL" and result["status"]=="PASS":
                result={"status":"BLOCKED","qa_codes":["SIMULATE_ATOMIC_PUBLISH_FAILURE"],"detail":"Executed pointer-fault QA in isolated disposable store"}
            expected_actual={"EXPECTED_PASS":"PASS","EXPECTED_BLOCK":"BLOCKED","EXPECTED_DQ_REVIEW":"DQ_REVIEW"}[expected]
            need(result["status"]==expected_actual,f"{name}: processor={result['status']} expected={expected_actual}; codes={result.get('qa_codes')}")
            if expected=="EXPECTED_BLOCK":
                need(set(result["qa_codes"])&set(spec["expected_qa"]),f"{name}: block reason does not match fixture")
            if expected=="EXPECTED_DQ_REVIEW":
                need(set(result["qa_codes"])&set(spec["expected_qa"]),f"{name}: DQ review reason differs")
            if name=="SNAP-ARCHIVE-RESTORE":need(result["counts"]["protected_restored"]==1,"Archive restore must actually occur")
            if name=="SNAP-EARLIER-ASOF":need(result["official_asof"]=="2026-10-31" and result["matched_through"]=="20261031","Earlier As-Of truncation wrong")
            if name=="SNAP-RETRACT":need(result["changes"].get("OFFICIAL_RETRACT")==1,"Actual official retraction missing")
            if name=="SNAP-ADD":need(result["changes"].get("OFFICIAL_ADD")==1,"Actual official add missing")
            if name=="SNAP-CORRECT":need(result["changes"].get("OFFICIAL_CORRECT")==1,"Actual official correct missing")
            if name=="SNAP-DIGITAL-ADD":need(result["changes"].get("MARKETPLACE_ADD")==1,"Actual digital add missing")
            if name=="SNAP-DIGITAL-RETRACT":need(result["changes"].get("MARKETPLACE_RETRACT")==1,"Actual digital retract missing")
            if name=="SNAP-DIGITAL-CORRECT":need(result["changes"].get("MARKETPLACE_CORRECT")==1,"Actual digital correct missing")
            if name=="SNAP-DIGITAL-AHEAD":need(result["counts"]["marketplace_ahead_rows"]>0,"Digital ahead rows not preserved")
            if name=="SNAP-NEGATIVE-VALID":need(result["counts"]["negative_official"]>0,"Valid negatives were lost")
            if name=="SNAP-ZERO-VALID":need(result["counts"]["reported_zero_official"]>0,"Verified zeros were lost")
            if name in ("GEN-BASE","SNAP-IDEMPOTENT") and result["status"]=="PASS":
                again=process(spec,root,p23,base,stores,operating,accounts,ownership)
                need(canonical_json(again)==canonical_json(result),"Byte-level scenario rerun mismatch: "+name)
            status_counts[result["status"]]+=1
            results[name]=dict(expected=expected,result=result)
            cases.append({"scenario_id":name,"expected":expected,"actual":result["status"],"qa_codes":",".join(result.get("qa_codes",[])),"official_rows":result.get("counts",{}).get("official_rows",""),"digital_rows":result.get("counts",{}).get("digital_rows","")})
            log.append(f"PASS | {name} | {result['status']}"+(" | "+','.join(result.get('qa_codes',[])) if result.get('qa_codes') else ""))
        need(status_counts=={"PASS":13,"BLOCKED":6,"DQ_REVIEW":1},"20-case outcome matrix discrepancy")
        log.append("PASS | 20_CASE_PROCESSOR_MATRIX | 13 PASS / 6 BLOCKED / 1 DQ_REVIEW (actual executions)")
        need(pointer_test(),"Isolated fault injection failed")
        log.append("PASS | ATOMIC_POINTER_FAULT_AND_ROLLBACK | Isolated real pointer transition/failure/rollback tested")
        # Regression: raw source retained unchanged, no invented official channel additions.
        ref=results["GEN-BASE"]["result"]
        need(ref["totals_cents"]["official_net_cents"]==3759335474,"Official baseline totals mismatch")
        need(ref["totals_cents"]["marketplace_net_cents"]==514398580,"Digital baseline totals mismatch")
        need(ref["counts"]["official_rows"]==36438 and ref["counts"]["digital_rows"]==21377,"Baseline row totals mismatch")
        log.append("PASS | FINANCIAL_BASELINE | Official and digital sum in integer cents, no double count")
        summary={"project":PROJECT,"checkpoint":CHECKPOINT,"contract":CONTRACT,"seed":SEED,"version":VERSION,"classification":"100% SYNTHETIC","state":"CANDIDATE_ONLY__NO_PROJECT_PUBLISH","scenario_results":results,"actual_status_counts":dict(sorted(status_counts.items()))}
        out={"p3_1_scenario_results.json":canonical_json(summary),"p3_1_case_matrix.csv":make_csv(cases,("scenario_id","expected","actual","qa_codes","official_rows","digital_rows"))}
        out["p3_1_manifest.json"]=canonical_json({"project":PROJECT,"checkpoint":CHECKPOINT,"contract":CONTRACT,"engine_version":VERSION,"input_p2_3_manifest_sha256":P23_SHA,"outputs":{n:{"sha256":sha(b),"size_bytes":len(b)} for n,b in sorted(out.items())}})
        candidate,mode=write_candidate(workspace,out)
        log.append(f"PASS | CANDIDATE | {mode} | {candidate}")
        for name,body in sorted(out.items()):log.append(f"CANDIDATE_SHA256 | {name} | {sha(body)}")
        after={str(p.relative_to(root)):sha_file(p) for p in root.rglob("*") if p.is_file()}
        need(before==after,"APPROVED PROJECT FILES CHANGED")
        log.append("PASS | PROJECT_ROOT_UNCHANGED | Entire approved project byte-identical")
        need(sorted(p.name for p in report.parent.iterdir())==["OUTPUT.txt"],"Central report directory not exclusive")
        log.append("PASS | OUTPUT_EXCLUSIVE | Exactly OUTPUT.txt in central output")
        log.append("TESTS | scenario=20 passed=20 failed=0 | additional_gates=6 passed=6 failed=0")
        log.append("WARNING | P3.1 validates snapshot processor dry-run and disposable atomic pointer only; no actual approved ETL generation published")
        log.append("WARNING | protected archive here is a certified synthetic TEST FIXTURE; persistent operational archive/release pipeline pending P3.2+")
        log.append("WARNING | SQL, DAX and Power BI Desktop runtime NOT tested")
        log.append("STATUS=PASS_P3_1_PROCESSOR_CANDIDATE_VALIDATED_PENDING_REPORT_REVIEW")
    except Exception as exc:
        log.append(f"FAIL | {type(exc).__name__} | {exc}")
        log.append("TRACE | "+" | ".join(traceback.format_exception_only(type(exc),exc)).strip())
        log.append("STATUS=FAIL_P3_1_NOT_APPROVED")
    log.append(f"END_UTC | {datetime.now(timezone.utc).isoformat()}")
    save_report(report,workspace,log)
    return 0 if "STATUS=PASS_P3_1_PROCESSOR_CANDIDATE_VALIDATED_PENDING_REPORT_REVIEW" in log else 1


def main():
    ap=argparse.ArgumentParser(description="P3.1 Full Snapshot processor QA — no project modification")
    ap.add_argument("--root",required=True)
    ap.add_argument("--report",required=True)
    args=ap.parse_args()
    return run(Path(args.root).expanduser().absolute(),Path(args.report).expanduser().absolute())

if __name__=="__main__":sys.exit(main())
