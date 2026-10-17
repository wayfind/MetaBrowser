"""Actual SDK keyless local Skill discovery (OAuth has its own contract test)."""
import ctypes,json,os,pathlib,tempfile
lib=ctypes.CDLL(str(pathlib.Path(os.environ.get('METABROWSER_HOST_TEST_PLUGIN', 'zig-out/lib/libmetabrowser_metacodes.dylib')).resolve()))
event_type=ctypes.CFUNCTYPE(None,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint64)
lib.mb_mc_login.argtypes=[ctypes.c_char_p,event_type,ctypes.c_void_p];lib.mb_mc_login.restype=ctypes.c_uint32
lib.mb_mc_control.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_char_p,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(ctypes.c_uint64)]
lib.mb_mc_free.argtypes=[ctypes.c_void_p,ctypes.c_uint64]
with tempfile.TemporaryDirectory(prefix='metabrowser-account-') as work:
    home=pathlib.Path(work);workspace=home/'workspace';workspace.mkdir()
    # A tiny standard local skill proves actual SDK parsing, not a fabricated UI list.
    skill=workspace/'.agents/skills/test-local';skill.mkdir(parents=True)
    (skill/'SKILL.md').write_text('---\nname: test-local\ndescription: Local fixture skill for native catalogue acceptance.\n---\nRead the current workspace.\n')
    out=ctypes.c_void_p();length=ctypes.c_uint64()
    assert lib.mb_mc_control(None,b'skills_catalog',json.dumps({'workspace':str(workspace),'home':str(home)}).encode(),ctypes.byref(out),ctypes.byref(length))==0
    catalogue=json.loads(ctypes.string_at(out,length.value));lib.mb_mc_free(out,length)
    assert any(s['invocation_name']=='test-local' for s in catalogue['skills']),catalogue
print('PASS: keyless SDK local Skill discovery')
