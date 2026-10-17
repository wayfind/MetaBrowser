"""Compare same-patch owned offline audio fixtures; never assert full privacy."""
import argparse
import hashlib
import json
from pathlib import Path
from audio_vector_acceptance import verify_graphs as vector_graphs
from audio_fft_acceptance import verify_graphs as fft_graphs
from audio_compressor_acceptance import verify_graphs as compressor_graphs
from audio_resampler_acceptance import verify_graphs as resampler_graphs
from audio_signature_acceptance import verify_graphs as signature_graphs
from audio_hrtf_acceptance import verify as hrtf_graphs,verify_trace as hrtf_trace
from audio_worklet_acceptance import verify as worklet_graphs
from audio_hrtf_dynamic_acceptance import verify as dynamic_hrtf_graphs
from audio_biquad_matrix_acceptance import verify as biquad_matrix_graphs
from audio_biquad_boundary_acceptance import verify as biquad_boundary_graphs
from linux_persona_launcher import FLAGS,renderer_arguments
from patched_linux_audio_runner import attest_proc_arguments

CHECKERS={'audio-vector':vector_graphs,'audio-fft':fft_graphs,'audio-compressor':compressor_graphs,'audio-resampler':resampler_graphs,'audio-signature':signature_graphs,'audio-hrtf':hrtf_graphs,'audio-worklet':worklet_graphs,'audio-hrtf-dynamic':dynamic_hrtf_graphs,'audio-biquad-matrix':biquad_matrix_graphs,'audio-biquad-boundary':biquad_boundary_graphs}
KEYS={'audio-biquad-boundary':('rate','type','boundary','repeat'),'audio-biquad-matrix':('rate','type','automation','repeat'),'audio-vector':('rate','kind','repeat'),'audio-fft':('kind','rate','size','repeat'),
      'audio-compressor':('rate','setting','signal','repeat'),'audio-resampler':('sourceRate','destRate','frames','signal','repeat'),'audio-signature':('variant','rate','repeat'),'audio-hrtf':('rate','direction','signal','repeat'),'audio-worklet':('rate','kind','repeat'),'audio-hrtf-dynamic':('rate','motion','scale','repeat')}

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def validate_capture(report,raw_root,probe_dir,marker):
    assert report['completed'] is True and report['clean_shutdown'] is True and not report.get('error')
    assert type(report['paid_model_calls']) is int and report['paid_model_calls']==0
    assert report['full_scope_complete'] is False
    root=Path(raw_root or report['root']).resolve(strict=True)
    assert (root/'.metabrowser-owned-fixture').read_text()==marker
    raw=json.loads((root/'probe-process.private.json').read_text())
    assert raw['exit_code']==0 and json.loads(raw['stdout'])==report['observations']
    for name,want in report['probe_sha256'].items():
        source=Path(probe_dir)/Path(name).name if probe_dir else Path(name)
        assert sha(source)==want,name
    return root


def row_hashes(row):
    if 'channels' in row:return tuple(channel['sha256'] for channel in row['channels'])
    if row.get('kind')=='analyser':return (row['timeHash'],row['frequencyHash'],row['byteHash'])
    return (row['sha256'],)


