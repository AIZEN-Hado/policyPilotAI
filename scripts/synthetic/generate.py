"""Deterministic fictional claim documents. Python standard library + Poppler/ImageMagick.
Ground truth is written outside the ingestible document directory.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / 'data/synthetic/exemplars'
TRUTH = ROOT / 'evaluation/synthetic'
VERSION = 'exemplars-1.0'


def tool(name):
    found = shutil.which(name)
    if found:
        return found
    candidates = sorted(Path('/nix/store').glob(f'*-*/bin/{name}'))
    if not candidates:
        raise RuntimeError(f'{name} required; install Poppler and ImageMagick')
    return str(candidates[-1])


def money(paise):
    whole, fraction = divmod(paise, 100)
    digits = str(whole)
    tail = digits[-3:]
    head = digits[:-3]
    groups = []
    while head:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return 'INR ' + ','.join(groups + [tail]) + f'.{fraction:02d}'


def write_pdf(path, streams, images=None):
    objects = []
    def add(data):
        objects.append(data if isinstance(data, bytes) else data.encode('ascii'))
        return len(objects)
    add('<< /Type /Catalog /Pages 2 0 R >>')
    add('')
    add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>')
    pages = []
    for i, content in enumerate(streams):
        img_ref = None
        if images:
            raw, w, h = images[i]
            img_ref = add(f'<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length {len(raw)} >>\nstream\n'.encode() + raw + b'\nendstream')
        raw = content.encode('ascii')
        stream = add(f'<< /Length {len(raw)} >>\nstream\n'.encode() + raw + b'\nendstream')
        resources = f'/XObject << /Im0 {img_ref} 0 R >>' if images else '/Font << /F1 3 0 R /F2 4 0 R >>'
        pages.append(add(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << {resources} >> /Contents {stream} 0 R >>'))
    objects[1] = f'<< /Type /Pages /Count {len(pages)} /Kids [{" ".join(f"{p} 0 R" for p in pages)}] >>'.encode()
    data = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n')
    offset = len(data)
    data.extend(f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode())
    for pos in offsets[1:]:
        data.extend(f'{pos:010d} 00000 n \n'.encode())
    data.extend(f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{offset}\n%%EOF\n'.encode())
    path.write_bytes(data)


class Document:
    def __init__(self, case, issuer, title, layout=0):
        self.case, self.issuer, self.title, self.layout = case, issuer, title, layout
        self.pages, self.spans = [], []
        self.new_page()

    def rawtext(self, x, y, text, size=10, bold=False, key=None):
        if not text:
            return
        text.encode('ascii')
        escaped = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        self.ops.append(f'BT /F{2 if bold else 1} {size} Tf 1 0 0 1 {x} {y} Tm ({escaped}) Tj ET')
        self.spans.append({'page': len(self.pages)+1, 'text': text, 'field': key,
                           'bbox_top_left_pt': [x, 842-y-size, min(555, x+size*len(text)*0.62), 842-y+3]})

    def new_page(self):
        if hasattr(self, 'ops'):
            self.close_page()
        self.ops = ['0.12 0.16 0.20 rg']
        # Distinct hospital document header structures, not just palette changes.
        if self.layout == 1:
            self.rawtext(40, 800, self.title.upper(), 17, True)
            self.rawtext(40, 777, self.issuer, 11)
            self.y = 699
        elif self.layout == 2:
            self.rawtext(40, 804, self.issuer.upper(), 14, True)
            self.rawtext(40, 780, 'INPATIENT SERVICES / RECORD COPY', 9)
            self.rawtext(40, 747, self.title, 16, True)
            self.y = 690
        else:
            self.rawtext(40, 800, self.issuer, 17, True)
            self.rawtext(40, 775, self.title, 13, True)
            self.y = 699
        self.rawtext(40, 735 if self.layout != 2 else 725,
                     f"Case {self.case['id']}  |  {self.case['city']}  |  Records: records@example.invalid", 8)
        self.ops.append('0.65 G 40 721 m 555 721 l S' if self.layout != 2 else '0.65 G 40 712 m 555 712 l S')

    def close_page(self):
        self.rawtext(40, 31, 'SYNTHETIC - NOT VALID FOR CLAIM SUBMISSION', 8, True)
        self.rawtext(40, 18, f"Fictional issuer and patient | {self.case['id']} | Page {len(self.pages)+1}", 7)
        self.pages.append('\n'.join(self.ops))

    def line(self, text='', key=None, bold=False):
        for part in textwrap.wrap(text, width=92) or ['']:
            if self.y < 72:
                self.new_page()
            self.rawtext(40, self.y, part, 10, bold, key)
            self.y -= 16

    def section(self, title):
        self.line()
        self.line(title.upper(), bold=True)
        self.y -= 3

    def field(self, label, value, key=None):
        self.line(f'{label}: {value}', key)

    def rows(self, headers, rows, widths):
        if self.layout == 1 and headers[0] == 'No.':
            order = [0, 1, 4, 2, 3]
            headers = [headers[i] for i in order]
            rows = [[row[i] for i in order] for row in rows]
            widths = [30, 230, 90, 45, 120]
        elif self.layout == 2 and headers[0] == 'No.':
            order = [1, 2, 3, 4, 0]
            headers = [headers[i] for i in order]
            rows = [[row[i] for i in order] for row in rows]
            widths = [230, 45, 80, 110, 50]
        xs = [40]
        for width in widths[:-1]:
            xs.append(xs[-1]+width)
        def row(values, header=False):
            self.ops.append(f'0.85 G 40 {self.y-7} m 555 {self.y-7} l S')
            for x, value in zip(xs, values):
                self.rawtext(x, self.y, str(value), 9, header)
            self.y -= 25
        row(headers, True)
        for values in rows:
            if self.y < 95:
                self.new_page()
                row(headers, True)
            row(values)
        self.y -= 8

    def save(self, path):
        self.close_page()
        write_pdf(path, self.pages)
        return {'file': path.name, 'pages': len(self.pages), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'representation': 'native_text', 'source_spans': self.spans}


CASES = [
 dict(id='SYN-C001', name='Meera Kulkarni', age=34, city='Pune', hospital='SYN Riverbend Hospital',
      policy='SYN-P101', member='SYN-M101', product='SYN-IND-2026-V1', family=False, layout=0,
      admission='2026-08-12', discharge='2026-08-15', diagnosis='Acute appendicitis',
      course='Admitted with abdominal pain. Surgical assessment and imaging documented appendicitis. Laparoscopic appendectomy performed on 13 August. Observed postoperatively; discharged in stable condition.',
      room=3, roomrate=3500, copay=0, deductible=0, endorsement=False,
      items=[('Room - single standard',3,3500),('Nursing care',3,900),('Surgeon fee',1,25000),('Anaesthesia fee',1,8000),('Operating theatre',1,11000),('Medical consultations',4,700),('Laboratory investigations',1,4200),('Abdominal ultrasound',1,2200),('Inpatient pharmacy',1,6800),('Procedure materials',1,3600),('Patient registration',1,300)],
      total=77100, expected=76800, deposit=30000, prior=0),
 dict(id='SYN-C002', name='Arjun Menon', age=42, city='Bengaluru', hospital='SYN Cedarfield Surgical Centre',
      policy='SYN-P202', member='SYN-M202-A', product='SYN-FAM-2026-V1', family=True, layout=1,
      admission='2026-09-07', discharge='2026-09-10', diagnosis='Symptomatic cholelithiasis',
      course='Admitted for planned management after outpatient surgical review. Laparoscopic cholecystectomy performed on 8 September. Recovery documented without an inpatient complication; discharged stable.',
      room=3, roomrate=5000, copay=10, deductible=5000, endorsement=True,
      items=[('Room - single standard',3,5000),('Nursing services',3,1200),('Surgeon fee',1,42000),('Anaesthesia fee',1,12000),('Operating theatre',1,18000),('Medical consultations',4,900),('Laboratory investigations',1,4800),('Ultrasound review',1,2800),('Inpatient pharmacy',1,9200),('Procedure materials',1,7500),('Patient registration',1,500)],
      total=119000, expected=102150, deposit=50000, prior=120000),
 dict(id='SYN-C003', name='Nisha Verma', age=51, city='Jaipur', hospital='SYN Sandstone Care Hospital',
      policy='SYN-P303', member='SYN-M303-A', product='SYN-FAM-2026-V1', family=True, layout=2,
      admission='2026-10-03', discharge='2026-10-07', diagnosis='Community-acquired pneumonia',
      course='Admitted with fever and cough. Investigations and inpatient treatment recorded. Clinical improvement noted before discharge. Admission recorded by the inpatient desk on 3 October 2026.',
      room=4, roomrate=2800, copay=10, deductible=5000, endorsement=False,
      items=[('Room - twin sharing',4,2800),('Nursing services',4,800),('Physician reviews',6,900),('Chest imaging',1,2200),('Laboratory investigations',1,4800),('Inpatient pharmacy',1,9600),('Respiratory support charges',2,1200),('Procedure materials',1,1800),('Patient registration',1,300)],
      total=40900, expected=None, deposit=20000, prior=None)
]


def build_case(c):
    dest = DOCS/c['id']; dest.mkdir(parents=True, exist_ok=True)
    truth = TRUTH/c['id']; truth.mkdir(parents=True, exist_ok=True)
    manifest = {'version': VERSION, 'case_family_id': c['id'], 'split': 'development_exemplar',
                'canonical_case': c, 'documents': [], 'review_status': 'engineering_checked_not_clinically_validated'}
    def doc(issuer, title, layout=0): return Document(c, issuer, title, layout)
    def save(d, name): manifest['documents'].append(d.save(dest/name))
    def patient(d):
        d.field('Patient', f"{c['name']} / age {c['age']}", 'patient')
        d.field('Member / policy', f"{c['member']} / {c['policy']}", 'identity')
    d=doc('SYN Meridian Benefits', 'Policy schedule / member certificate')
    d.section('Contract identification'); patient(d)
    for label, val in [('Product identifier',c['product']),('Contract type','Family floater' if c['family'] else 'Individual'),('Coverage period','2026-01-01 to 2026-12-31 inclusive'),('Continuous coverage since','2023-01-01'),('Sum insured',money(100000000 if c['family'] else 50000000)),('Currency','INR'),('Wording version','2026.1')]: d.field(label,val,'schedule.'+label)
    d.section('Insured members')
    d.line(f"{c['member']} | {c['name']} | Self | Active throughout coverage period")
    if c['family']: d.line(f"{c['member'][:-1]}B | {'Isha Menon' if c['id']=='SYN-C002' else 'Rohan Verma'} | Spouse | Active throughout coverage period")
    d.section('Selected benefit terms')
    d.line('Room benefit: single standard room; daily cap INR 4,000.00.' if c['family'] else 'Room benefit: single standard room at actual billed cost.')
    d.line(f"Per-admission deductible: {money(c['deductible']*100)}. Copayment: {c['copay']} percent after deductible.")
    d.line('Endorsements attached: SYN-END-202 dated 2026-06-01.' if c['endorsement'] else 'Endorsements attached: none recorded for this certificate.')
    d.section('Record administration'); d.line('Fictional contract for software testing only. No premium has been collected. Member and issuer identifiers cannot be used with any insurer or public registry.')
    save(d,'01_schedule.pdf')
    d=doc('SYN Meridian Benefits', 'Policy wording / version 2026.1')
    clauses=[('1. Scope and definitions','An eligible admission is inpatient treatment of illness during the scheduled coverage period for a listed member. The schedule, this wording and applicable dated endorsements form the fictional contract.'),
    ('2. Eligible inpatient expenses','Billed room accommodation, nursing, treating clinician fees, anaesthesia, theatre, investigations, inpatient pharmacy and procedure materials are eligible when supported by the admission record and final itemized bill. This fixture imposes no separate clinical sublimit.'),
    ('3. Administrative exclusion','Patient registration charges are excluded. No other administrative exclusion may be inferred. Missing evidence is a request for verification, not an excluded expense.'),
    ('4. Room benefit','For individual certificates, single standard room is paid at actual cost. For family certificates the cap is INR 4,000.00 per billed day unless changed by endorsement. Deduct only room charges above the cap; no proportionate reduction of other items applies in this fixture.'),
    ('5. Deductible and copayment','Individual certificates have no deductible or copayment. Family certificates have an INR 5,000.00 per-admission deductible, followed by a 10 percent copayment on the remaining eligible amount. These are fictional product terms, not general rules for Indian insurance.'),
    ('6. Waiting period','A 30-day initial waiting period applies from continuous coverage inception. The listed exemplar members began continuous coverage on 2023-01-01. No additional disease-specific waiting period is defined for these fixture admissions.'),
    ('7. Utilization and benefit ceiling','The annual ceiling is the sum insured less previously paid benefits across listed members. Family cover shares that ceiling. No restoration benefit is provided. Unknown utilization blocks a final payable amount.'),
    ('8. Order of operations','First reconcile the supported gross bill. Remove registration and any room-cap excess. Subtract the deductible, flooring at zero. Apply the copayment to that balance. Round to paise, half up. Finally cap the amount at verified remaining annual cover.'),
    ('9. Endorsement precedence','An endorsement applies only to its named policy and effective period. Its explicitly replaced clause takes precedence; all unrelated terms remain unchanged.'),
    ('10. Evidence and review','Require a matching schedule, itemized final bill, payment evidence and admission/discharge record. Contradictory dates or incomplete bill pages require clarification. An assessment is a draft until an authorized human review; it is not a payment instruction.')]
    for i,(title,body) in enumerate(clauses):
        if i==5: d.new_page()
        d.section(title); d.line(body,'clause.'+str(i+1))
    save(d,'02_wording.pdf')
    if c['endorsement']:
        d=doc('SYN Meridian Benefits','Endorsement / SYN-END-202'); patient(d)
        d.field('Issued / effective','2026-06-01 / 2026-06-01 through 2026-12-31')
        d.section('Amendment to clause 4'); d.line('The daily room limit is increased from INR 4,000.00 to INR 6,000.00 for policy SYN-P202. This applies to each listed member. All other terms, including deductible and copayment, remain unchanged.','endorsement.room_cap')
        d.section('Version control'); d.line('Schedule reference SYN-P202; product SYN-FAM-2026-V1; wording 2026.1. This endorsement is not transferable to another policy.')
        save(d,'03_endorsement.pdf')
    d=doc('SYN Meridian Benefits','Reimbursement claim form')
    d.section('A / member declaration'); patient(d)
    d.field('Contact','patient@example.invalid / phone not collected in synthetic fixture')
    d.field('Other insurance declared','None'); d.field('Bank/KYC details','Not supplied; no payment execution in this fixture')
    d.section('B / hospitalization'); d.field('Hospital',c['hospital']); d.field('Admission', '2026-10-02' if c['id']=='SYN-C003' else c['admission'],'claim.admission'); d.field('Discharge',c['discharge'],'claim.discharge'); d.field('Diagnosis as recorded',c['diagnosis'])
    d.field('Admission type','Planned' if c['id']=='SYN-C002' else 'Emergency')
    d.section('C / expense statement'); d.field('Inpatient expenses claimed',money(c['total']*100),'claimed_total'); d.line('Pre-hospitalization: INR 0.00 | Post-hospitalization: INR 0.00 | Other: INR 0.00')
    d.section('D / attachment checklist'); d.line('Schedule; wording; discharge summary; final hospital bill; payment receipt. Endorsement included where applicable. Supporting investigation record attached.')
    d.section('E / declaration'); d.line('This record represents a fictional submission for software evaluation. No real signature, bank mandate or legal declaration has been collected.')
    d.field('Submission date',{'SYN-C001':'2026-08-20','SYN-C002':'2026-09-15','SYN-C003':'2026-10-12'}[c['id']]); save(d,'04_claim_form.pdf')
    d=doc(c['hospital'],'Discharge summary',c['layout']); patient(d)
    d.field('Inpatient record',c['id'].replace('C','IP')); d.field('Admission',c['admission'],'hospital.admission'); d.field('Discharge',c['discharge'],'hospital.discharge'); d.field('Discharge status','Stable / home')
    d.section('Diagnosis'); d.line(c['diagnosis'],'diagnosis'); d.section('Presentation and inpatient course'); d.line(c['course'],'course')
    d.section('Investigations'); d.line('See attached investigation record. Findings are fictional narrative content and have not been clinically validated.')
    d.section('Follow-up record'); d.line('Outpatient review was advised. Medication names and dosing are intentionally omitted; this fixture is not a treatment guide.')
    d.section('Record authorization'); d.line('SYN-CLINICIAN-01 / synthetic record author; no medical registration or signature represented.')
    save(d,'05_discharge.pdf')
    # Two-page bill. Case 3 is missing the continuation page; total remains visible on page 1.
    d=doc(c['hospital'],'Final inpatient bill',c['layout']); patient(d)
    d.field('Bill number',c['id'].replace('C','BILL')); d.field('Service period',f"{c['admission']} to {c['discharge']}")
    d.field('Final invoice total',money(c['total']*100),'bill.total')
    d.line('All amounts in INR. No tax or discount is modeled in this fictional invoice.')
    d.section('Service charges / sheet 1 of 2')
    entries=[[str(i+1),n,str(q),f'{r:,.2f}',f'{q*r:,.2f}'] for i,(n,q,r) in enumerate(c['items'])]
    d.rows(['No.','Description','Qty','Rate','Amount'],entries[:6],[30,240,40,80,125])
    d.line('Remaining services and invoice reconciliation on sheet 2.','bill.continuation')
    if c['id']!='SYN-C003':
        d.new_page(); d.field('Bill number',c['id'].replace('C','BILL')); patient(d); d.section('Service charges / sheet 2 of 2')
        d.rows(['No.','Description','Qty','Rate','Amount'],entries[6:],[30,240,40,80,125]); d.field('Gross / net invoice',money(c['total']*100),'bill.total'); d.field('Deposit received',money(c['deposit']*100)); d.field('Final collection',money((c['total']-c['deposit'])*100)); d.field('Balance outstanding','INR 0.00'); d.line('Receipt references: '+c['id']+'-R1 and '+c['id']+'-R2. Payments settle the hospital bill, not insurer liability.')
    save(d,'06_bill.pdf')
    d=doc(c['hospital'],'Payment receipt / consolidated ledger',c['layout']); patient(d)
    d.rows(['Receipt','Date','Description','Amount'],[[c['id']+'-R1',c['admission'],'Admission deposit',money(c['deposit']*100)],[c['id']+'-R2',c['discharge'],'Final collection',money((c['total']-c['deposit'])*100)]],[105,90,170,150])
    d.field('Total paid',money(c['total']*100),'receipt.total'); d.field('Refund','INR 0.00'); d.field('Outstanding balance','INR 0.00'); d.line('Payment mode: synthetic ledger entry. No bank account, transaction network identifier or actual transfer is represented.'); save(d,'07_receipts.pdf')
    d=doc(c['hospital'],'Investigation record',c['layout']); patient(d); d.field('Record date',c['admission']); d.field('Requesting service','Inpatient treating team')
    d.section('Recorded examination'); d.line({'SYN-C001':'Abdominal ultrasound: narrative finding compatible with the documented appendicitis assessment.','SYN-C002':'Abdominal ultrasound review: gallstones described in the clinical record.','SYN-C003':'Chest imaging: narrative finding of pulmonary opacity recorded for inpatient clinical correlation.'}[c['id']])
    d.section('Limitations'); d.line('Fictional supporting narrative. No real image, laboratory measurement or clinical interpretation is supplied. This document tests linkage and evidence handling, not diagnostic accuracy.'); save(d,'08_investigation.pdf')
    if c['prior'] is not None:
        d=doc('SYN Meridian Benefits','Benefit utilization statement'); patient(d); d.field('As of',c['admission']); d.field('Previously paid benefits',money(c['prior']*100),'utilization.prior'); d.field('Remaining annual cover',money(((1000000 if c['family'] else 500000)-c['prior'])*100),'utilization.remaining'); d.line('Statement applies to the annual policy period and all members listed on the schedule. It precedes the current admission; no restoration is assumed.'); save(d,'09_utilization.pdf')
    manifest['expected']={'state':'REVIEW_REQUIRED' if c['expected'] is not None else 'REQUIRES_MORE_INFO','draft_payable_paise':None if c['expected'] is None else c['expected']*100,'final_payment_authorized':False,
      'missing_or_conflicting':[] if c['expected'] is not None else ['bill_sheet_2_absent','claim_admission_2026-10-02_vs_hospital_2026-10-03','prior_utilization_absent'],
      'reference_calculation':{'SYN-C001':'77100 - 300 registration = 76800; no deductible/copay; within 500000 remaining cover.', 'SYN-C002':'119000 - 500 registration = 118500; room 5000/day within endorsed 6000 cap; minus 5000 deductible = 113500; minus 11350 copay = 102150; within 880000 remaining cover.', 'SYN-C003':'No definitive payable amount: incomplete bill, conflicting dates, unknown utilization. Payment receipt alone cannot reconstruct missing evidence.'}[c['id']]}
    # Raster-only copy is the delivered bill for case 3, with no hidden text layer.
    if c['id']=='SYN-C003':
        path=dest/'06_bill.pdf'
        with tempfile.TemporaryDirectory() as temp:
            prefix=Path(temp)/'page'
            subprocess.run([tool('pdftoppm'),'-r','120','-singlefile','-png',str(path),str(prefix)],check=True,stdout=subprocess.DEVNULL)
            jpeg=Path(temp)/'scan.jpg'
            subprocess.run([tool('magick'),str(prefix)+'.png','-colorspace','sRGB','-background','#eeeeeb','-rotate','0.65','-gravity','center','-crop','992x1404+0+0','+repage','-blur','0x0.45','-quality','62',str(jpeg)],check=True)
            w,h=map(int,subprocess.check_output([tool('magick'),'identify','-format','%w %h',str(jpeg)]).decode().split())
            write_pdf(path,['q 595 0 0 842 0 0 cm /Im0 Do Q'],[(jpeg.read_bytes(),w,h)])
        m=next(x for x in manifest['documents'] if x['file']=='06_bill.pdf')
        m['representation']='image_only_scan'; m['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        m['degradation']={'dpi':120,'rotation_degrees':0.65,'blur_sigma':0.45,'jpeg_quality':62,'seed':None,'deterministic':True}
        m['coordinate_note']='Source spans describe the canonical pre-rotation page; not exact scan coordinates. Do not score scan localization with these boxes.'
        for span in m['source_spans']: span['canonical_bbox_top_left_pt']=span.pop('bbox_top_left_pt')
    (truth/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def main():
    DOCS.mkdir(parents=True,exist_ok=True); TRUTH.mkdir(parents=True,exist_ok=True)
    manifests=[build_case(c) for c in CASES]
    print(json.dumps({'cases':len(manifests),'documents':sum(len(m['documents']) for m in manifests),'pages':sum(d['pages'] for m in manifests for d in m['documents'])}))

if __name__=='__main__': main()
