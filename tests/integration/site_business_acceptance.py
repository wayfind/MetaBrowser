"""Read-only public website workflows through agent-browser and an owned app.

Login gates and incomplete playback are evidence, never success. No SDK,
credentials, account migration, orders, messages or CAPTCHA interactions.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request
import urllib.parse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--gpu', choices=('native', 'software'), default='software')
    parser.add_argument('--site', action='append', choices=('xiaohongshu', 'taobao', 'tmall', '1688', 'bilibili'))
    args = parser.parse_args()
    app = args.app.resolve(strict=True)
    assert not (app / 'Contents/Frameworks/libmetabrowser_metacodes.dylib').exists()
    assert not (app / 'Contents/Resources/agentcore').exists()
    with socket.socket() as sock:
        # Allow a completed run's TIME_WAIT sockets, but not a live listener.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('127.0.0.1', 18855))
    root = Path(tempfile.mkdtemp(prefix='metabrowser-site-business-'))
    env = {k: v for k, v in os.environ.items() if k in ('HOME', 'PATH', 'USER', 'LOGNAME', 'LANG', 'LC_CTYPE', 'TMPDIR', 'SHELL', '__CF_USER_TEXT_ENCODING')}
    env.update(METABROWSER_IDENTITY_HOME=str(root / 'identities'), METABROWSER_ACCOUNT_HOME=str(root / 'account'), METABROWSER_CONVERSATION_HOME=str(root / 'conversations'), METABROWSER_WORKSPACE=str(root / 'workspace'))
    session = 'metabrowser-business-' + root.name.rsplit('-', 1)[-1]
    framework = app / 'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'
    with framework.open('rb') as stream:
        framework_sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
    report = {'app': str(app), 'root': str(root), 'gpu': args.gpu, 'requested_sites': args.site or ['xiaohongshu', 'taobao', 'tmall', '1688', 'bilibili'], 'framework_sha256': framework_sha256, 'completed': False, 'paid_model_calls': 0, 'authenticated': False, 'sites': {}}
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def cli(*command):
        result = subprocess.run(['agent-browser', '--session', session, '--cdp', '18855', *command], capture_output=True, text=True, timeout=45, env=env)
        if result.returncode:
            raise RuntimeError(result.stderr.strip()[:1000])
        return result.stdout

    def snapshot(name):
        text = cli('snapshot', '-i', '-c')
        path = args.output.with_name(args.output.stem + '-' + name + '.txt')
        path.write_text(text)
        path.chmod(0o600)
        return text

    def evaluate(code):
        value = json.loads(cli('eval', '(async()=>JSON.stringify(await (' + code + ')))()'))
        return json.loads(value) if isinstance(value, str) else value

    def navigate(url):
        cli('open', url)
        time.sleep(2)

    def public_url(url):
        parsed = urllib.parse.urlsplit(url)
        # Login redirects can carry transient session/risk parameters. Only
        # host/path are needed to explain an observed navigation or auth gate.
        return urllib.parse.urlunsplit((parsed.scheme, parsed.hostname or '', parsed.path, '', ''))

    flags = ['--use-gl=angle', '--use-angle=swiftshader', '--use-webgpu-adapter=swiftshader',
             '--disable-accelerated-video-decode', '--disable-accelerated-video-encode'] if args.gpu == 'software' else []
    with (root / 'browser.log').open('w') as log:
        process = subprocess.Popen([str(app / 'Contents/MacOS/Chromium'), '--user-data-dir=' + str(root / 'browser'), '--remote-debugging-port=18855', '--use-mock-keychain', '--no-first-run', '--no-default-browser-check', '--disable-component-update', *flags, 'about:blank'], env=env, stdout=log, stderr=log, start_new_session=True)
        try:
            for _ in range(150):
                assert process.poll() is None
                try:
                    urllib.request.urlopen('http://127.0.0.1:18855/json/version', timeout=.2).close()
                    break
                except OSError:
                    time.sleep(.1)
            for site, url in (
                ('xiaohongshu', 'https://www.xiaohongshu.com/explore'),
                ('taobao', 'https://s.taobao.com/search?q=' + urllib.parse.quote('机械键盘')),
                ('tmall', 'https://list.tmall.com/search_product.htm?q=' + urllib.parse.quote('机械键盘')),
                ('1688', 'https://s.1688.com/selloffer/offer_search.htm?keywords=%BB%FA%D0%B5%BC%FC%C5%CC'),
                ('bilibili', 'https://search.bilibili.com/all?keyword=' + urllib.parse.quote('网页游戏攻略')),
            ):
                if args.site and site not in args.site:
                    continue
                result = {'status': 'incomplete', 'steps': []}
                report['sites'][site] = result
                try:
                    navigate(url)
                    if site in ('1688', 'bilibili'):
                        selector = 'a[href*="detail.1688.com/offer/"],input[type="password"]' if site == '1688' else 'a[href*="bilibili.com/video/BV"],input[type="password"]'
                        readiness = evaluate("(async()=>{const end=performance.now()+10000;while(performance.now()<end){if(document.querySelector(" + json.dumps(selector) + "))return true;await new Promise(r=>setTimeout(r,200))}return false})()")
                        result['semantic_readiness_observed'] = readiness is True
                    text = snapshot(site + '-search')
                    result['steps'].append({'navigation': True, 'final_url': public_url(evaluate('location.href')), 'interactive_entries': len(text.splitlines())})
                    if site == '1688':
                        links = evaluate("Array.from(document.querySelectorAll('a[href]')).map(a=>a.href).filter(u=>/^https?:\\/\\/detail\\.1688\\.com\\/offer\\/\\d+\\.html/.test(u))")
                        if not links:
                            result['status'] = 'requires_login' if '账号名/邮箱/手机号' in text or '密码登录' in text else 'no_product_results'
                            continue
                        result['steps'].append({'search_product_links': len(set(links))})
                        parsed = urllib.parse.urlsplit(links[0])
                        assert parsed.hostname == 'detail.1688.com'
                        navigate('https://detail.1688.com' + parsed.path)
                        detail = snapshot(site + '-detail')
                        result['steps'].append({'detail_url': public_url(evaluate('location.href')), 'supplier_visible': '有限公司' in detail, 'parameters_visible': '参数' in detail})
                        result['status'] = 'passed_public_search_detail' if '有限公司' in detail and '参数' in detail else 'incomplete_detail'
                    elif site == 'bilibili':
                        links = evaluate("Array.from(document.querySelectorAll('a[href]')).map(a=>a.href).filter(u=>/^https:\\/\\/www\\.bilibili\\.com\\/video\\/BV/.test(u))")
                        if not links:
                            result['status'] = 'no_video_results'
                            continue
                        result['steps'].append({'search_video_links': len(set(links))})
                        parsed = urllib.parse.urlsplit(links[0])
                        assert parsed.hostname == 'www.bilibili.com'
                        navigate('https://www.bilibili.com' + parsed.path)
                        snapshot(site + '-detail')
                        result['player'] = evaluate("({avc:MediaSource.isTypeSupported('video/mp4; codecs=\"avc1.640028\"'),aac:MediaSource.isTypeSupported('audio/mp4; codecs=\"mp4a.40.2\"'),unsupported:/不支持 HTML5 播放器/.test(document.body.innerText),videos:Array.from(document.querySelectorAll('video,bwp-video')).map(v=>({tag:v.tagName,ready:v.readyState,time:v.currentTime,width:v.videoWidth,height:v.videoHeight,paused:v.paused,error:v.error?.code}))})")
                        if result['player']['unsupported']:
                            result['status'] = 'failed_codec_playback'
                        else:
                            # Only a muted local playback action; never a site
                            # account action, subscription, comment or rating.
                            result['playback'] = evaluate("""(async()=>{
                              function locate(root=document,depth=0){
                                const v=root.querySelector('video,bwp-video');
                                if(v&&typeof v.play==='function')return v;
                                if(depth<6)for(const host of root.querySelectorAll('*'))if(host.shadowRoot){const nested=locate(host.shadowRoot,depth+1);if(nested)return nested}
                              }
                              const end=performance.now()+9000;
                              let video,start;
                              while(performance.now()<end){
                                video=locate();
                                if(video&&video.readyState>=2){
                                  video.muted=true;
                                  if(start===undefined){start=video.currentTime;try{await video.play()}catch(e){return {advanced:false,error:e.name}}}
                                  if(video.currentTime-start>.25&&video.videoWidth>0){video.pause();return {advanced:true,width:video.videoWidth,height:video.videoHeight,seconds:video.currentTime-start,decodedFrames:video.getVideoPlaybackQuality?.().totalVideoFrames}}
                                }
                                await new Promise(r=>setTimeout(r,150));
                              }
                              return {advanced:false,videoFound:!!video,ready:video?.readyState,error:video?.error?.code};
                            })()""")
                            result['status'] = 'passed_public_search_detail_playback' if result['playback'].get('advanced') is True else 'playback_needs_verification'
                    else:
                        result['status'] = 'requires_login' if ('账号名/邮箱/手机号' in text or '登录探索更多内容' in text or '密码登录' in text or '登录' in text and len(text.splitlines()) < 30) else 'public_page_only'
                        result['reason'] = 'Search/detail business workflow has not passed in this unauthenticated identity.'
                except (RuntimeError, subprocess.TimeoutExpired, ValueError, AssertionError) as error:
                    result.update(status='failed', error=str(error)[:1000])
            report['completed'] = True
            report['all_business_workflows_passed'] = len(report['sites']) == 5 and all(x['status'].startswith('passed_') for x in report['sites'].values())
        finally:
            try:
                cli('close')
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=20)
                args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
                args.output.chmod(0o600)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
