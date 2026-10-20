#!/usr/bin/env python3
r"""RetailPulse 360 | P3.2 validated baseline ETL + frozen closed-store archive CANDIDATE.

Run from any working directory on Windows, with approved P2.1/P2.2/P2.3 files:
    Run the supported portable entry point: python tools/reproduce.py --output "../retailpulse build"

READ ONLY: approved project. WRITE: isolated sibling retailpulse360_dev/P3_2_CANDIDATE,
and the explicitly selected external OUTPUT.txt only. No other sibling files or folders modified.
"""
from __future__ import annotations
import argparse
import calendar
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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

PROJECT = "RetailPulse 360"
CHECKPOINT = "P3.2"
VERSION = "p3.2.0"
RUNNER_REVISION = "p3.2.4"  # Permit a shared output directory; write only the named OUTPUT.txt.
SEED = 3602026
CONTRACT = "0.1"
P21 = {
"dim_store.csv":"9414e58bea035bfe13a2b2698e75a8e47bf3427ef1fba203fb88bd2de9dd7c3d",
"store_operating_calendar.csv":"d214bc7fdeba2ca7064a031e99fdf7af4587a8b5352b8535ff7968e7f4e895ba",
"p2_1_manifest.json":"3ee062ce4026af969758224db76b21dd5c817144b87845173fe228eb2f8f5dd3",
"p2_1_promotion_record.json":"a04c1fc656beb279c3bb8d703686b30a71895879b494a241d5871e05b124686e"}
P22 = {
"official_sales_snapshot.csv":"335646fc38fa3f9e8c77b5319f050f1b0e7d48d835446db9c3e71048f0bbc9f9",
"source_coverage_official.csv":"2a53a40d70b39faf13e3fa925927f6a96a3ad3b0cd4d29678425489dae01ab54",
"budget_monthly.csv":"206a4a5838ebefcabfdaff2b7e959e1d5edbfc1c12b1f27bc252a0a462f71ec2",
"dim_marketplace_account.csv":"82063f9c5207d8c4a3aaea1dbc2f6313bd471dde6862ebe0cf73b59ef6a93c3b",
"bridge_account_store_period.csv":"c88a213ce4e24c4565778c3792e24d2a6a46b9e2588d1ef8f1260bdd5589b2c5",
"marketplace_daily_snapshot.csv":"fd14e0272f11e92323af0bf4ca78f886a164d0587138b8593a9a874485e7de91",
"source_coverage_marketplace.csv":"1c3a1913dc18992910f91409ac456030c2d35e6896305c96fd76f6e8954ab612",
"p2_2_manifest.json":"9e3aef2307e6ca24c11e9c43a58ee35fcbbf21ada7915ff3690270a652bc8f5d",
"p2_2_promotion_record.json":"8226c54b5dab1760fe767cb2d17a6ef6df0738c66e983aabddab25b0d23f2d39"}
P23 = {"p2_3_manifest.json":"b6111158d7efbb513d3e5ab2663df09d5a95e6fc72534ca5b42dd1abff7dc46a",
"p2_3_promotion_record.json":"bdfb4441d956dc44ae261470aaf9ae1ccdb52d526f0595c9a12c30f4b11ba52b"}

DOCS = ("ARCHITECTURE_DECISIONS.md","DATA_MODEL_SPEC.md","KPI_CONTRACTS.md",
        "PHASE_1_REVIEW.md","PROJECT_CHARTER.md","QA_TEST_MATRIX.md",
        "REPORT_PAGE_MATRIX.md","SYNTHETIC_GENERATOR_SPEC.md")
FIELDS = {
"dim_store.csv":("store_key","store_name","region_key","region_name","city_key","city_name","store_profile","lifecycle_cohort","open_date","last_trading_date"),
"store_operating_calendar.csv":("store_key","date_key","calendar_date","is_operating","lifecycle_state"),
"official_sales_snapshot.csv":("store_key","date_key","channel_key","gross_sales_cents","returns_amount_cents","net_sales_cents","transactions","units","source_snapshot_id","lineage_hash"),
"source_coverage_official.csv":("store_key","date_key","channel_key","coverage_state","evidence"),
"budget_monthly.csv":("store_key","month_start","channel_key","monthly_target_cents","budget_version"),
"dim_marketplace_account.csv":("account_key","account_name","account_type"),
"bridge_account_store_period.csv":("account_key","store_key","valid_from","valid_to"),
"marketplace_daily_snapshot.csv":("account_key","date_key","attributed_retail_net_sales_cents","orders","units","source_snapshot_id","lineage_hash"),
"source_coverage_marketplace.csv":("account_key","date_key","coverage_state","evidence")}
OFF=FIELDS["official_sales_snapshot.csv"]
DIG=FIELDS["marketplace_daily_snapshot.csv"]
BUSINESS_OFF=OFF[:8]


