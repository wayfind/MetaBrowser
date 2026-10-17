#!/usr/bin/env python3
"""Stage native per-binding storage capacity privacy; preserve actual enforcement."""
import argparse
import hashlib
import json
from pathlib import Path
import re

MARKER='METABROWSER_STORAGE_PRIVACY_V1: '


def make_plan(root):
    before,after={},{}
    def read(path):
        p=root/path
        assert not p.is_symlink() and p.resolve().is_relative_to(root)
        if path not in before:before[path]=p.read_text();after[path]=before[path]
        return after[path]
    def edit(path,old,new,tag,previous=None):
        text=read(path);marker=('# ' if path.endswith('.gn') else '// ')+MARKER+tag+'\n'
        value=marker+new
        if marker in text:
            if text.count(value)==1 and text.count(marker)==1:return
            previous_values=(previous,) if isinstance(previous,str) else (previous or ())
            for prior in previous_values:
                if text.count(marker+prior)==1 and text.count(marker)==1:
                    after[path]=text.replace(marker+prior,value,1)
                    return
            assert text.count(marker)==text.count(value)==1,(path,tag,'patch drift')
            return
        assert text.count(old)==1,(path,tag,'source drift')
        after[path]=text.replace(old,value,1)
    def include(path,line):
        text=read(path)
        if line in text.splitlines():assert text.splitlines().count(line)==1;return
        anchor=next(s for s in text.splitlines() if s.startswith('#include "'))
        edit(path,anchor,anchor+'\n'+line,'include-'+line.split('/')[-1])

    path='content/browser/renderer_host/render_process_host_impl.cc'
    edit(path,'''  storage_partition_impl_->GetQuotaContext()->BindQuotaManagerHost(
      storage_key, std::move(receiver));''', '''  const bool protected_identity = GetContentClient()->browser()
      ->GetMetaBrowserPrivacyToken(
          GetBrowserContext(), storage_key, storage_partition_impl_->GetConfig(),
          url::Origin::Create(storage_key.CopyWithForceEnabledThirdPartyStoragePartitioning()
                                  .top_level_site().GetURL())).has_value();
  storage_partition_impl_->GetQuotaContext()->BindQuotaManagerHost(
      storage_key, std::move(receiver), protected_identity);''','quota-owner-policy')
    path='content/browser/browser_interface_binders.cc'
    edit(path,'''  RenderFrameHostImpl::From(host)
      ->GetStoragePartition()
      ->GetQuotaContext()
      ->BindQuotaManagerHost(host->GetStorageKey(), std::move(receiver));''',
         '''  auto* partition = RenderFrameHostImpl::From(host)->GetStoragePartition();
  const bool protected_identity = GetContentClient()->browser()
      ->GetMetaBrowserPrivacyToken(
          host->GetBrowserContext(), host->GetStorageKey(), partition->GetConfig(),
          host->GetOutermostMainFrame()->GetLastCommittedOrigin()).has_value();
  partition->GetQuotaContext()->BindQuotaManagerHost(
      host->GetStorageKey(), std::move(receiver), protected_identity);''',
         'frame-quota-owner-policy')
    path='content/browser/quota/quota_context.h'
    for name in ('BindQuotaManagerHost','BindQuotaManagerHostOnIOThread'):
        old=f'''  void {name}(
      const blink::StorageKey& storage_key,
      mojo::PendingReceiver<blink::mojom::QuotaManagerHost> receiver);'''
        edit(path,old,old.replace('receiver);','receiver,\n      bool protected_identity = false);'),name+'-policy')
    path='content/browser/quota/quota_context.cc'
    for name in ('BindQuotaManagerHost','BindQuotaManagerHostOnIOThread'):
        old=f'''void QuotaContext::{name}(
    const blink::StorageKey& storage_key,
    mojo::PendingReceiver<blink::mojom::QuotaManagerHost> receiver) {{'''
        edit(path,old,old.replace('receiver) {','receiver,\n    bool protected_identity) {'),name+'-policy')
    edit(path,'this, storage_key, std::move(receiver)));',
         'this, storage_key, std::move(receiver), protected_identity));','io-policy-copy')
    edit(path,'std::make_unique<QuotaManagerHost>(storage_key, quota_manager_.get());',
         'std::make_unique<QuotaManagerHost>(storage_key, quota_manager_.get(), protected_identity);','host-policy-copy')
    path='content/browser/quota/quota_manager_host.h'
    old='''  QuotaManagerHost(const blink::StorageKey& storage_key,
                   storage::QuotaManager* quota_manager);'''
    edit(path,old,old.replace('quota_manager);','quota_manager,\n                   bool protected_identity = false);'),'host-policy-argument')
    anchor='  const raw_ptr<storage::QuotaManager> quota_manager_;'
    edit(path,anchor,anchor+'\n  const bool metabrowser_protected_identity_;','immutable-host-policy')
    path='content/browser/quota/quota_manager_host.cc'
    include(path,'#include "content/browser/quota/metabrowser_storage_quota.h"')
    old='''QuotaManagerHost::QuotaManagerHost(const blink::StorageKey& storage_key,
                                   storage::QuotaManager* quota_manager)
    : storage_key_(storage_key), quota_manager_(quota_manager) {'''
    edit(path,old,'''QuotaManagerHost::QuotaManagerHost(const blink::StorageKey& storage_key,
                                   storage::QuotaManager* quota_manager,
                                   bool protected_identity)
    : storage_key_(storage_key), quota_manager_(quota_manager),
      metabrowser_protected_identity_(protected_identity) {''','immutable-host-policy')
    anchor='  std::move(callback).Run(status, usage, quota, std::move(usage_breakdown));'
    edit(path,anchor,'''  if (status == blink::mojom::QuotaStatusCode::kOk &&
      metabrowser_protected_identity_) {
    quota = MetaBrowserReportedStorageQuota(usage);
  }
'''+anchor,'protect-modern-and-legacy-estimates')

    path='content/browser/buckets/bucket_host.h'
    include(path,'#include <utility>')
    old='''  void DidGetUsageAndQuota(EstimateCallback callback,
                           blink::mojom::QuotaStatusCode code,'''
    edit(path,old,old.replace('                           blink::', '                           bool protected_identity,\n                           blink::'),'bucket-policy-copy')
    anchor='  void OnReceiverDisconnected();'
    previous_owner=anchor+'\n  bool IsMetaBrowserQuotaProtected() const;'
    owner_methods=previous_owner+'''
  void ContinueMetaBrowserEstimate(EstimateCallback callback,
                                   bool protected_identity,
                                   bool bucket_exists);'''
    transitional_owner=owner_methods.replace('  bool IsMetaBrowserQuotaProtected()',
        '// '+MARKER+'bucket-fresh-quota-metadata\n  bool IsMetaBrowserQuotaProtected()')
    edit(path,anchor,owner_methods,'bucket-owner-policy',previous=(previous_owner,transitional_owner))
    old='''  mojo::ReceiverSet<blink::mojom::BucketHost, base::WeakPtr<BucketContext>>
      receivers_;'''
    edit(path,old,'''  // Each binding freezes its own policy; a shared host must not give a
  // newly bound receiver another receiver's protection setting.
  mojo::ReceiverSet<blink::mojom::BucketHost,
                    std::pair<base::WeakPtr<BucketContext>, bool>> receivers_;''','per-binding-bucket-policy')
    path='content/browser/buckets/bucket_host.cc'
    for line in ('#include "content/browser/quota/metabrowser_storage_quota.h"',
                 '#include "content/public/browser/content_browser_client.h"',
                 '#include "content/public/common/content_client.h"'):
        include(path,line)
    # The first tuple entry remains the original weak context, including every
    # existing permission and post-owner-destruction check.
    text=read(path);tag='// '+MARKER+'receiver-context-access\n'
    if tag not in text:
        assert text.count('receivers_.current_context()')==6,'Bucket context access drift'
        after[path]=tag+text.replace('receivers_.current_context()','receivers_.current_context().first')
    else:
        assert text.count(tag)==1
        assert not re.search(r'receivers_\.current_context\(\)(?!\.first|\.second)',text)
    for old in ('receivers_.Add(this, remote.InitWithNewPipeAndPassReceiver(), bucket_context);',
                'receivers_.Add(this, std::move(receiver), bucket_context);'):
        edit(path,old,old.replace('bucket_context);','std::make_pair(bucket_context, IsMetaBrowserQuotaProtected()));'),
             'bind-'+('created' if 'remote.' in old else 'passed'))
    anchor='BucketHost::~BucketHost() = default;'
    edit(path,anchor,anchor+'''

bool BucketHost::IsMetaBrowserQuotaProtected() const {
  auto* partition = bucket_manager_host_->GetStoragePartition();
  const auto& key = bucket_manager_host_->storage_key();
  return GetContentClient()->browser()->GetMetaBrowserPrivacyToken(
      partition->browser_context(), key, partition->GetConfig(),
      url::Origin::Create(key.CopyWithForceEnabledThirdPartyStoragePartitioning()
                             .top_level_site().GetURL())).has_value();
}''','bucket-owner-policy')
    # Estimate lives in this browser-side host, not in renderer JavaScript.
    old='''      base::BindOnce(&BucketHost::DidGetUsageAndQuota,
                     weak_factory_.GetWeakPtr(), std::move(callback)));'''
    edit(path,old,old.replace('std::move(callback)))','std::move(callback),\n                     protected_identity))'),'bucket-policy-at-request',
         previous=old.replace('std::move(callback)))','std::move(callback),\n                     receivers_.current_context().second))'))
    old_estimate='''void BucketHost::Estimate(EstimateCallback callback) {
  if (bucket_info_.is_null()) {
    std::move(callback).Run({}, {}, /*success=*/false);
    return;
  }

  GetQuotaManagerProxy()->GetBucketUsageAndReportedQuota(
      bucket_id_, base::SequencedTaskRunner::GetCurrentDefault(),
// METABROWSER_STORAGE_PRIVACY_V1: bucket-policy-at-request
      base::BindOnce(&BucketHost::DidGetUsageAndQuota,
                     weak_factory_.GetWeakPtr(), std::move(callback),
                     protected_identity));
}

'''
    query_start=old_estimate.index('  GetQuotaManagerProxy()->GetBucketUsageAndReportedQuota(')
    new_estimate=old_estimate[:query_start]+'''  const bool protected_identity = receivers_.current_context().second;
  if (!protected_identity) {
    ContinueMetaBrowserEstimate(std::move(callback), false, true);
    return;
  }
  // BucketInfo is only a snapshot. Fetch current persisted policy before
  // reporting an app-authored cap; open() itself does not change existing quota.
  GetQuotaManagerProxy()->GetBucketById(
      bucket_id_, base::SequencedTaskRunner::GetCurrentDefault(),
      base::BindOnce(&BucketHost::DidGetBucket, weak_factory_.GetWeakPtr(),
          base::BindOnce(&BucketHost::ContinueMetaBrowserEstimate,
              weak_factory_.GetWeakPtr(), std::move(callback), protected_identity)));
}

void BucketHost::ContinueMetaBrowserEstimate(EstimateCallback callback,
                                            bool protected_identity,
                                            bool bucket_exists) {
  if (!bucket_exists) {
    std::move(callback).Run({}, {}, /*success=*/false);
    return;
  }
'''+old_estimate[query_start:]
    prior_estimate=new_estimate.replace(
        '  // BucketInfo is only a snapshot. Fetch current persisted policy before\n'
        '  // reporting an app-authored cap; open() itself does not change existing quota.',
        '  // BucketInfo is only a snapshot. Fetch current app-authored policy before\n'
        '  // reporting it; reopening a bucket can change the quota in the database.')
    edit(path,old_estimate,new_estimate,'refresh-bucket-policy-before-estimate',previous=prior_estimate)
    old='''void BucketHost::DidGetUsageAndQuota(EstimateCallback callback,
                                     blink::mojom::QuotaStatusCode code,'''
    edit(path,old,old.replace('                                     blink::','                                     bool protected_identity,\n                                     blink::'),'bucket-policy-callback')
    anchor='''  std::move(callback).Run(usage, quota,
                          code == blink::mojom::QuotaStatusCode::kOk);'''
    edit(path,anchor,'''  if (code == blink::mojom::QuotaStatusCode::kOk && protected_identity) {
    // Explicit caps are authored by the website, not derived from the device.
    quota = bucket_info_.quota > 0 ? bucket_info_.quota
                                  : MetaBrowserReportedStorageQuota(usage);
  }
'''+anchor,'protect-implicit-bucket-capacity')
    path='components/services/storage/public/cpp/buckets/bucket_init_params.h'
    anchor='  int64_t quota = 0;'
    edit(path,anchor,anchor+'''

  // Browser-authored policy only; never received from renderer bucket options,
  // serialized into origin data, or used to grant additional writable bytes.
  bool metabrowser_protected_identity = false;''','bucket-count-policy-carrier')
    path='content/browser/buckets/bucket_manager_host.cc'
    for line in ('#include "content/public/browser/content_browser_client.h"',
                 '#include "content/public/common/content_client.h"'):
        include(path,line)
    anchor='  storage::BucketInitParams params(storage_key_, name);'
    edit(path,anchor,anchor+'''
  auto* partition = GetStoragePartition();
  params.metabrowser_protected_identity = GetContentClient()->browser()
      ->GetMetaBrowserPrivacyToken(
          partition->browser_context(), storage_key_, partition->GetConfig(),
          url::Origin::Create(storage_key_.CopyWithForceEnabledThirdPartyStoragePartitioning()
                                 .top_level_site().GetURL())).has_value();''',
         'browser-owned-bucket-count-policy')
    path='storage/browser/quota/quota_manager_impl.cc'
    anchor='''  CHECK_EQ(max_buckets == 0, IsStorageUnlimited(bucket_params.storage_key));'''
    edit(path,anchor,'''  if (bucket_params.metabrowser_protected_identity && quota != kNoLimit) {
    // Use the same public 10 GiB cohort as estimates rather than private
    // physical capacity. Keep unlimited grants and byte enforcement native.
    max_buckets = (10 * kGBytes) / kTypicalBucketUsage;
  }
'''+anchor,'capacity-independent-bucket-count')
    # A full data pipe can be closed by the backend's quota failure before its
    # Mojo result reaches the renderer. Preserve the backend error instead of
    # exposing whichever of the producer/backend callbacks happened to win.
    path='third_party/blink/renderer/modules/file_system_access/file_system_underlying_sink.cc'
    include(path,'#include "mojo/public/cpp/bindings/callback_helpers.h"')
    edit(path,'''    if (!producer_result_.is_null() &&
        producer_result_->status != mojom::blink::FileSystemAccessStatus::kOk) {''',
         '''    // A producer failure can be a consequence of a backend failure
    // (for example, quota closes the consumer's data pipe). Wait for the
    // authoritative write result; the default callback below also settles a
    // disconnected writer. A successful backend still preserves producer errors.
    if (!producer_result_.is_null() &&
        producer_result_->status != mojom::blink::FileSystemAccessStatus::kOk &&
        !write_result_.is_null() &&
        write_result_->status == mojom::blink::FileSystemAccessStatus::kOk) {''',
         'opfs-authoritative-write-error')
    edit(path,'''  writer_remote_->Write(
      position, std::move(consumer_handle),
      blink::BindOnce(&WriterHelper::WriteComplete, helper->AsWeakPtr()));''',
         '''  writer_remote_->Write(
      position, std::move(consumer_handle),
      mojo::WrapCallbackWithDefaultInvokeIfNotRun(
          blink::BindOnce(&WriterHelper::WriteComplete, helper->AsWeakPtr()),
          mojom::blink::FileSystemAccessError::New(
              mojom::blink::FileSystemAccessStatus::kOperationAborted,
              base::File::FILE_OK, "File writer disconnected"),
          uint64_t{0}));''',
         'opfs-disconnect-completion')
    path='content/browser/BUILD.gn'
    anchor='    "quota/quota_manager_host.h",'
    edit(path,anchor,anchor+'\n    "quota/metabrowser_storage_quota.h",','quota-helper-owner')
    path='content/browser/quota/metabrowser_storage_quota.h'
    p=root/path;before[path]=p.read_text() if p.exists() else None
    after[path]=(Path(__file__).resolve().parents[1]/'chromium/privacy/metabrowser_storage_quota.h').read_text()
    return before,after


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('--apply',action='store_true')
    args=p.parse_args();root=args.source.resolve(strict=True)
    assert (root/'chrome/VERSION').read_text().splitlines()==['MAJOR=154','MINOR=0','BUILD=8037','PATCH=97']
    before,after=make_plan(root)
    changed=[f for f in after if before[f]!=after[f]]
    for f in after:assert ((root/f).read_text() if (root/f).exists() else None)==before[f],'Source changed during preflight'
    if args.apply:
        for f in changed:(root/f).write_text(after[f])
    print(json.dumps({'applied':args.apply,'changed':changed,'all_files':{f:hashlib.sha256(s.encode()).hexdigest() for f,s in after.items()}},indent=2))


if __name__=='__main__':main()
