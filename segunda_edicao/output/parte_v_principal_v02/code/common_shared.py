"""I/O explícito, manifesto e processos pertencentes à bancada."""
from pathlib import Path
from contextlib import contextmanager
import hashlib, json, os, platform, sqlite3, subprocess, sys, time

ROOT = Path(__file__).resolve().parents[2]
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
        ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()

def environment():
    return {'python':sys.version, 'platform':platform.platform(),
            'sqlite':sqlite3.sqlite_version, 'cpu_logical':os.cpu_count(),
            'dependencies':'Python standard library only',
            'clock':'perf_counter for elapsed; time.time for UTC epoch',
            'scope':'local Windows host; no LLM, people, paid API or remote service'}

def seal(root, kind, complete=True):
    root = Path(root)
    files = {p.relative_to(root).as_posix():sha(p)
             for p in sorted(root.rglob('*')) if p.is_file() and p!=root/'manifesto.json'}
    save(root/'manifesto.json', {'schema':1,'kind':kind,'complete':complete,'files':files})

def check_manifest(root):
    root=Path(root); m=load(root/'manifesto.json')
    actual={p.relative_to(root).as_posix() for p in root.rglob('*')
            if p.is_file() and p!=root/'manifesto.json'}
    if set(m['files']) != actual: raise ValueError('Inventário incompleto ou arquivo extra')
    for rel,h in m['files'].items():
        p=(root/rel).resolve()
        if not p.is_relative_to(root.resolve()) or sha(p)!=h:
            raise ValueError('Hash ou caminho inválido: '+rel)
    return m

def wait_file(path, proc, timeout=15):
    end=time.monotonic()+timeout
    while not Path(path).exists():
        if proc.poll() is not None: raise RuntimeError(f'Processo encerrou: {proc.returncode}')
        if time.monotonic()>end: raise TimeoutError(str(path))
        time.sleep(.01)

@contextmanager
def child(module, args, folder):
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
    with (folder/'stdout.txt').open('x',encoding='utf-8') as out, (folder/'stderr.txt').open('x',encoding='utf-8') as err:
        p=subprocess.Popen([sys.executable,'-m',module,*map(str,args)],cwd=ROOT,
            stdout=out,stderr=err,creationflags=FLAGS)
        try: yield p
        finally:
            if p.poll() is None:
                p.terminate()
                try:p.wait(timeout=5)
                except subprocess.TimeoutExpired:p.kill();p.wait(timeout=5)
