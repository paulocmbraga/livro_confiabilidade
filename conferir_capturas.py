from pathlib import Path
from importlib import import_module
import json

ROOT=Path(__file__).resolve().parent
results=[]
for module,function,folder in [
    ('parte_i','verify','parte_i_v03'), ('piloto04','verificar_captura','piloto04_v02'),
    ('parte_ii','verify','parte_ii_v03'), ('parte_iii','verify','parte_iii_v01'),
    ('parte_iv','verify','parte_iv_v02'), ('piloto15','verify','piloto15_v02'),
    ('parte_v','verify','parte_v_v01'), ('parte_vi','verify','parte_vi_v02')]:
    getattr(import_module('laboratorios.'+module),function)(ROOT/'output'/folder)
    results.append({'captura':folder,'resultado':'passou'})
print(json.dumps(results,ensure_ascii=False,indent=2))