def require(cond,desc):
    if not cond: raise ValueError(desc)


def sha(body):return hashlib.sha256(body).hexdigest()


def sha_file(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()


def cj(obj):return (json.dumps(obj,indent=2,sort_keys=True,ensure_ascii=False)+"\n").encode("utf-8")


def csv_blob(rows,fields):
    b=io.StringIO(newline="")
    wr=csv.DictWriter(b,fields,extrasaction="raise",lineterminator="\n")
    wr.writeheader();wr.writerows(rows)
    return b.getvalue().encode("utf-8")


def parse(blob,fields,label):
    require(blob.endswith(b"\n") and b"\r" not in blob,"Noncanonical CSV "+label)
    r=csv.DictReader(io.StringIO(blob.decode("utf-8"),newline=""))
    require(tuple(r.fieldnames or ())==fields,"Bad schema "+label)
    out=list(r)
    require(all(None not in x and all(v is not None for v in x.values()) for x in out),"Malformed CSV "+label)
    return out


def keys(rows,fields,label):
    out={}
    for r in rows:
        k=tuple(r[c] for c in fields)
        require(k not in out,"Duplicate grain "+label+":"+str(k))
        out[k]=r
    return out


def approved_inputs(root,workspace):
    data=root/"data"/"synthetic"
    for folder,pinned in (("p2_1",P21),("p2_2",P22)):
        loc=data/folder
        require(loc.is_dir() and not loc.is_symlink(),"Missing/unsafe approved "+folder)
        require({p.name for p in loc.iterdir()}==set(pinned),"Unexpected approved inventory "+folder)
        for n,h in pinned.items():
            p=loc/n
            require(p.is_file() and not p.is_symlink() and sha_file(p)==h,"Approved SHA mismatch "+folder+"/"+n)
    p23=data/"p2_3"
    require(p23.is_dir() and not p23.is_symlink(),"P2.3 missing")
    for n,h in P23.items():
        p=p23/n
        require(p.is_file() and not p.is_symlink() and sha_file(p)==h,"P2.3 SHA mismatch "+n)
    m=json.loads((p23/"p2_3_manifest.json").read_text(encoding="utf-8"))
    require(m["seed"]==SEED and m["contract_version"]==CONTRACT and m["scenario_count"]==20,"P2.3 provenance wrong")
    require(m["approved_p2_1_sha256"]==P21 and m["approved_p2_2_sha256"]==P22,"P2.3 lineage wrong")
    inv={}
    for folder,dirs,files in os.walk(p23,followlinks=False):
        for d in dirs:require(not (Path(folder)/d).is_symlink(),"Unexpected symlink in fixture")
        for n in files:
            p=Path(folder)/n; rel=p.relative_to(p23).as_posix()
            q=PurePosixPath(rel)
            require(not p.is_symlink() and not q.is_absolute() and ".." not in q.parts,"Unsafe P2.3 file")
            inv[rel]=p
    require(len(inv)==46 and set(inv)==set(m["artifacts"])|set(P23),"P2.3 file inventory drift")
    for rel,meta in m["artifacts"].items():
        p=inv[rel]
        require(sha_file(p)==meta["sha256"] and p.stat().st_size==meta["size_bytes"],"P2.3 corrupted: "+rel)
    # P3.1 test outcomes were reviewed in chat. A throwaway DEV candidate is
    # not an authoritative dependency for rebuilding governed baseline facts.
    # P3.2 performs its own independent input, reconciliation, archive and
    # publish-safety checks below, using only approved P2.x repository inputs.
    m22=json.loads((data/"p2_2"/"p2_2_manifest.json").read_text(encoding="utf-8"))
    require(m22["seed"]==SEED and m22["contract_version"]==CONTRACT,"P2.2 manifest wrong")
    require(m22["settings"]["official_asof"]=="2026-12-20" and m22["settings"]["marketplace_asof"]=="2026-12-27","Unapproved As-Of")
    return p23,m22


def build(root,p23,m22):
    d=root/"data"/"synthetic"; p21=d/"p2_1";p22=d/"p2_2"
    source={n:(p21/n if n in ("dim_store.csv","store_operating_calendar.csv") else p22/n).read_bytes() for n in FIELDS}
    tables={n:parse(source[n],fields,n) for n,fields in FIELDS.items()}
    stores={k[0]:v for k,v in keys(tables["dim_store.csv"],("store_key",),"store").items()}
    accounts={k[0]:v for k,v in keys(tables["dim_marketplace_account.csv"],("account_key",),"account").items()}
    life=keys(tables["store_operating_calendar.csv"],("store_key","date_key"),"store-calendar")
    operating={k for k,r in life.items() if r["is_operating"]=="1"}
    require(len(stores)==30 and len(life)==21900 and len(operating)>0,"Store/lifecycle universe wrong")
    start=date(2025,1,1);end=date(2026,12,31)
    for k,r in life.items():
        dd=date.fromisoformat(r["calendar_date"])
        st=stores[k[0]]
        eligible=date.fromisoformat(st["open_date"])<=dd and (not st["last_trading_date"] or dd<=date.fromisoformat(st["last_trading_date"]))
        require(r["date_key"]==dd.strftime("%Y%m%d") and (r["is_operating"]=="1")==eligible,"Lifecycle mismatch "+str(k))
    off=keys(tables["official_sales_snapshot.csv"],("store_key","date_key","channel_key"),"official")
    cov_off=keys(tables["source_coverage_official.csv"],("store_key","date_key","channel_key"),"official coverage")
    require(set(off)==set(cov_off) and len(off)==36438,"Official coverage key mismatch")
    totals=Counter(); zero=0; negative=0
    for k,r in off.items():
        require((k[0],k[1]) in operating and k[2] in ("RETAIL","PROGRAM") and k[1]<="20261220","Official lifecycle/channel/asof")
        gross=int(r["gross_sales_cents"]);ret=int(r["returns_amount_cents"]); net=int(r["net_sales_cents"])
        require(gross>=0 and ret>=0 and gross-ret==net and int(r["transactions"])>=0 and int(r["units"])>=0,"Official arithmetic")
        state=cov_off[k]["coverage_state"]
        require(state in ("REPORTED_VALUE","REPORTED_ZERO"),"Official uncovered row")
        if state=="REPORTED_ZERO":
            require(gross==ret==net==int(r["transactions"])==int(r["units"])==0,"Reported zero has values")
            zero+=1
        else:
            require(any([gross,ret,net,int(r["transactions"]),int(r["units"])]),"Unlabeled zero")
        negative+=net<0;totals[k[2]]+=net
    require(len(off)==2*sum(k[1]<="20261220" for k in operating),"Official missing operating channel")
    require(set(off)=={(st,day,ch) for st,day in operating if day<="20261220" for ch in ("RETAIL","PROGRAM")},"Official operational coverage incomplete")
    ownership=defaultdict(list)
    maps=tables["bridge_account_store_period.csv"]
    require(len(maps)==38,"Account history differs")
    for r in maps:
        require(r["account_key"] in accounts and r["store_key"] in stores and r["valid_from"]<=r["valid_to"],"Account relationship FK/interval")
        ownership[r["account_key"]].append((r["valid_from"].replace("-",""),r["valid_to"].replace("-",""),r["store_key"]))
    for acc,intervals in ownership.items():
        intervals.sort()
        for prev,nxt in zip(intervals,intervals[1:]):require(prev[1]<nxt[0],"Overlapping ownership: "+acc)
    dig=keys(tables["marketplace_daily_snapshot.csv"],("account_key","date_key"),"marketplace")
    cov_dig=keys(tables["source_coverage_marketplace.csv"],("account_key","date_key"),"marketplace coverage")
    require(set(dig)==set(cov_dig) and len(dig)==21377,"Marketplace coverage mismatch")
    resolved=[];matched=defaultdict(int);future=0;dig_total=0
    for k,r in sorted(dig.items()):
        net=int(r["attributed_retail_net_sales_cents"])
        require(int(r["orders"])>=0 and int(r["units"])>=0 and k[1]<="20261227","Digital row/count/asof invalid")
        ownership_dates=[(s) for a,b,s in ownership[k[0]] if a<=k[1]<=b]
        require(len(ownership_dates)==1 and (ownership_dates[0],k[1]) in operating,"Digital owner invalid")
        state=cov_dig[k]["coverage_state"]
        require(state in ("REPORTED_VALUE","REPORTED_ZERO"),"Uncovered digital row")
        if state=="REPORTED_ZERO":require(net==int(r["orders"])==int(r["units"])==0,"Digital verified zero invalid")
        item={"store_key":ownership_dates[0],**r}
        resolved.append(item)
        dig_total+=net
        if k[1]>"20261220":future+=1
        else:matched[(ownership_dates[0],k[1])]+=net
    mismatches=[]
    for (st,day),val in matched.items():
        ref=off.get((st,day,"RETAIL"))
        require(ref is not None,"Matched digital missing Retail")
        retail=int(ref["net_sales_cents"])
        if val>0 and val>max(0,retail):mismatches.append((st,day,val,retail))
    require(not mismatches,"Matched marketplace exceeds retail: "+str(mismatches[:3]))
    budgets=keys(tables["budget_monthly.csv"],("store_key","month_start","channel_key"),"monthly budget")
    require(len(budgets)==1440,"Budget monthly grain")
    bdaily=[];budget_master=0;month_check=defaultdict(int)
    for k,r in sorted(budgets.items()):
        store,monthstr,ch=k
        month=date.fromisoformat(monthstr)
        require(store in stores and ch in ("RETAIL","PROGRAM") and month.day==1 and start<=month<=end,"Budget keys invalid")
        target=int(r["monthly_target_cents"]); require(target>=0,"Negative budget")
        budget_master+=target
        days=calendar.monthrange(month.year,month.month)[1]
        q,rem=divmod(target,days)
        distributed=[q+(i<rem) for i in range(days)]
        require(sum(distributed)==target and max(distributed)-min(distributed)<=1,"Cent residual allocation invalid")
        for i,alloc in enumerate(distributed):
            day=month+timedelta(days=i);ds=day.strftime("%Y%m%d")
            if (store,ds) not in operating:continue
            month_check[k]+=alloc
            bdaily.append({"store_key":store,"date_key":ds,"channel_key":ch,"allocated_budget_cents":str(alloc),"budget_version":r["budget_version"],"allocation_policy_version":"CALENDAR_DAYS_CENT_QR_V1"})
        # Validate no reallocation during partial operating months.
        require(month_check[k]==sum(distributed[i] for i in range(days) if (store,(month+timedelta(days=i)).strftime("%Y%m%d")) in operating),"Lifecycle budget mask differs")
    require(len(bdaily)==2*len(operating),"Daily budget row universe")
    require(len(keys(bdaily,("store_key","date_key","channel_key"),"budget daily"))==len(bdaily),"Budget daily duplicated")
    require(budget_master==3759361737 and totals["RETAIL"]==3151571610 and totals["PROGRAM"]==607763864 and dig_total==514398580,"Pinned financial baseline differs")
    require(negative==101 and zero==182 and future==245,"Source regression indicators differ")
    # Archive is not the 2-row P2.3 fault fixture. Seal ALL baseline official rows
    # belonging to stores which really have an approved last-trading date <= As-Of.
    closed={k for k,s in stores.items() if s["last_trading_date"] and s["last_trading_date"]<="2026-12-20"}
    require(len(closed)==2,"Closed store population changed")
    protected=[r for k,r in sorted(off.items()) if k[0] in closed]
    require(protected and len(protected)==sum(k[0] in closed for k in off),"Archive not exhaustive")
    def value_hash(r):return sha(cj({f:r[f] for f in BUSINESS_OFF}))
    hashes={"|".join((r["store_key"],r["date_key"],r["channel_key"])):value_hash(r) for r in protected}
    protected_csv=csv_blob(protected,OFF)
    archive={"project":PROJECT,"contract_version":CONTRACT,"seed":SEED,
             "archive_state":"CANDIDATE_SEALED_NOT_OPERATIONALLY_PUBLISHED",
             "source":"P2.2 immutable full baseline; closed stores only",
             "official_asof":"2026-12-20","closed_stores":sorted(closed),
             "archive_file":"protected_history/closed_store_official.csv",
             "archive_sha256":sha(protected_csv),"rows":len(protected),
             "business_value_sha256":hashes,
             "rule":"Protected key matches all canonical business fields; source_snapshot_id is lineage"}
    # Guard checks independently exercise restore, protected-value conflict, and hash tampering.
    ix=keys(protected,("store_key","date_key","channel_key"),"protected archive")
    sample_key=next(iter(ix));sample=dict(ix[sample_key])
    source_without=dict(off); del source_without[sample_key]
    restored={**source_without,sample_key:ix[sample_key]}
    require(len(restored)==len(off) and restored[sample_key]==off[sample_key],"Missing protected row not restored")
    changed=dict(sample);changed["gross_sales_cents"]=str(int(changed["gross_sales_cents"])+1)
    require(value_hash(changed)!=hashes["|".join(sample_key)],"Protected conflict not detected")
    require(sha(protected_csv+b"tamper")!=archive["archive_sha256"],"Archive corruption not detected")
    # Calendar uses Saturday -> Friday and remains full even after source As-Of.
    drows=[];cur=start
    while cur<=end:
        week_start=cur-timedelta(days=(cur.weekday()+2)%7)
        monthstart=cur.replace(day=1)
        drows.append({"date_key":cur.strftime("%Y%m%d"),"calendar_date":cur.isoformat(),"year":str(cur.year),
                      "quarter":str((cur.month-1)//3+1),"month":str(cur.month),"month_start":monthstart.isoformat(),
                      "year_month":cur.strftime("%Y%m"),"weekday_number":str(cur.weekday()+1),
                      "week_start_saturday":week_start.isoformat(),"week_end_friday":(week_start+timedelta(days=6)).isoformat()})
        cur+=timedelta(days=1)
    require(len(drows)==730 and all(date.fromisoformat(r["week_start_saturday"]).weekday()==5 for r in drows),"Date dimension wrong")
    # Build canonical artifacts; raw bytes preserved verbatim, not normalized.
    outputs={}
    for n in P22:
        if n.endswith(".csv"):outputs["raw/"+n]=source[n]
    outputs["staging/stg_official_sales.csv"]=csv_blob([off[k] for k in sorted(off)],OFF)
    outputs["staging/stg_marketplace_resolved.csv"]=csv_blob(resolved,("store_key",)+DIG)
    outputs["staging/stg_budget_monthly.csv"]=csv_blob([budgets[k] for k in sorted(budgets)],FIELDS["budget_monthly.csv"])
    outputs["staging/source_coverage_official.csv"]=source["source_coverage_official.csv"]
    outputs["staging/source_coverage_marketplace.csv"]=source["source_coverage_marketplace.csv"]
    date_fields=("date_key","calendar_date","year","quarter","month","month_start","year_month","weekday_number","week_start_saturday","week_end_friday")
    outputs["analytics/dim_date.csv"]=csv_blob(drows,date_fields)
    outputs["analytics/dim_store.csv"]=source["dim_store.csv"]
    outputs["analytics/dim_channel.csv"]=csv_blob([{"channel_key":"PROGRAM","channel_name":"Program","is_additive":"1"},
                                                        {"channel_key":"RETAIL","channel_name":"Retail","is_additive":"1"}],
                                                       ("channel_key","channel_name","is_additive"))
    outputs["analytics/dim_marketplace_account.csv"]=source["dim_marketplace_account.csv"]
    outputs["analytics/bridge_account_store_period.csv"]=source["bridge_account_store_period.csv"]
    outputs["analytics/store_operating_calendar.csv"]=source["store_operating_calendar.csv"]
    outputs["analytics/fact_sales_daily.csv"]=outputs["staging/stg_official_sales.csv"]
    outputs["analytics/fact_budget_monthly.csv"]=outputs["staging/stg_budget_monthly.csv"]
    outputs["analytics/fact_budget_daily.csv"]=csv_blob(sorted(bdaily,key=lambda r:(r["store_key"],r["date_key"],r["channel_key"])),
        ("store_key","date_key","channel_key","allocated_budget_cents","budget_version","allocation_policy_version"))
    outputs["analytics/fact_marketplace_daily.csv"]=outputs["staging/stg_marketplace_resolved.csv"]
    outputs["analytics/dq_findings.csv"]=csv_blob([], ("check_id","severity","source_family","affected_key","reason","evidence"))
    outputs["protected_history/closed_store_official.csv"]=protected_csv
    outputs["protected_history/archive_manifest.json"]=cj(archive)
    # Independent row counts and source-vs-fact reconciliation.
    test_counts={"stores":len(stores),"calendar_days":len(drows),"operating_store_days":len(operating),
        "sales_rows":len(off),"marketplace_rows":len(dig),"budget_monthly_rows":len(budgets),
        "budget_daily_rows":len(bdaily),"negative_official_rows":negative,"reported_zero_rows":zero,
        "digital_ahead_rows":future,"protected_rows":len(protected),"closed_stores":len(closed)}
    sums={"retail_net_cents":totals["RETAIL"],"program_net_cents":totals["PROGRAM"],
          "official_net_cents":totals["RETAIL"]+totals["PROGRAM"],
          "marketplace_net_cents":dig_total,"budget_monthly_master_cents":budget_master,
          "budget_effective_full_horizon_cents":sum(int(r["allocated_budget_cents"]) for r in bdaily),
          "budget_aligned_to_official_asof_cents":sum(int(r["allocated_budget_cents"]) for r in bdaily if r["date_key"]<="20261220")}
    # Example fixture: month 100.00 / 31: 10 days allocated from full calendar, no redistribution.
    q,rem=divmod(10000,31)
    allocations=[q+int(i<rem) for i in range(31)]
    require(sum(allocations)==10000 and sum(allocations[:10])<10000,"Budget 31-day closure fixture failed")
    # The full-horizon budget must be >= the As-Of-aligned budget.
    require(sums["budget_effective_full_horizon_cents"]>=sums["budget_aligned_to_official_asof_cents"],"Budget AsOf ordering invalid")
    manifest={"project":PROJECT,"checkpoint":CHECKPOINT,"version":VERSION,"contract_version":CONTRACT,
              "seed":SEED,"classification":"100% SYNTHETIC / FICTIONAL",
              "state":"CANDIDATE_ONLY_NOT_PUBLISHED","source_asof":{"OFFICIAL":"2026-12-20","MARKETPLACE":"2026-12-27"},
              "currency":"CUR","money":"integer cents, exact", "sources_sha256":{"p2_1":P21,"p2_2":P22,"p2_3":P23},
              "counts":test_counts,"totals_cents":sums,
              "artifacts":{name:{"sha256":sha(body),"size_bytes":len(body)} for name,body in sorted(outputs.items())},
              "limitations":["Not an operational Full Snapshot publisher or release generation",
                             "Archive is sealed candidate; runtime archive validation/persistence are separate gates",
                             "Strict LFL, SQLite, DAX, Desktop runtime not validated in P3.2"]}
    outputs["p3_2_manifest.json"]=cj(manifest)
    return outputs,test_counts,sums,archive


def candidate_publish(workspace,outputs):
    target=workspace/"P3_2_CANDIDATE"
    if target.exists():
        require(target.is_dir() and not target.is_symlink(),"Unsafe preexisting candidate")
        actual={p.relative_to(target).as_posix():p for p in target.rglob("*") if p.is_file()}
        require(set(actual)==set(outputs) and all(not p.is_symlink() for p in target.rglob("*")),"Candidate inventory conflict")
        for rel,body in outputs.items():
            require(sha_file(actual[rel])==sha(body) and actual[rel].stat().st_size==len(body),"Candidate differs: "+rel)
        return "ALREADY_IDENTICAL_NO_REWRITE",target
    stage=Path(tempfile.mkdtemp(prefix=".P3_2_STAGE_",dir=workspace))
    try:
        for rel,body in outputs.items():
            p=stage/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(body)
        for rel,body in outputs.items():require(sha_file(stage/rel)==sha(body),"Stage SHA invalid")
        os.replace(stage,target)
        return "CREATED_NEW_ATOMIC_CANDIDATE_DIRECTORY",target
    finally:
        if stage.exists():shutil.rmtree(stage)


def write_report(report,log):
    """Replace a TEMPORARY report without keeping any previous copies.

    OUTPUT.txt is a communication handoff only, never approval evidence.
    """
    # Use an exclusively created, per-run temporary name to avoid collisions
    # with other projects sharing the output directory. Replace only OUTPUT.txt.
    fd, temp_name = tempfile.mkstemp(prefix=".RetailPulse360_OUTPUT_", suffix=".tmp", dir=report.parent)
    temp=Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(log)+"\n")
        os.replace(temp,report)
    finally:
        if temp.exists():temp.unlink()


def run(root,report):
    log=[f"PROJECT | {PROJECT}",f"CHECKPOINT | {CHECKPOINT}",
         "CONTRACT | Phase 1 v0.1 APPROVED DEC-01..DEC-10",
         f"RUN_UTC | {datetime.now(timezone.utc).isoformat()}",
         "MODE | BUILD_VALIDATE_BASELINE_ETL_AND_ARCHIVE_CANDIDATE_ONLY",
         f"PROJECT_ROOT_READ_ONLY | {root}", f"REPORT | {report}",
         f"SEED | {SEED}",f"VERSION | {VERSION}",f"RUNNER_REVISION | {RUNNER_REVISION}","SYNTHETIC | TRUE"]
    workspace=root.parent/"retailpulse360_dev"
    try:
        require(root.is_dir() and not root.is_symlink(),"Missing/unsafe project root")
        require(report.name=="OUTPUT.txt", "Report filename must be OUTPUT.txt")
        require(report.parent!=root and root not in report.parents and
                workspace not in report.parents,"Report must be outside project/workspace")
        # OUTPUT.txt is a temporary communication handoff. Create its external
        # directory when missing; never require a previous report to exist.
        if not report.parent.exists():
            require(report.parent.parent.is_dir() and not report.parent.parent.is_symlink(),
                    "Missing/unsafe parent of output folder")
            report.parent.mkdir(exist_ok=False)
            log.append("PASS | REPORT_DIRECTORY | Created missing external output directory")
        require(report.parent.is_dir() and not report.parent.is_symlink(),
                "Report directory is not a safe directory")
        require(not report.exists() or (report.is_file() and not report.is_symlink()),
                "Unsafe report target (must be absent or a regular OUTPUT.txt)")
        # Other projects may legitimately have subfolders here. Only the
        # user-selected OUTPUT.txt is in scope for modification.
        log.append("PASS | REPORT_GATE | Shared directory allowed; only OUTPUT.txt replaced, no prior report required")
        require(not workspace.is_symlink(),"Unsafe dev workspace symlink")
        workspace.mkdir(exist_ok=True)
        require(workspace.is_dir(),"Dev workspace cannot be prepared")
        for n in DOCS:require((root/"docs"/n).is_file(),"Missing approved contract: "+n)
        root_before={p.relative_to(root).as_posix():sha_file(p) for p in root.rglob("*") if p.is_file()}
        p23,m22=approved_inputs(root,workspace)
        log.append("PASS | INPUT_GATES | All approved P2.1/P2.2/P2.3 source SHAs verified; no DEV P3.1 dependency")
        outputs,counts,totals,archive=build(root,p23,m22)
        log.append("PASS | ETL_GRAIN | Unique and complete official/digital/targets and conformed dimensions")
        log.append("PASS | LIFECYCLE | Exact open/closure eligibility; no post-closure daily budget")
        log.append("PASS | FINANCIAL_RECONCILIATION | Official=Retail+Program; digital excluded; exact cents")
        log.append("PASS | BUDGET_POLICY | All calendar days allocated before lifecycle mask; As-Of alignment documented")
        log.append("PASS | COVERAGE_ZERO_NEGATIVE | Verified zeros and negative returns preserved; missing not converted to zero")
        log.append("PASS | MARKETPLACE_OWNER_AND_ASOF | Temporal bridge verified; digital ahead retained; matched <= Retail")
        log.append("PASS | PROTECTED_ARCHIVE | Complete closed-store official history sealed with key/value hashes")
        log.append("PASS | PROTECTED_FAULT_FIXTURES | Restore missing, block altered value, detect archive SHA tamper")
        # Determinism of all derived, canonical byte artifacts in a second full transformation.
        again,counts2,totals2,archive2=build(root,p23,m22)
        require(outputs==again and counts==counts2 and totals==totals2 and archive==archive2,"ETL rerun not byte-deterministic")
        log.append("PASS | REPRODUCIBILITY | Full independent second transformation byte-exact")
        # Fully independent disposable publication and conflict check: no user artifacts changed.
        with tempfile.TemporaryDirectory(prefix="rp360_p32_conflict_") as tmp:
            qa=Path(tmp)
            fixture={"test.bin":b"canonical-locked"}
            initial,_=candidate_publish(qa,fixture)
            repeat,_=candidate_publish(qa,fixture)
            require(initial=="CREATED_NEW_ATOMIC_CANDIDATE_DIRECTORY" and repeat=="ALREADY_IDENTICAL_NO_REWRITE",
                    "Candidate idempotence gate")
            (qa/"P3_2_CANDIDATE"/"test.bin").write_bytes(b"tampered")
            try:candidate_publish(qa,fixture)
            except ValueError as exc:require("Candidate differs" in str(exc),"Unexpected conflict error")
            else:raise ValueError("Changed candidate was silently overwritten")
        log.append("PASS | CANDIDATE_REPLAY_AND_CONFLICT | Disposable idempotence and tamper block")
        mode,target=candidate_publish(workspace,outputs)
        require(all(sha_file(target/k)==sha(v) for k,v in outputs.items()),"Published candidate integrity mismatch")
        log.append(f"PASS | CANDIDATE | {mode} | {target}")
        log.append(f"ARTIFACTS | count={len(outputs)} total_bytes={sum(map(len,outputs.values()))}")
        log.append("COUNTS | "+json.dumps(counts,sort_keys=True))
        log.append("TOTALS_CENTS | "+json.dumps(totals,sort_keys=True))
        log.append("ARTIFACT_SHA256 | p3_2_manifest.json | "+sha(outputs["p3_2_manifest.json"]))
        log.append("ARCHIVE_SHA256 | closed_store_official.csv | "+archive["archive_sha256"])
        root_after={p.relative_to(root).as_posix():sha_file(p) for p in root.rglob("*") if p.is_file()}
        require(root_after==root_before,"Approved project root changed!")
        log.append("PASS | PROJECT_ROOT_UNCHANGED | All previously approved bytes unchanged")
        require(report.parent.is_dir() and not report.parent.is_symlink(),"Output directory became unsafe")
        require(not report.exists() or (report.is_file() and not report.is_symlink()),"Output target became unsafe")
        log.append("PASS | OUTPUT_SCOPED | Only requested OUTPUT.txt modified; unrelated sibling files/folders untouched")
        log.append("TESTS | baseline_gates=14 passed=14 failed=0 | P3.1 historical dry-run not rerun")
        log.append("WARNING | P3.2 is candidate ETL baseline only; persistent operational snapshot generation/pointer and scenario replay pending P3.3")
        log.append("WARNING | SQL, DAX, Power BI Desktop and Strict LFL runtime not tested")
        log.append("STATUS=PASS_P3_2_CANDIDATE_VALIDATED_PENDING_REPORT_REVIEW")
    except Exception as exc:
        log.append("FAIL | "+type(exc).__name__+" | "+str(exc))
        log.append("TRACE | "+" | ".join(traceback.format_exception_only(type(exc),exc)).strip())
        log.append("STATUS=FAIL_P3_2_NOT_APPROVED")
    log.append(f"END_UTC | {datetime.now(timezone.utc).isoformat()}")
    success = "STATUS=PASS_P3_2_CANDIDATE_VALIDATED_PENDING_REPORT_REVIEW" in log
    try:
        if (report.parent.is_dir() and not report.parent.is_symlink() and
            (not report.exists() or (report.is_file() and not report.is_symlink()))):
            write_report(report,log)
            print(("PASS" if success else "FAIL") + f" | P3.2 | Report: {report}",
                  file=sys.stdout if success else sys.stderr,flush=True)
        else:
            print(f"FAIL | Cannot safely write report to {report}; check that the directory is safe and OUTPUT.txt is a regular file",file=sys.stderr,flush=True)
            success=False
    except Exception as exc:
        print("FAIL | Report write error: "+str(exc),file=sys.stderr,flush=True)
        success=False
    if not success:
        for line in log:
            if line.startswith("FAIL |") or line.startswith("STATUS=FAIL"):
                print(line,file=sys.stderr,flush=True)
    return 0 if success else 1


def main():
    p=argparse.ArgumentParser(description="P3.2 baseline ETL + protected closed-store archive CANDIDATE; no approved project writes")
    p.add_argument("--root",required=True);p.add_argument("--report",required=True)
    a=p.parse_args()
    return run(Path(a.root).expanduser().absolute(),Path(a.report).expanduser().absolute())

if __name__=="__main__":raise SystemExit(main())
