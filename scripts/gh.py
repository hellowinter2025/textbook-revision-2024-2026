# -*- coding: utf-8 -*-
"""
GitHub 工具：从 Windows 凭据管理器取令牌（不落盘、不打印），走 SOCKS5 代理调 API。

    py _preview/gh.py whoami
    py _preview/gh.py create <repo> [public|private] [description]
    py _preview/gh.py repos
下载地址：https://github.com/happycola233/tchMaterial-parser
"""
import ctypes, ctypes.wintypes as wt, sys, json, time
import requests

sys.stdout.reconfigure(encoding='utf-8')
PROXY = 'socks5h://127.0.0.1:10808'
API = 'https://api.github.com'

class CREDENTIAL(ctypes.Structure):
    _fields_ = [("Flags", wt.DWORD), ("Type", wt.DWORD), ("TargetName", wt.LPWSTR),
                ("Comment", wt.LPWSTR), ("LastWritten", wt.FILETIME),
                ("CredentialBlobSize", wt.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
                ("Persist", wt.DWORD), ("AttributeCount", wt.DWORD),
                ("Attributes", ctypes.c_void_p), ("TargetAlias", wt.LPWSTR),
                ("UserName", wt.LPWSTR)]

_adv = ctypes.WinDLL('advapi32', use_last_error=True)
_adv.CredReadW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]

def _read_cred(target='git:https://github.com'):
    p = ctypes.POINTER(CREDENTIAL)()
    if not _adv.CredReadW(target, 1, 0, ctypes.byref(p)):
        raise RuntimeError('凭据不存在: ' + target)
    c = p.contents
    blob = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize)
    _adv.CredFree(p)
    return c.UserName, blob.decode('utf-16-le', 'replace')

def token():
    return _read_cred()[1]

def user():
    return _read_cred()[0]

def _port_open(host, port, timeout=1.5):
    import socket
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except Exception:
        return False

def sess():
    """自动选择直连 / SOCKS 代理：10808 在监听就走代理，否则直连。"""
    s = requests.Session()
    if _port_open('127.0.0.1', 10808):
        s.proxies = {'http': PROXY, 'https': PROXY}
    s.headers.update({'Authorization': 'Bearer ' + token(),
                      'Accept': 'application/vnd.github+json',
                      'X-GitHub-Api-Version': '2022-11-28',
                      'User-Agent': 'wb-compare-uploader'})
    return s

def whoami():
    s = sess()
    r = s.get(API + '/user', timeout=60)
    print('HTTP', r.status_code)
    if r.ok:
        j = r.json()
        print('login      :', j['login'])
        print('name       :', j.get('name'))
        print('public_repos:', j.get('public_repos'))
    print('scopes     :', r.headers.get('X-OAuth-Scopes'))
    print('rate-limit :', r.headers.get('X-RateLimit-Remaining'))
    return r

def repos():
    s = sess()
    r = s.get(API + '/user/repos', params={'per_page': 100, 'sort': 'updated'}, timeout=60)
    for x in r.json():
        print('%-40s %8.2f MB  private=%s  updated=%s'
              % (x['full_name'], (x.get('size') or 0) / 1024, x['private'], x['updated_at'][:10]))

def create(name, vis='public', desc=''):
    s = sess()
    body = {'name': name, 'private': (vis == 'private'),
            'description': desc, 'has_issues': True, 'has_wiki': False, 'auto_init': False}
    r = s.post(API + '/user/repos', json=body, timeout=60)
    print('HTTP', r.status_code)
    if r.status_code == 201:
        print('已创建:', r.json()['html_url'])
    elif r.status_code == 422:
        print('已存在或名称非法:', r.json().get('message'), r.json().get('errors'))
    else:
        print(r.text[:400])
    return r

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'whoami'
    if cmd == 'whoami':
        whoami()
    elif cmd == 'repos':
        repos()
    elif cmd == 'create':
        create(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'public',
               sys.argv[4] if len(sys.argv) > 4 else '')
    else:
        print('未知命令', cmd)
