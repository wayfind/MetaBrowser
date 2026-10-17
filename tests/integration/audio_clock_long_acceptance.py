"""Validate real silence-transition trace plus graph lifecycle in a muted browser."""
import argparse,hashlib,json,math
from pathlib import Path


def verify(data):
 assert data['closedContexts']==1 and data['frozen'] is True
 assert data['microphoneRequested'] is False and data['browserMuteRequired'] is True
 rows=data['rows'];assert len(rows)==36
 assert [r['phase'] for r in rows]==['start']+['silent']*33+['signal','resumed']
 for row in rows:
  assert row['state']=='running'
  for key in ('currentTime','contextTime','performanceTime','performanceNow','baseLatency','outputLatency','rms'):
   assert type(row[key]) in (int,float) and math.isfinite(row[key]) and row[key]>=0
  assert row['contextTime']<=row['currentTime']+1e-9
  assert math.isclose(row['baseLatency'],256/48000,rel_tol=0,abs_tol=1e-12)
  if row['phase']!='start':assert row['outputLatency']==.008
  if row['phase']=='silent':assert row['rms']==0
  if row['phase'] in ('signal','resumed'):assert .12<row['rms']<.16
 for earlier,later in zip(rows,rows[1:]):
  for key in ('currentTime','contextTime','performanceTime','performanceNow'):assert later[key]>=earlier[key]
 wall=(rows[-1]['performanceNow']-rows[0]['performanceNow'])/1000
 elapsed=rows[-1]['currentTime']-rows[0]['currentTime']
 assert wall>=33 and 32<elapsed<=wall+1
 transitions=data['silenceTransitions'];assert len(transitions)==2
 for event,suffix in zip(transitions,('Start()','Stop()')):
  assert event['name']=='SilentSinkSuspender::TransitionSinks - fake_sink_.'+suffix and event['phase']=='I'
  assert type(event['ts']) in (int,float) and math.isfinite(event['ts'])
 assert 0<transitions[1]['ts']-transitions[0]['ts']<10e6
 return {'actual_native_silence_transitions':2,'observed_rows':36,'elapsed_graph_seconds':elapsed,
         'paused_clock_frozen':True,'browser_muted':True,'real_hardware_playback_verified':False,'full_scope_complete':False}


def accept(report,archive):
 assert report['completed'] is True and report['clean_shutdown'] is True and not report.get('error')
 assert report['probe_kind']=='audio-clock-long' and report['paid_model_calls']==0
 assert report['requested_audio_muted'] is True and '--mute-audio' in report['command']
 assert (archive/'.metabrowser-owned-fixture').read_text()=='persona-metadata'
 raw=json.loads((archive/'probe-process.private.json').read_text());assert raw['exit_code']==0 and json.loads(raw['stdout'])==report['observations']
 for name,want in report['probe_sha256'].items():assert hashlib.sha256((archive/'inputs'/Path(name).name).read_bytes()).hexdigest()==want
 return verify(report['observations'])


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path);p.add_argument('--archive',type=Path,required=True);a=p.parse_args()
 print(json.dumps(accept(json.loads(a.report.read_text()),a.archive),indent=2))
