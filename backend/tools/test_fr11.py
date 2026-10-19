"""FR-11 幻觉抑制实测：静音 / 低幅噪声样本经真实流水线，期望零有效输出。"""
import io, json, os, random, struct, time, urllib.request, wave

BASE = 'http://127.0.0.1:5000'


def make_wav(kind, seconds, sr=16000):
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        n = int(seconds * sr)
        if kind == 'silence':
            data = [0] * n
        elif kind == 'noise_quiet':
            random.seed(1)
            data = [random.randint(-100, 100) for _ in range(n)]
        elif kind == 'tone':
            import math
            data = [int(300 * math.sin(2 * math.pi * 1000 * i / sr)) for i in range(n)]
        else:  # noise_low
            random.seed(2)
            data = [random.randint(-800, 800) for _ in range(n)]
        w.writeframes(struct.pack('<%dh' % n, *data))
    return buf.getvalue()


def upload(wav_bytes, fname):
    bd = '----fr11' + str(time.time())
    body = ('--%s\r\nContent-Disposition: form-data; name="audio"; filename="%s"\r\n'
            'Content-Type: audio/wav\r\n\r\n' % (bd, fname)).encode() + wav_bytes + \
           ('\r\n--%s--\r\n' % bd).encode()
    req = urllib.request.Request(BASE + '/api/v1/uploads/simple', data=body, method='POST',
                                 headers={'Content-Type': 'multipart/form-data; boundary=' + bd})
    return json.loads(urllib.request.urlopen(req).read().decode())


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path).read().decode())


def wait_job(jid, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = get('/api/v1/jobs/' + jid)
        st = d['job']['status']
        if st in ('done', 'partial', 'failed'):
            return st
        time.sleep(2)
    return 'timeout'


cases = [('silence', 6, 'silence_6s.wav'),
         ('silence', 15, 'silence_15s.wav'),
         ('tone', 8, 'tone_1khz_8s.wav'),
         ('noise_quiet', 8, 'noise_quiet_8s.wav'),
         ('noise_low', 8, 'noise_low_8s.wav')]

print('%-16s %-8s %-8s %-8s %s' % ('样本', 'job状态', '段落数', '字符数', '文本'))
print('-' * 90)
results = {}
for kind, secs, fname in cases:
    wav = make_wav(kind, secs)
    up = upload(wav, fname)
    rid, jid = up['recording_id'], up['job_id']
    st = wait_job(jid)
    d = get('/api/v1/recordings/' + rid)
    segs = d.get('segments') or []
    text = (d.get('text') or '').strip()
    chars = len(text.replace('\n', ''))
    print('%-16s %-8s %-8d %-8d %s' % (fname, st, len(segs), chars, text[:50]))
    results[fname] = {'status': st, 'segments': len(segs), 'chars': chars, 'text': text}
    # 清理
    try:
        urllib.request.urlopen(urllib.request.Request(BASE + '/api/v1/recordings/' + rid, method='DELETE'))
    except Exception:
        pass

print()
print('=== 判定（幻觉零容忍：静音/纯音/极低噪声应零有效输出）===')
must_zero = ['silence_6s.wav', 'silence_15s.wav', 'tone_1khz_8s.wav', 'noise_quiet_8s.wav']
allok = True
for k in must_zero:
    ok = results[k]['chars'] == 0
    allok = allok and ok
    print('  %-20s 零输出: %s (chars=%d)' % (k, ok, results[k]['chars']))
print('FR-11 判定:', 'PASS' if allok else 'FAIL')
