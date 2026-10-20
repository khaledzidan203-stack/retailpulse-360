#!/usr/bin/env python3
"""Fail-closed publication scan and static native-report checks. No GUI claims."""
from pathlib import Path
import hashlib
import json
import re
import struct
import subprocess
import zlib

ROOT=Path(__file__).resolve().parents[1]


def need(ok, message):
    if not ok:
        raise RuntimeError(message)


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value,list):
        for child in value:
            yield from walk(child)


def png_check(body, path):
    need(body[:8]==b'\x89PNG\r\n\x1a\n','Invalid PNG '+path)
    offset=8;compressed=[];dimensions=None;chunks=[]
    while offset<len(body):
        length=struct.unpack('>I',body[offset:offset+4])[0]
        kind=body[offset+4:offset+8];data=body[offset+8:offset+8+length]
        crc=struct.unpack('>I',body[offset+8+length:offset+12+length])[0]
        need(zlib.crc32(kind+data)&0xffffffff==crc,'PNG CRC '+path)
        # Unknown metadata is a review hold, not silently ignored.
        need(kind in (b'IHDR',b'IDAT',b'IEND',b'sRGB',b'gAMA',b'pHYs',b'cHRM'), 'Unreviewed PNG metadata '+path+' '+repr(kind))
        if kind==b'IHDR': dimensions=struct.unpack('>II',data[:8])
        if kind==b'IDAT':compressed.append(data)
        chunks.append(kind.decode('ascii'));offset+=length+12
        if kind==b'IEND':break
    need(offset==len(body) and chunks[-1]=='IEND','PNG trailing bytes '+path)
    need(dimensions and min(dimensions)>600,'Screenshot resolution '+path)
    need(len(zlib.decompress(b''.join(compressed)))>0,'PNG data '+path)
    return dimensions


def static_checks():
    baseline=json.loads((ROOT/'release/powerbi_baseline.json').read_text())
    for rel,digest in baseline.items():
        need(hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()==digest,'Approved design changed '+rel)
    report=ROOT/'PowerBI/RetailPulse 360.Report'
    model=ROOT/'PowerBI/RetailPulse 360.SemanticModel/definition'
    pages=report/'definition/pages'
    index=json.loads((pages/'pages.json').read_text())
    definitions={p.parent.name:json.loads(p.read_text()) for p in pages.glob('*/page.json')}
    need(len(definitions)==11 and set(index['pageOrder'])==set(definitions),'Page index mismatch')
    need(index['activePageName'] in definitions,'Invalid active page')
    tables={}; measures=0
    for path in (model/'tables').glob('*.tmdl'):
        text=path.read_text('utf-8-sig')
        table=re.search(r'^table (.+)$',text,re.M).group(1).strip("'")
        fields={kind:set() for kind in ('column','measure','hierarchy')}
        for kind,quoted,plain in re.findall(r"^\t(column|measure|hierarchy) (?:'([^']+)'|([^\s=]+))",text,re.M):
            fields[kind].add(quoted or plain)
        measures+=len(fields['measure']);tables[table]=fields
    need(measures==43,'Original measure count changed')
    model_text=(model/'model.tmdl').read_text()
    need(set(re.findall(r'^ref table (.+)$',model_text,re.M))==set(tables),'Model table index mismatch')
    relations=(model/'relationships.tmdl').read_text()
    for entity,column in re.findall(r'^\s*(?:fromColumn|toColumn): ([^.\n]+)\.([^\n]+)',relations,re.M):
        entity=entity.strip().strip("'");column=column.strip().strip("'")
        need(entity in tables and column in tables[entity]['column'],'Invalid relationship endpoint '+entity+'.'+column)
    visuals=0;bindings=0;gauges=[];page_summary=[]
    for pid in index['pageOrder']:
        page=definitions[pid]; files=list((pages/pid/'visuals').glob('*/visual.json'))
        page_summary.append({'page':page['displayName'],'visuals':len(files)})
        for path in [pages/pid/'page.json',*files]:
            obj=json.loads(path.read_text()); aliases={}
            for node in walk(obj):
                for source in node.get('From',[]):
                    if isinstance(source,dict) and 'Name' in source and 'Entity' in source: aliases[source['Name']]=source['Entity']
            for node in walk(obj):
                for kind in ('Column','Measure','Hierarchy'):
                    ref=node.get(kind)
                    if not isinstance(ref,dict) or 'Property' not in ref:continue
                    source=ref.get('Expression',{}).get('SourceRef',{})
                    entity=source.get('Entity') or aliases.get(source.get('Source'))
                    need(entity in tables,'Unknown entity '+str(entity)+' in '+str(path.relative_to(ROOT)))
                    need(ref['Property'] in tables[entity][kind.lower()], 'Unknown binding '+entity+'.'+ref['Property'])
                    bindings+=1
            if path.name=='visual.json':
                visuals+=1;need(obj['name']==path.parent.name,'Visual ID mismatch')
                if obj.get('visual',{}).get('visualType')=='gauge':
                    gauges.append({'page':page['displayName'],'roles':sorted(obj['visual']['query']['queryState'])})
        if page['displayName'].startswith(('05 ','06 ')):
            expected='RETAIL' if page['displayName'].startswith('05 ') else 'PROGRAM'
            filters=page.get('filterConfig',{}).get('filters',[])
            need(any(f.get('isLockedInViewMode') and "'"+expected+"'" in json.dumps(f) for f in filters),'Channel scope missing')
    expressions=(model/'expressions.tmdl').read_text()
    need('expression pProjectRoot = "SET_LOCAL_BUILD_PROJECT_ROOT"' in expressions,'Missing local root placeholder')
    need('LocalProjectRoot = pProjectRoot' in (model/'tables/Query1.tmdl').read_text(),'Query1 bypasses root parameter')
    # Shared loader reads only parameters/files; none of these three expressions depends on a table.
    need(set(re.findall(r'^expression (\w+) =',expressions,re.M))=={'pProjectRoot','pGeneration','fnLoadCsv'},'Unexpected shared M expression')
    need('fnLoadCsv(' not in expressions,'Recursive shared loader')
    digital=next(d for d in definitions.values() if d['displayName'].startswith('09 '))
    need(not digital.get('filterConfig',{}).get('filters'),'Unexpected page-wide digital filter; review matched scopes')
    return dict(pages=11,measures=measures,visuals=visuals,bindings=bindings,protected_files=len(baseline),gauges=gauges,page_summary=page_summary,desktop_runtime='NOT RUN')