def compare(mac,linux,mac_receipt,linux_receipt,mac_receipt_digest,linux_receipt_digest,
            mac_raw_root=None,linux_raw_root=None,mac_probe_dir=None,linux_probe_dir=None):
    kind=mac['probe_kind'];assert kind in CHECKERS and linux['probe_kind']==kind
    assert mac['persona']=='linux-x86_64-software-v1' and mac['privacy']=='off'
    assert linux['backend']=='scalar' and linux['requested_privacy']=='off'
    assert linux_receipt['state']=='build-complete' and linux_receipt['target']=='headless_shell'
    assert linux['engine_sha256']==linux_receipt['binary_sha256']
    assert linux['build_receipt_sha256']==linux_receipt_digest
    assert mac['framework_sha256']==mac_receipt['framework_sha256']==linux['parent_mac_framework_sha256']==linux_receipt['parent_mac_framework_sha256']
    assert linux_receipt['parent_receipt_sha256']==mac_receipt_digest
    expected={name:value for name,value in mac_receipt['sources'].items() if not name.startswith('out/')}
    assert expected and linux_receipt['source_sha256']==expected
    validate_capture(mac,mac_raw_root,mac_probe_dir,'persona-metadata')
    linux_root=validate_capture(linux,linux_raw_root,linux_probe_dir,'patched-linux-audio-reference')
    records=linux['renderer_transport'];assert records
    for record in records:
        launch=json.loads((linux_root/Path(record['launch_record']).name).read_text())
        args=record['actual_arguments'];assert launch['pid']==record['pid'] and launch['arguments']==args[1:]
        expected_exe=str(Path(linux_receipt['source'])/'out/metabrowser-linux-reference/headless_shell')
        assert args[0]==launch['binary']==expected_exe
        canonical,representation=attest_proc_arguments(record['raw_proc_arguments'],expected_exe,launch['arguments'])
        assert canonical==args and representation==record['cmdline_representation']
        assert renderer_arguments(args[1:])==args[1:]
        switches=args[1:args.index('--')] if '--' in args else args[1:]
        assert '--type=renderer' in switches and all(flag in switches for flag in FLAGS)
    trial=kind.replace('-','_')+'_trial.js'
    def trial_digest(report):
        matches=[value for name,value in report['probe_sha256'].items() if Path(name).name==trial]
        assert len(matches)==1;return matches[0]
    assert trial_digest(mac)==trial_digest(linux)
    CHECKERS[kind](mac['observations']);CHECKERS[kind](linux['observations'])
    if kind=='audio-hrtf':
        hrtf_trace(mac['observations'],True);hrtf_trace(linux['observations'],True)
    fields=KEYS[kind]
    def keyed(report):
        rows=report['observations']['rows'];mapping={tuple(row.get(k) for k in fields):row for row in rows}
        assert len(mapping)==len(rows);return mapping
    left,right=keyed(mac),keyed(linux);assert left.keys()==right.keys()
    mismatches=[];response_mismatches=[];total=equal=0
    for key,a in left.items():
        b=right[key]
        if kind=='audio-biquad-matrix' and a['response']!=b['response']:
            response_mismatches.append({'case':dict(zip(fields,key)),'mac':a['response'],'linux':b['response']})
        if kind=='audio-resampler':assert a['inputSha256']==b['inputSha256']
        ah,bh=row_hashes(a),row_hashes(b);assert len(ah)==len(bh)
        total+=len(ah);equal+=sum(x==y for x,y in zip(ah,bh))
        if ah!=bh:mismatches.append({'case':dict(zip(fields,key)),'mac':ah,'linux':bh})
    return {'probe_kind':kind,'fixture_buffers_identical':not mismatches and not response_mismatches,'functional_checks_passed':True,
            'frequency_response_float32_buffers_equal':not response_mismatches if kind=='audio-biquad-matrix' else None,
            'frequency_response_mismatches':response_mismatches,
            'hashes_compared':total,'hashes_equal':equal,'mismatches':mismatches,
            'mac_framework_sha256':mac['framework_sha256'],'linux_engine_sha256':linux['engine_sha256'],
            'same_patch_source_binding_verified':True,'full_pipeline_cross_cpu_proven':False,'full_scope_complete':False,
            'scope':'Finite Window offline fixtures, Mac GUI vs Linux headless/sandbox-disabled. Equal buffer digests do not cover every API/value/device/realm or complete privacy.'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('mac','linux','mac-receipt','linux-receipt','output'):p.add_argument('--'+name,type=Path,required=True)
    for name in ('mac-raw-root','linux-raw-root','mac-probe-dir','linux-probe-dir'):p.add_argument('--'+name,type=Path)
    a=p.parse_args()
    result=compare(json.loads(a.mac.read_text()),json.loads(a.linux.read_text()),json.loads(a.mac_receipt.read_text()),json.loads(a.linux_receipt.read_text()),sha(a.mac_receipt),sha(a.linux_receipt),a.mac_raw_root,a.linux_raw_root,a.mac_probe_dir,a.linux_probe_dir)
    result['captures']={str(path):sha(path) for path in [a.mac,a.linux,a.mac_receipt,a.linux_receipt]}
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ('mismatches','captures')}))
    raise SystemExit(0 if result['fixture_buffers_identical'] else 1)
