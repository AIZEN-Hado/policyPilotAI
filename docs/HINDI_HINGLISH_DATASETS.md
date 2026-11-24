# Hindi OCR and Hinglish dataset shortlist

PolicyPilot's noncommercial demo uses fictional training cases. The two
specialist networks need insurance field spans and evidence relevance labels.
Public OCR and transliteration datasets can inform separate component checks.

| Source | Useful for | Dataset and permissions |
|---|---|---|
| [IIIT-Synthetic-IndicSTR-Hindi](https://ilocr.iiit.ac.in/dataset/60/) | Hindi OCR checks on rendered word crops | IIIT lists image and transcription splits and requests citation. The public page does not state dataset reuse or redistribution terms. Confirm those terms before importing a subset. |
| [BhartiOCR](https://github.com/Faizaniqbal52/BhartiOCR/blob/main/README.md#15-provenance--licensing) | OCR checks on rendered Hindi text with scan-like degradation | The annotations and software use Apache 2.0. Source text has separate terms. Access is gated. Hindi page samples may lack transcriptions, so use only verified labeled items if a suitable subset is cleared. |
| [HinGE](https://huggingface.co/datasets/LingoIITGN/HinGE) | Reference for Hinglish spelling and code-switching patterns | The card lists CC BY 4.0. It derives examples from the [IIT Bombay parallel corpus](https://www.cfilt.iitb.ac.in/iitb_parallel/), whose publisher lists CC BY-NC 4.0 and separate upstream terms. Use the published method as a reference when writing original examples. |
| [Trilingual Hinglish Corpus](https://huggingface.co/datasets/debajyotimaz/trilingual-hinglish-corpus) | Reference for research on Romanized Hindi and English | Research use only. The curation and Hindi translations use CC BY-NC-SA 4.0. Original sentences have separate terms and include real social-media text. Leave it out of synthetic training. |

The next training dataset should use original English, Devanagari Hindi, and
Roman-script Hinglish versions of fictional schedules, bills and discharge
summaries. Render some of those documents as images for Tesseract and label the
fields visible in its OCR output. Keep variants of one case in the same split.
Track exact field and source-span matches separately for clean text and scans.
Report missing or corrupted fields separately.

Source and asset terms must cover the proposed use before importing any public
subset. A research-only restriction may limit a hosted demo even if the demo is
free. The specialist v2 bundle remains the English-text baseline.
