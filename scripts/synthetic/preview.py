"""Render all pages and assemble contact sheets for visual review."""
from pathlib import Path
import subprocess
from generate import DOCS, TRUTH, tool
out=TRUTH/'previews'; out.mkdir(exist_ok=True)
fonts = list(Path('/usr/share/fonts').rglob('DejaVuSans.ttf')) if Path('/usr/share/fonts').exists() else []
fonts += list(Path('/nix/store').glob('*dejavu-fonts*/share/fonts/truetype/DejaVuSans.ttf'))
font_args = ['-font', str(fonts[0])] if fonts else []
for case in sorted(DOCS.glob('SYN-*')):
    pages=[]
    for pdf in sorted(case.glob('*.pdf')):
        prefix=out/(case.name+'_'+pdf.stem)
        subprocess.run([tool('pdftoppm'),'-scale-to','700','-png',str(pdf),str(prefix)],check=True,stdout=subprocess.DEVNULL)
        pages.extend(sorted(out.glob(prefix.name+'-*.png')))
    subprocess.run([tool('magick'),'montage',*font_args,*[str(p) for p in pages],'-thumbnail','280x396','-tile','4x','-geometry','+8+8','-background','#b8bcc0',str(out/(case.name+'_contact.png'))],check=True)
print(out)
