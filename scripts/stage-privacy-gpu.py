#!/usr/bin/env python3
"""Allow only an explicitly selected bundled SwiftShader CPU adapter.

Retains normal WebGPU safety level, shader validation and all other blocklist
reasons. Does not enable unsafe or experimental APIs or fake hardware IDs.
"""
import argparse
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=Path)
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()
root = args.source.resolve(strict=True)
assert (root / 'chrome/VERSION').read_text().splitlines() == ['MAJOR=154', 'MINOR=0', 'BUILD=8037', 'PATCH=97']
relative = 'gpu/command_buffer/service/webgpu_decoder_impl.cc'
path = root / relative
assert not path.is_symlink()
text = path.read_text()
old = '''    if (use_blocklist() && IsWebGPUAdapterBlocklisted(adapter).blocked) {
      return false;
    }

    const bool is_swiftshader =
        adapter_info.adapterType == wgpu::AdapterType::CPU &&
        adapter_info.vendorID == 0x1AE0 && adapter_info.deviceID == 0xC0DE;'''
new = '''    // METABROWSER_SOFTWARE_GPU_V1: a real software adapter, never a fake GPU.
    const bool is_swiftshader =
        adapter_info.adapterType == wgpu::AdapterType::CPU &&
        adapter_info.vendorID == 0x1AE0 && adapter_info.deviceID == 0xC0DE;
    WebGPUBlocklistOptions metabrowser_blocklist_options;
    if (is_swiftshader &&
        use_webgpu_adapter_ == WebGPUAdapterName::kSwiftShader) {
      // Exempt only the CPU-adapter policy for the explicitly selected bundled
      // backend. Other driver/string blocklists and WGSL safety stay enabled.
      metabrowser_blocklist_options.ignores = WebGPUBlocklistReason::CPUAdapter;
    }
    if (use_blocklist() &&
        IsWebGPUAdapterBlocklisted(adapter, metabrowser_blocklist_options).blocked) {
      return false;
    }'''
if new not in text:
    if text.count(old) != 1 or 'METABROWSER_SOFTWARE_GPU_V1' in text:
        raise SystemExit('Pinned WebGPU adapter selection drift')
    updated = text.replace(old, new, 1)
else:
    assert text.count(new) == 1
    updated = text
if args.apply and updated != text:
    path.write_text(updated)
print(json.dumps({'scope': 'explicit-swiftshader-only-cpu-policy-exemption', 'applied': args.apply,
                  'files': {relative: hashlib.sha256(updated.encode()).hexdigest()}}))
