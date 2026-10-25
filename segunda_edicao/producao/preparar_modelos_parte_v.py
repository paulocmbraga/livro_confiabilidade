"""Restore exact local model/runtime files; no existing artifact is replaced."""
from pathlib import Path
import hashlib,json,shutil,zipfile
from urllib.request import urlopen
P=Path(__file__).resolve().parents[1];dest=P/'.modelos/parte_v';dest.mkdir(parents=True,exist_ok=True)
lock=json.loads((P/'materiais/parte_v/modelos.lock.json').read_text(encoding='utf-8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
downloads={
 'whisper-v1.8.7.zip':'https://github.com/ggml-org/whisper.cpp/releases/download/v1.8.7/whisper-bin-x64.zip',
 'ggml-tiny.bin':'https://huggingface.co/ggerganov/whisper.cpp/resolve/'+lock['whisper_revision']+'/ggml-tiny.bin'}
for name,url in downloads.items():
    path=dest/name
    if not path.exists():
        partial=path.with_suffix(path.suffix+'.partial')
        with urlopen(url,timeout=120) as src,partial.open('xb') as out:shutil.copyfileobj(src,out)
        if sha(partial)!=lock['whisper_files'][name]:raise ValueError('download hash')
        partial.rename(path)
    if sha(path)!=lock['whisper_files'][name]:raise ValueError('existing file hash')
with zipfile.ZipFile(dest/'whisper-v1.8.7.zip') as z:
    base=(dest/'whisper-v1.8.7').resolve()
    for member in z.infolist():
        target=(base/member.filename).resolve()
        if not target.is_relative_to(base):raise ValueError('unsafe ZIP path')
        if member.is_dir():target.mkdir(parents=True,exist_ok=True);continue
        data=z.read(member);target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            if target.read_bytes()!=data:raise ValueError('existing binary differs')
        else:target.write_bytes(data)
for name,h in lock['whisper_files'].items():assert sha(dest/name)==h,name
import rapidocr_onnxruntime
for p in Path(rapidocr_onnxruntime.__file__).parent.rglob('*.onnx'):assert sha(p)==lock['ocr_models'][p.name],p.name
print('Whisper runtime/model and OCR model hashes verified.')