def public_scan():
    findings=[]; files=[]; screenshots=[]
    # No per-file size limit. PNG compressed pixels are decoded and metadata is allowlisted.
    patterns={
        'absolute workstation path':re.compile(r'(?i)\b[A-Z]:[\\/]|/(?:Users|home)/[^/\s]+|\\\\[A-Za-z0-9_-]+\\(?!\\)'),
        'email address':re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'),
        'credential':re.compile(r'(?i)(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:password|api_key|access_token)\s*[:=]\s*[\"\x27][^\"\x27\s]{8,})'),
    }
    if (ROOT/'.git').exists():
        names=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode('utf-8').split('\0')
        candidates=sorted({ROOT/name for name in names if name})
    else:
        candidates=sorted(ROOT.rglob('*'))
    for p in candidates:
        rel=p.relative_to(ROOT).as_posix()
        if '.git' in p.relative_to(ROOT).parts:continue
        need(not p.is_symlink(),'Symlink in public tree '+rel)
        if not p.is_file():continue
        need(not any(x in p.relative_to(ROOT).parts for x in ('.pbi','__pycache__','.venv')),'Private/generated directory '+rel)
        need(p.suffix.lower() not in ('.sqlite','.db','.abf','.zip','.pyc','.pem','.key','.pfx'),'Forbidden binary '+rel)
        body=p.read_bytes()
        if p.suffix.lower()=='.png': screenshots.append((rel,png_check(body,rel)))
        else:
            try:text=body.decode('utf-8-sig')
            except UnicodeDecodeError:raise RuntimeError('Unreviewed binary '+rel)
            need('\x00' not in text,'NUL/binary text '+rel)
            for label,pattern in patterns.items():
                if pattern.search(text):findings.append({'file':rel,'category':label})
        files.append({'path':rel,'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()})
    need(len(screenshots)==11,'Expected 11 screenshots')
    need(not findings,'Publication scan holds: '+json.dumps(findings))
    return files,screenshots


if __name__=='__main__':
    result=static_checks()
    files,shots=public_scan()
    result.update(public_files=len(files),public_bytes=sum(f['bytes'] for f in files),screenshots=len(shots),privacy_scan='PASS; all file bytes, PNG decoded and metadata checked; visual review recorded separately')
    print(json.dumps(result,indent=2))
