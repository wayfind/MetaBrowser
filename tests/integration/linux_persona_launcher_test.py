"""Protect test backend activation from conflicting flags or argument terminators."""
from linux_persona_launcher import FLAGS,renderer_arguments

base=['--type=renderer','--field-trial-handle=17','--','literal']
result=renderer_arguments(base)
assert result[-2:]==['--','literal']
assert all(result.index(flag)<result.index('--') for flag in FLAGS)
assert renderer_arguments(result)==result
rejected=0
for args in [[],['--type=zygote'],['--type=renderer','--user-agent=custom'],
             ['--type=renderer','--use-angle=metal'],
             ['--type=renderer','--metabrowser-persona-template=native-macos-arm64-v1'],
             ['--type=renderer','--use-gl=angle','--use-gl=angle'],
             ['--','--type=renderer'],['--type=renderer','--type=utility'],
             ['--type=renderer','--type=renderer']]:
 try:renderer_arguments(args)
 except AssertionError:rejected+=1
 else:raise AssertionError(args)
assert rejected==9
print('Renderer transport: terminator preservation/idempotence and nine conflicts passed')
