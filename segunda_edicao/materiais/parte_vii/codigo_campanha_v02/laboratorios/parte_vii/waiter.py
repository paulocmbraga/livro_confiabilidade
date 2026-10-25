"""Falha controlada: trabalhador admitido, bloqueado antes da chamada ao modelo."""
import argparse,threading,os
from laboratorios.parte_i.common import save
p=argparse.ArgumentParser();p.add_argument('--ready');a=p.parse_args()
save(a.ready,dict(pid=os.getpid(),phase='before_inference'))
threading.Event().wait()
