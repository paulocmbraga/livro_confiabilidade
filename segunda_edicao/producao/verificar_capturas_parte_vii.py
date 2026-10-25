"""Entrada de conferência sem servidor, inferência ou efeito novo."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from laboratorios.parte_vii.verify import verify,protocols
p=argparse.ArgumentParser();p.add_argument('--inference',type=Path,default=ROOT/'output/parte_vii_principal_v02')
p.add_argument('--protocols',type=Path,default=ROOT/'output/parte_vii_protocolos_v02');a=p.parse_args()
print(json.dumps({'inference':verify(a.inference),'protocols':protocols(a.protocols)},ensure_ascii=False,indent=2))
