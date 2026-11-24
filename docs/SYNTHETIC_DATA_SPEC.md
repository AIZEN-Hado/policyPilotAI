# Synthetic claims: realism and quality requirements

Status: required generation specification. First three exemplar bundles generated and engineering-checked; see `data/synthetic/README.md` for current coverage and limitations. Full-corpus, OCR and domain validation remain outstanding.

## User direction

There is no pilot partner. Develop with synthetic data that resembles real Indian claims in structure, consistency, document variety and difficult cases. Do not substitute short generic text files or repeated templates for realistic claim bundles.

## Source-grounded, explicitly fictional

Before generation, research public insurer claim forms, policy schedules/wordings, customer information sheets and public hospital sample formats. Prefer official sources. Record URL, retrieval date, document version and what structural feature was learned. Do not copy private records, real claim narratives, insurer branding, signatures or substantial copyrighted wording.

Generate fictional organizations and clearly synthetic identifiers, using reserved example domains and non-routable contact placeholders. Do not fabricate usable Aadhaar, PAN, bank, UPI, medical registration or insurer UIN identifiers. Use SYN-prefixed identifiers where those fields are needed. Indian city names and document conventions may be realistic without identifying real people.

Label each document “SYNTHETIC — NOT VALID FOR CLAIM SUBMISSION” in a non-obstructive footer. Labels must not reveal the expected outcome. Avoid watermarks over the OCR test region. Realism concerns content/layout, not impersonating a real issuer.

## Generate a coherent case before rendering documents

Create a canonical structured case containing members, coverage dates, policy version and endorsements, admission/discharge dates, document chronology, billed services, payments and known utilization. Render all documents from that case, with controlled, annotated discrepancies only where the scenario requires them.

Each complete case should include the applicable subset of:
- Policy schedule and member list.
- Fictional policy wording and relevant endorsements.
- Completed claim form.
- Discharge summary with a consistent chronology.
- Detailed hospital bill with multi-page line items where appropriate.
- Receipts/deposit and refund reconciliation.
- Supporting investigation or pharmacy bill where relevant.
- Clarification request/response or utilization record where the scenario requires it.

Missing-document scenarios deliberately omit documents and annotate that omission. Do not force a fixed document count onto every case. Do not use generated clinical narratives as medical training guidance or evidence of clinical validity.

## Financial and temporal realism

Use INR and precise paise/decimal arithmetic, with explicit quantity, rate, discounts, net amount and payment allocation. Reconcile bill totals, deposits, final receipts and refunds. Represent taxes only when supported by the chosen fictional fixture specification and reviewed source basis; do not invent a universal healthcare tax rule.

Dates must respect the case chronology and coverage timeline except for intentionally labeled contradictions. Policy rules specify exact order of deductions, rounding, limits and endorsement precedence. Policy matching must depend on identifiers/version/period, not insurer name similarity.

Construct varied claim values, lengths of stay and bill sizes. Source-check ranges before claiming they are representative of Indian practice. Do not manufacture a population distribution or imply a synthetic sample reflects national prevalence.

## Document diversity

Use at least four independently authored fictional hospital layout families and two fictional policy families in the first corpus. Vary tables, column order, fonts, headers/footers, abbreviations, date formats, page numbering and multi-page continuation. A logo or font substitution alone does not create a distinct layout family.

Include native PDFs, image-only scans and mixed text/image PDFs. Produce clean and degraded variants from the same canonical case. Test controlled skew, rotation, blur, compression, low contrast, shadows, clipped margins and mixed page sizes. Record transformation parameters and seeds. Degradation must have a reason and severity label; do not render every document unreadable.

Keep expected state distinct: readable evidence, uncertain extraction requiring review, genuinely absent evidence, and contradictory evidence. Missing or illegible facts must never be silently supplied from hidden ground truth to the system under test.

Hindi/English mixtures should use valid fonts and shaping and receive linguistic inspection. Do not claim handwriting support from printed cursive fonts. Any handwriting-like challenge remains explicitly unvalidated and requires manual review.

## Ground truth and leakage prevention

Store a separate manifest for each case: family/split IDs, document hashes, source-grounded fixture rules, facts, page/bounding boxes, table cell values, intentional corruptions, expected evidence, reference calculation trace, expected review state and prohibited actions.

Ground truth is outside runtime ingestion/storage paths. It must not appear in filenames, document metadata, hidden PDF layers, page text, prompts or search indexes. Image-only scans must not contain hidden canonical text. Display names must not encode outcomes such as “excluded_claim.pdf”.

Split by canonical case family; clean/degraded siblings never cross splits. Reserve an independently authored layout family for a layout-generalization check. Prevent wording/template memorization from being mistaken for robust extraction. Keep synthetic regression and later real-data evaluation scores separate.

## Generation sequence

1. Research and log public structural references.
2. Define two fictional policy rule packs, deterministic calculation references and canonical case schema.
3. Build three complete exemplar bundles: straightforward claim, endorsement-altered calculation, and ambiguous/poor-quality evidence requiring review.
4. Validate their full document consistency, render quality, provenance and expected outcomes before scaling.
5. Expand to the planned 24 scenario families and 48 clean/degraded bundles.
6. Run a corpus audit, freeze a version and hashes, and publish an honest dataset card.

The first three bundles are a quality checkpoint, not a replacement for the broader matrix. Do not expand generation while their reconciliation or source mapping is broken.

## Acceptance checks

- Every document is parseable or explicitly an intended malformed-input test.
- Every case has a manifest, seed/version, document hashes and expected review behavior.
- Every financial difference and chronology contradiction is either reconciled or deliberately annotated.
- Every required critical fact maps to visible source evidence, or is explicitly absent/unreadable.
- Each layout family is visually inspected; all language variants and severe degradation types are inspected.
- Reference calculations use a separately checked oracle/hand-calculated examples, not just the production function under test.
- No actual personal records, usable sensitive identifiers, genuine signatures or misleading issuer branding.
- No answer leakage in runtime-visible artifacts.
- Clinical plausibility and native-language review status are reported honestly; automated checks are not domain sign-off.

Dataset card: intended use, fictional nature, source register, generation method, scenario/split counts, supported document classes/languages, degradation distribution, known omissions, reviewer status, limitations and regeneration instructions.

## Limits

High-quality synthetic data can expose implementation failures and support a realistic demonstration. It cannot establish real-world medical correctness, insurer acceptance, OCR accuracy across hospitals or market demand. Those gates remain for an authorized partner pilot.
