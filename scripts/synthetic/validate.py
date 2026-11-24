"""Check fixture consistency, observable evidence and PDF extraction without an LLM."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from decimal import Decimal, ROUND_HALF_UP
sys.path.insert(0, str(Path(__file__).parent))
from generate import DOCS, TRUTH, tool


def validate():
    checks=[]
    def check(condition, description):
        checks.append({'check':description,'passed':bool(condition)})
    seen=[]
    for manifest_path in sorted(TRUTH.glob('SYN-*/manifest.json')):
        m=json.loads(manifest_path.read_text()); c=m['canonical_case']; cid=c['id']; seen.append(cid)
        check(sum(q*r for _,q,r in c['items'])==c['total'],cid+' line items reconcile')
        check(dt.date.fromisoformat(c['admission']) < dt.date.fromisoformat(c['discharge']),cid+' clinical chronology')
        check((dt.date.fromisoformat(c['discharge'])-dt.date.fromisoformat(c['admission'])).days==c['room'],cid+' bed days match dates')
        check(c['deposit'] <= c['total'],cid+' payment allocation')
        texts={}
        for d in m['documents']:
            path=DOCS/cid/d['file']
            check(hashlib.sha256(path.read_bytes()).hexdigest()==d['sha256'],str(path.relative_to(DOCS))+' hash')
            info=subprocess.check_output([tool('pdfinfo'),str(path)]).decode()
            pages=int(next(x.split(':')[1] for x in info.splitlines() if x.startswith('Pages:')))
            check(pages==d['pages'],cid+'/'+d['file']+' page count')
            text=subprocess.check_output([tool('pdftotext'),'-layout',str(path),'-']).decode(); texts[d['file']]=text
            if d['representation']=='image_only_scan':
                check(not text.strip(),cid+' scan has no hidden text')
                images=subprocess.check_output([tool('pdfimages'),'-list',str(path)]).decode()
                check('jpeg' in images,cid+' scan contains embedded image')
            else:
                check('SYNTHETIC - NOT VALID FOR CLAIM SUBMISSION' in text,cid+'/'+d['file']+' label')
                check(cid in text,cid+'/'+d['file']+' case linkage')
                for span in d['source_spans']:
                    box=span.get('bbox_top_left_pt')
                    check(0<=box[0]<box[2]<=595 and 0<=box[1]<box[3]<=842,cid+'/'+d['file']+' source region')
                # all authored lines must survive PDF text extraction (whitespace-insensitive)
                normalized=''.join(text.split())
                check(all(''.join(s['text'].split()) in normalized for s in d['source_spans']),cid+'/'+d['file']+' text extraction integrity')
            check('draft_payable' not in text and 'reference_calculation' not in text,cid+'/'+d['file']+' no answer fields')
        if cid=='SYN-C001':
            # Independent hand-calculated reference, not the generator's expected value.
            check(m['expected']['draft_payable_paise']==7_680_000,cid+' fixed reference payable')
        elif cid=='SYN-C002':
            eligible=Decimal('119000')-Decimal('500')-Decimal('5000')
            payable=(eligible*Decimal('.90')).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
            check(m['expected']['draft_payable_paise']==int(payable*100)==10_215_000,cid+' independently calculated endorsement payable')
            check('6,000.00' in texts['03_endorsement.pdf'],cid+' endorsed cap is visible')
        else:
            check(m['expected']['draft_payable_paise'] is None,cid+' no fabricated payable amount')
            check('2026-10-02' in texts['04_claim_form.pdf'] and '2026-10-03' in texts['05_discharge.pdf'],cid+' date conflict is visible')
            check(not (DOCS/cid/'09_utilization.pdf').exists(),cid+' utilization genuinely missing')
            check(next(d['pages'] for d in m['documents'] if d['file']=='06_bill.pdf')==1,cid+' bill continuation genuinely missing')
        check(not m['expected']['final_payment_authorized'],cid+' human authorization required')
    check(len(seen)==3,'three exemplar bundles')
    check(not list(DOCS.rglob('*.json')),'ground truth absent from runtime documents')
    report={'status':'passed' if all(x['passed'] for x in checks) else 'failed','checks':len(checks),'failures':[x for x in checks if not x['passed']], 'limitations':['No OCR engine executed; scan OCR accuracy not measured.','Clinical/domain and native-language review not performed.','Canonical bounding boxes are approximate text regions; scan localization is not ground-truthed.']}
    (TRUTH/'validation_report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return report['status']=='passed'

if __name__=='__main__': raise SystemExit(0 if validate() else 1)
