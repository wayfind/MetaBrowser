#!/usr/bin/env python3
"""Inventory the trusted generated Blink IDL database, not regex guesses.

Only run against an owned pinned build: pickle is a trusted build artifact,
never an arbitrary download. This lists potential declarations, not runtime
availability or proof of privacy protection. No browser/device/provider calls.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('--out',default='out/metabrowser-mac-arm64');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    root=a.source.resolve(strict=True)
    assert (root/'chrome/VERSION').read_text().splitlines()==['MAJOR=154','MINOR=0','BUILD=8037','PATCH=97']
    database=(root/a.out/'gen/third_party/blink/renderer/bindings/web_idl_database.pickle').resolve(strict=True)
    assert database.is_relative_to(root)
    before=sha(database);sys.dont_write_bytecode=True;sys.path.insert(0,str(root/'third_party/blink/renderer/bindings/scripts'))
    import web_idl
    db=web_idl.Database.read_from_file(str(database))
    source_files={};types=[];members=[]
    def location(item):
        loc=item.debug_info.location
        if loc is None:return None
        path=Path(loc.filepath)
        resolved=(root/path).resolve() if not path.is_absolute() else path.resolve()
        assert resolved.is_relative_to(root)
        if not resolved.is_file():
            # Generated testing interfaces use a virtual source-root location.
            # Bind them to the real generated file rather than silently leaving
            # 1,389 declarations without any content-addressed source.
            generated=(root/a.out/'gen'/resolved.relative_to(root)).resolve(strict=True)
            assert generated.is_relative_to(root) and generated.is_file()
            resolved=generated
        key=resolved.relative_to(root).as_posix()
        if resolved.is_file() and key not in source_files:source_files[key]=sha(resolved)
        return key
    def exposure(item):
        e=getattr(item,'exposure',None)
        if e is None:return None
        return {'globals':[{'name':x.global_name,'feature':None if x.feature is None else str(x.feature)} for x in e.global_names_and_features],
                'runtime_features':list(e.runtime_enabled_features),'origin_trials':list(e.origin_trial_features),
                'context_features':list(e.context_enabled_features),'secure_context':e.only_in_secure_contexts,
                'coi_context':e.only_in_coi_contexts,'isolated_context':e.only_in_isolated_contexts,
                'coi_or_runtime_features':list(e.only_in_coi_contexts_or_runtime_enabled_features),
                'context_independent_runtime_features':list(e.context_independent_runtime_enabled_features),
                'context_dependent_runtime_features':list(e.context_dependent_runtime_enabled_features),
                'injection_mitigated_context':e.only_in_injection_mitigated_contexts}
    def type_name(value):return value.syntactic_form if value is not None else None
    groups=[('interface',db.interfaces),('mixin',db.interface_mixins),('namespace',db.namespaces),('dictionary',db.dictionaries)]
    counts={kind:len(owners) for kind,owners in groups}
    for kind,owners in groups:
        for owner in sorted(owners,key=lambda x:str(x.identifier)):
            name=str(owner.identifier)
            inherited=getattr(owner,'inherited',None)
            types.append({'name':name,'kind':kind,'inherited':str(inherited.identifier) if inherited else None,'source':location(owner),'annotations':owner.extended_attributes.syntactic_form,'exposure':exposure(owner)})
            for member_kind,field in [('attribute','attributes'),('operation','operations'),('constructor','constructors'),('constant','constants'),('dictionary_member','own_members')]:
                for member in getattr(owner,field,()):
                    args=[{'name':str(x.identifier),'type':type_name(x.idl_type),'optional':x.is_optional} for x in getattr(member,'arguments',())]
                    row={'owner':name,'owner_kind':kind,'kind':member_kind,'name':str(member.identifier) if member.identifier is not None else None,
                         'type':type_name(getattr(member,'idl_type',getattr(member,'return_type',None))),'arguments':args,
                         'static':bool(getattr(member,'is_static',member_kind=='constant')),'readonly':bool(getattr(member,'is_readonly',False)),
                         'source':location(member),'annotations':member.extended_attributes.syntactic_form,'exposure':exposure(member),'review_status':'unclassified'}
                    row['id']=hashlib.sha256(json.dumps({k:v for k,v in row.items() if k!='review_status'},sort_keys=True,separators=(',',':')).encode()).hexdigest();members.append(row)
    assert sha(database)==before,'IDL database changed during inventory'
    assert len({m['id'] for m in members})==len(members),'Duplicate catalog IDs require explicit overload handling'
    receipt=root/a.out/'metabrowser-privacy/receipt.json';build=json.loads(receipt.read_text())
    output={'kind':'generated-Blink-potential-surface-catalog','schema_version':1,'target':'154.0.8037.97/mac-arm64','database_sha256':before,'build_receipt_sha256':sha(receipt),'framework_sha256':build['framework_sha256'],
            'scope':'Interfaces/mixins/namespaces and returned/input dictionary fields. Includes runtime-disabled declarations. Does not cover V8 internals/network protocols or prove runtime exposure/mitigation.',
            'counts':dict(counts,types=len(types),members=len(members),source_files=len(source_files)),'types':types,'members':members,'source_sha256':source_files,'privacy_coverage_proven':False,'paid_model_calls':0}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    import os,tempfile
    fd,tmp=tempfile.mkstemp(prefix=a.output.name+'.',dir=a.output.parent)
    try:
        with os.fdopen(fd,'w') as f:json.dump(output,f,sort_keys=True,separators=(',',':'))
        os.replace(tmp,a.output)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    print(json.dumps({'written':str(a.output),'counts':output['counts'],'privacy_coverage_proven':False}))


if __name__=='__main__':main()
