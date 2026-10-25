"""Exploratory post-campaign consumer; no oracle input to the decision."""
import re
from decimal import Decimal,InvalidOperation

def decision(kind,width,text,value,complete):
    if not complete:return {'accepted':False,'reason':'incomplete'}
    if kind!='ocr':return {'accepted':False,'reason':'unqualified_audio'}
    if width<500:return {'accepted':False,'reason':'resolution'}
    fields={}
    for label in ['Subtotal','Tax','Total']:
        values=re.findall(r'(?<!\w)'+label+r'\s+(\d+\.\d{2})(?!\d)',text,re.I)
        if len(values)!=1:return {'accepted':False,'reason':'field_missing_or_ambiguous'}
        fields[label]=Decimal(values[0])
    if fields['Subtotal']+fields['Tax']!=fields['Total']:
        return {'accepted':False,'reason':'arithmetic'}
    try:v=Decimal(str(value))
    except InvalidOperation:return {'accepted':False,'reason':'value'}
    if not v.is_finite() or v!=fields['Total']:
        return {'accepted':False,'reason':'disagreement'}
    return {'accepted':True,'reason':'candidate','amount_cents':int(v*100)}
