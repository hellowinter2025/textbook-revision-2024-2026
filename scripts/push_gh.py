# -*- coding: utf-8 -*-
"""把 gh-upload 的更新提交并推送到 GitHub（令牌只写进本地 git 配置，推完删除）"""
import ctypes, ctypes.wintypes as wt, io, os, subprocess, sys, time

sys.stdout.reconfigure(encoding='utf-8')

class C(ctypes.Structure):
    _fields_ = [("Flags", wt.DWORD), ("Type", wt.DWORD), ("TargetName", wt.LPWSTR),
                ("Comment", wt.LPWSTR), ("LastWritten", wt.FILETIME),
                ("CredentialBlobSize", wt.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
                ("Persist", wt.DWORD), ("AttributeCount", wt.DWORD),
                ("Attributes", ctypes.c_void_p), ("TargetAlias", wt.LPWSTR),
                ("UserName", wt.LPWSTR)]

adv = ctypes.WinDLL('advapi32', use_last_error=True)
adv.CredReadW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.POINTER(ctypes.POINTER(C))]
p = ctypes.POINTER(C)()
assert adv.CredReadW('git:https://github.com', 1, 0, ctypes.byref(p)), '凭据读取失败'
c = p.contents
USER = c.UserName
TOKEN = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize).decode('utf-16-le', 'replace').strip()
adv.CredFree(p)

WD = 'gh-upload'
CFG = os.path.join(WD, '.git', 'config')

def g(*args, show=True):
    r = subprocess.run(['git'] + list(args), cwd=WD, capture_output=True,
                       encoding='utf-8', errors='replace')
    out = (r.stdout or '') + (r.stderr or '')
    if TOKEN in out:
        out = out.replace(TOKEN, '<TOKEN>')
    if show and out.strip():
        print('   ', out.strip()[:300])
    return r.returncode, out

print('1) 暂存')
rc, out = g('add', '-A')
print('   rc =', rc)
rc, out = g('status', '--short')
print('   变更：')
print(out.strip()[:1200])

print('2) 提交')
msg = ('重做比对管线：修掉图表文字造成的左右错配；语文并入统一目录命名\n\n'
       '- 新增「图/表内部文字」四道过滤（按册自适应的字号阈值、行内乱序、标签堆、句子⇄碎片），\n'
       '  解决 2026 版把元素周期表等图改为矢量文字后与 2024 版正文错配的问题\n'
       '- 语文结果并入 pdf/修改页对照_语文·统编版.pdf，与其余 12 套命名一致\n'
       '- 全量重跑 13 套 / 68 册，改动由 3242 处修正为 2150 处，逐组审计通过\n'
       '- 体积由 438 MB 降到 264 MB（表格小字噪声大量减少）\n')
rc, out = g('commit', '-F', '-', show=False) if False else (None, None)
with open('_commitmsg.txt', 'w', encoding='utf-8') as f:
    f.write(msg)
rc, out = g('commit', '-F', os.path.abspath('_commitmsg.txt'))
print('   rc =', rc)
os.remove('_commitmsg.txt')

print('3) 配置本地凭据（写入 .git/config，推完删除）')
base = 'https://%s:%s@github.com/' % (USER, TOKEN)
g('config', '--local', 'url.%s.insteadOf' % base, 'https://github.com/', show=False)
print('   ok')

print('4) 推送（自动选择 直连 / SOCKS 代理）')


def _port_open(host, port, timeout=1.5):
    import socket
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except Exception:
        return False


PROXY = 'socks5h://127.0.0.1:10808'
PROXY_ARGS = ['-c', 'http.proxy=%s' % PROXY, '-c', 'https.proxy=%s' % PROXY]
DIRECT_ARGS = ['-c', 'http.proxy=', '-c', 'https.proxy=']
has_proxy = _port_open('127.0.0.1', 10808)
print('   代理 127.0.0.1:10808 %s' % ('在监听，先试代理' if has_proxy else '未监听，先试直连'))
tries = [PROXY_ARGS, DIRECT_ARGS] if has_proxy else [DIRECT_ARGS, PROXY_ARGS]
t0 = time.time()
rc = 1
out = ''
for i, extra in enumerate(tries, 1):
    where = '代理' if extra is PROXY_ARGS else '直连'
    r = subprocess.run(['git'] + extra + ['push', '--progress', 'origin', 'main'],
                       cwd=WD, capture_output=True, encoding='utf-8', errors='replace')
    out = ((r.stdout or '') + (r.stderr or '')).replace(TOKEN, '<TOKEN>')
    rc = r.returncode
    print('   第%d次（%s）rc=%d' % (i, where, rc))
    if rc == 0:
        break
print('   用时 %.0fs' % (time.time() - t0))
print('   ', out.strip()[-400:])

print('5) 清理本地配置中的令牌')
s = io.open(CFG, encoding='utf-8', errors='replace').read()
lines = s.splitlines()
kept, rm = [], 0
skip_url = False
for ln in lines:
    if TOKEN in ln:
        rm += 1
        skip_url = True
        continue
    if skip_url and (ln.strip().startswith('insteadof') or ln.strip().startswith('insteadOf')):
        rm += 1
        continue
    skip_url = False
    kept.append(ln)
io.open(CFG, 'w', encoding='utf-8', newline='').write('\n'.join(kept) + '\n')
print('   删除含令牌的行数：', rm)
left = [l for l in io.open(CFG, encoding='utf-8', errors='replace').read().splitlines() if TOKEN in l]
print('   残留检查：', '无' if not left else '仍有 %d 行' % len(left))
