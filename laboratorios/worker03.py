"""Adaptador fixture em processo separado. stdin/stdout JSON; não é um LLM."""
import json
import sys
import time


def main():
    request=json.load(sys.stdin)
    if set(request)!={'task_id','pergunta'}:raise ValueError('Entrada contém campo não público')
    task=request['task_id']
    if task=='T03':time.sleep(30)
    if task=='T04':
        sys.stdout.write('{"texto":');sys.stdout.flush();return
    result={'task_id':task,'texto':'Resposta preparada: '+task,'uso':2 if task=='T05' else 1,
            'estado':'respondida','trilha':'D'}
    if task=='T06':result.update(estado='rejeitada_antes_inferencia',uso=0,texto='')
    json.dump(result,sys.stdout)


if __name__=='__main__':main()
