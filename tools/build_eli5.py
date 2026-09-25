"""Build the friendly six-page companion to TK-LPLUT-2.0.

Requires ReportLab and pypdf. Illustrations are original PDF vectors; no raster
assets or runtime implementation changes are needed.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math

from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'output/pdf/Tom_Klootwijk_Paradigm_ELI5.pdf'
W, H = A4
M = 48
CW = W - 2*M
CREAM = '#FFF9EF'
INK = '#213E43'
TEAL = '#11796F'
MINT = '#DCEFE5'
CORAL = '#F4A28A'
PEACH = '#FCE6DC'
YELLOW = '#F2CC69'
MUTED = '#50676A'
WHITE = '#FFFFFF'
LAYOUT = []


def color(value): return colors.HexColor(value)


def fonts(folder):
    folder = Path(folder)
    for name, filename in [('EBody','segoeui.ttf'),('EBold','segoeuib.ttf'),
                           ('ETitle','georgiab.ttf')]:
        pdfmetrics.registerFont(TTFont(name,str(folder/filename)))
    pdfmetrics.registerFontFamily('EBody', normal='EBody', bold='EBold')


def text(c, x, top, width, value, size=14, leading=20, font='EBody', fill=INK,
         align=0, limit=778):
    style=ParagraphStyle('text',fontName=font,fontSize=size,leading=leading,
                         textColor=color(fill),alignment=align)
    paragraph=Paragraph(value,style)
    _,height=paragraph.wrap(width,H)
    if top+height>limit:
        raise ValueError(f'Page {c.getPageNumber()} overflow: {top+height}: {value[:60]}')
    paragraph.drawOn(c,x,H-top-height)
    LAYOUT.append({'page':c.getPageNumber(),'top':top,'bottom':round(top+height,2),
                   'text':value})
    return height


def line(c,x1,y1,x2,y2,fill=INK,width=2):
    c.setStrokeColor(color(fill)); c.setLineWidth(width)
    c.line(x1,H-y1,x2,H-y2)


def circle(c,x,y,r,fill,stroke=None,width=1):
    c.setFillColor(color(fill)); c.setStrokeColor(color(stroke or fill))
    c.setLineWidth(width); c.circle(x,H-y,r,fill=1,stroke=bool(stroke))


def rounded(c,x,top,width,height,fill,stroke=None,r=14):
    c.setFillColor(color(fill)); c.setStrokeColor(color(stroke or fill))
    c.setLineWidth(1.3)
    c.roundRect(x,H-top-height,width,height,r,fill=1,stroke=bool(stroke))


def arrow(c,x1,y1,x2,y2,fill=TEAL,width=2):
    line(c,x1,y1,x2,y2,fill,width)
    angle=math.atan2(y2-y1,x2-x1)
    for delta in [-.55,.55]:
        line(c,x2,y2,x2-8*math.cos(angle+delta),y2-8*math.sin(angle+delta),fill,width)


def robot(c,x,top,s=1,body=MINT,mirror=False):
    def px(v): return x+s*(110-v if mirror else v)
    def py(v): return top+s*v
    # Antenna, head, eyes, smile, body, arms and feet.
    line(c,px(55),py(18),px(55),py(4),TEAL,2*s)
    circle(c,px(55),py(3),4*s,YELLOW)
    rounded(c,x+15*s,py(18),80*s,55*s,body,INK,r=13*s)
    for eye in [40,70]: circle(c,px(eye),py(40),4*s,INK)
    path=c.beginPath(); path.moveTo(px(41),H-py(54))
    path.curveTo(px(47),H-py(63),px(63),H-py(63),px(69),H-py(54))
    c.setStrokeColor(color(INK)); c.setLineWidth(2*s); c.drawPath(path)
    rounded(c,x+29*s,py(82),52*s,38*s,body,INK,r=8*s)
    circle(c,px(45),py(98),5*s,YELLOW)
    for side,end in [(29,9),(81,101)]:
        line(c,px(side),py(93),px(end),py(103),INK,3*s)
    for foot in [42,69]:
        line(c,px(foot),py(120),px(foot),py(135),INK,3*s)
        line(c,px(foot)-6*s,py(135),px(foot)+7*s,py(135),INK,3*s)


def room(c,x,top,label,fill=MINT,size=61):
    rounded(c,x,top,size,size,fill,INK,r=12)
    text(c,x+5,top+19,size-10,label,13,17,'EBold',align=1)


def page_start(c,number,tag,title):
    c.setFillColor(color(CREAM)); c.rect(0,0,W,H,fill=1,stroke=0)
    text(c,M,30,CW,tag.upper(),9,12,'EBold',TEAL)
    text(c,M,77,CW,title,29,35,'ETitle')
    footer(c,number)
    c.bookmarkPage(f'page{number}'); c.addOutlineEntry(title,f'page{number}',0)


def footer(c,number,dark=False):
    fill=MINT if dark else MUTED
    line(c,M,797,W-M,797,TEAL if dark else '#D6DDD3',.7)
    text(c,M,807,CW-40,"Tom Klootwijk's paradigm, explained simply",8,11,fill=fill,limit=835)
    text(c,W-M-28,807,28,f'{number} / 6',8,11,fill=fill,align=2,limit=835)


def build(output):
    output.parent.mkdir(parents=True,exist_ok=True)
    c=canvas.Canvas(str(output),pagesize=A4,invariant=1,pageCompression=1)
    c.setTitle("A Little Machine with a World of Its Own - Tom Klootwijk's Paradigm, Explained Simply")
    c.setAuthor('Tom Klootwijk - architecture; friendly explanation prepared with Codex')
    c.setSubject('An illustrated ELI5 companion to The Infallible Contract, 25 September 2026')

    # 1. A warm invitation, with the robot explicitly framed as an analogy.
    c.setFillColor(color(INK)); c.rect(0,0,W,H,fill=1,stroke=0)
    c.bookmarkPage('page1'); c.addOutlineEntry('A little machine with a world of its own','page1',0)
    text(c,M,39,CW,'THE ELI5 EDITION',10,14,'EBold',YELLOW)
    text(c,M,93,CW,'A little machine<br/>with a world<br/>of its own',37,44,'ETitle',CREAM)
    text(c,M,247,CW,'Tom Klootwijk\'s idea, told with rooms,<br/>rule cards and a very small robot.',16,23,fill=MINT)
    circle(c,297,438,94,'#2D5458')
    line(c,144,404,245,430,'#87B8AA',2)
    line(c,359,430,439,378,'#87B8AA',2)
    line(c,354,468,440,514,'#87B8AA',2)
    robot(c,228,356,1.25)
    room(c,79,371,'world',MINT,70)
    room(c,438,342,'rules',YELLOW,70)
    room(c,438,488,'notes',CORAL,70)
    text(c,M,585,CW,'Imagine one little machine whose world, instructions and memories use the same kind of small building block.',17,25,'EBold',CREAM)
    text(c,M,676,CW,'Its current situation helps choose its next step. It can even rebuild details it made from rules and put away, using the original recipe and the notes that recipe needs.',14,21,fill=MINT)
    text(c,M,754,CW,'Our robot stands for a computer program. This is a story about how it works.',9.5,13,fill=MINT)
    footer(c,1,True); c.showPage()

    # 2. Exact graph distance, without equations or a technical vocabulary lesson.
    page_start(c,2,'The world','Start with connections')
    text(c,M,160,CW,'Imagine a few rooms joined by paths. The machine describes its world through those connections: which rooms meet, and how long each path is.')
    text(c,M,253,CW,'Now mark a boundary. Every room gets a number telling us the shortest distance to it, following the paths. The size of the number tells us how far away; its sign tells us which side.')
    rounded(c,M,343,CW,166,WHITE)
    text(c,M+16,358,CW-32,'A tiny example: each path below is one step.',11,16,fill=MUTED)
    xs=[91,194,297,400,503]
    for a,b in zip(xs,xs[1:]): line(c,a,418,b,418,'#A1B6AD',3)
    for x,label,fill in zip(xs,['-2','-1','0','+1','+2'],[MINT,MINT,YELLOW,PEACH,PEACH]):
        circle(c,x,418,23,fill,INK if label=='0' else None,2)
        text(c,x-21,408,42,label,16,21,'EBold',align=1)
    text(c,65,462,156,'inside',12,16,'EBold',TEAL,align=1)
    text(c,246,462,102,'boundary',12,16,'EBold',align=1)
    text(c,426,462,105,'outside',12,16,'EBold',align=1)
    text(c,M,548,CW,'<b>Negative means inside. Zero means on the boundary. Positive means outside.</b>',16,23)
    text(c,M,626,CW,'The boundary could be the edge of a region in a little simulated world. The number gives the machine something exact to work with when choosing a rule.')
    text(c,M,719,CW,'The connections and boundary give this world its shape.',17,24,'EBold',TEAL)
    c.showPage()

    # 3. Self-reference is the visible feedback loop, not magical self-awareness.
    page_start(c,3,'The next step','Each step helps choose<br/>the next one')
    text(c,M,185,CW,'The machine reads its current situation and uses it to choose a rule card. Following that card changes the situation. That new situation helps choose the next card.')
    card_x=[48,222,396]
    labels=[('Read','the situation'),('Choose','a rule card'),('Take','the next step')]
    for i,(x,(a,b)) in enumerate(zip(card_x,labels),1):
        rounded(c,x,305,151,121,[MINT,PEACH,'#F8EDC7'][i-1])
        circle(c,x+24,330,12,TEAL)
        text(c,x+13,321,22,str(i),12,16,'EBold',WHITE,align=1)
        text(c,x+15,357,121,a,19,24,'EBold')
        text(c,x+15,385,121,b,12,17)
    arrow(c,202,368,219,368); arrow(c,376,368,393,368)
    line(c,471,433,471,458,TEAL)
    line(c,471,458,124,458,TEAL)
    arrow(c,124,458,124,433)
    text(c,160,470,275,'The changed situation goes around again.',11,16,fill=TEAL,align=1)
    rounded(c,M,521,CW,73,INK)
    text(c,M+18,537,CW-36,'Its own latest situation helps choose<br/>what happens next.',17,23,'EBold',CREAM,align=1)
    text(c,M,627,CW,'World facts, instructions and records all use the same kind of little block. Labels tell the machine how to read each one, like a card that belongs to a particular part of a game.')
    text(c,M,723,CW,'The rules are supplied. The loop follows them; it does not have to invent them as it goes.',12,18,fill=MUTED)
    c.showPage()

    # 4. Regeneration and the paired representation, each with its actual limit.
    page_start(c,4,'Memory and checking','Remember the recipe')
    text(c,M,155,CW,'Suppose you build a toy house, then clear it off the table. You can rebuild it if you keep the instructions and every piece or note those instructions need.')
    text(c,M,250,CW,'The machine can do this with generated details of its world. A small worktable still needs somewhere to keep those recipes and notes.')
    rounded(c,66,342,107,66,MINT)
    text(c,77,363,85,'recipe',16,21,'EBold',align=1)
    text(c,179,362,30,'+',22,27,'EBold',TEAL,align=1)
    rounded(c,215,342,107,66,PEACH)
    text(c,226,363,85,'notes',16,21,'EBold',align=1)
    arrow(c,337,375,382,375)
    room(c,410,340,'rebuild',YELLOW,70)
    text(c,M,463,CW,'Two views, one individual',24,30,'ETitle')
    text(c,M,514,CW,'It also keeps a mirrored view of its state. Think of looking at the same toy from two sides. The views must agree in the way the rules say they should.')
    robot(c,159,620,.76,body=MINT)
    robot(c,353,620,.76,body=PEACH,mirror=True)
    c.setDash(3,5); line(c,298,624,298,737,'#90AAA0',1.5); c.setDash()
    text(c,M,750,CW,'That helps spot certain mistakes. It is one individual, with two related views.',11.5,16,fill=MUTED)
    c.showPage()

    # 5. Explain local GPU work and the conditional promise in ordinary language.
    page_start(c,5,'Doing the work','Keep the cards close')
    text(c,M,159,CW,'The GPU is another kind of computer worker. It can keep the rule cards and the current state nearby, then follow a run of steps before checking back with the main computer.')
    rounded(c,M,282,CW,155,MINT)
    robot(c,83,292,.82)
    for i,fill in enumerate([WHITE,PEACH,YELLOW]):
        rounded(c,244+i*18,310+i*9,88,78,fill,INK,r=9)
    arrow(c,378,353,405,353)
    text(c,413,330,105,'next<br/>step',16,21,'EBold',TEAL,align=1)
    text(c,220,413,300,'A nearby workbench, with the cards at hand.',10,14,fill=MUTED,align=1)
    text(c,M,472,CW,'What “infallible” means here',23,30,'ETitle')
    text(c,M,521,CW,'Think of a game with a complete rulebook. Start from an allowed position, give the same information in the same order, and follow the rules faithfully.')
    rounded(c,M,625,CW,98,PEACH)
    text(c,M+16,639,CW-32,'The same steps give the same answer. Any promise we have proved the rules keep stays true along the way.',16,23,'EBold')
    text(c,M,743,CW,'That promise depends on those conditions. It does not make faulty hardware or a wrong rule disappear.',11.5,16,fill=MUTED)
    c.showPage()

    # 6. Measured progress is dated, and the story is not presented as a finished robot.
    page_start(c,6,'Where we are today','Several pieces already work')
    text(c,M,159,CW,'The small building blocks work. The machine can calculate exact boundary distances in its little connected worlds. The main computer and GPU can follow the same sequence and agree, step for step.')
    stats=[('262','checks passed'),('21','ran on the GPU'),('64','matching steps')]
    for i,(number,label) in enumerate(stats):
        x=M+i*174
        rounded(c,x,284,151,106,[MINT,PEACH,'#F8EDC7'][i])
        text(c,x+10,300,131,number,31,38,'ETitle',align=1)
        text(c,x+9,350,133,label,11,16,'EBold',align=1)
    text(c,M,409,CW,'These are recorded checks from 25 September 2026. The GPU checks are part of the 262, and the 64 steps are one matching CPU/GPU example.',11.5,16,fill=MUTED)
    text(c,M,473,CW,'The next pieces of the story',23,30,'ETitle')
    text(c,M,520,CW,'The special twisting world called a Klein bottle still needs to be built into the program. The world-building, memory and decision-making pieces also need to be joined into one evolving individual.')
    rounded(c,M,627,CW,95,INK)
    text(c,M+18,642,CW-36,'The idea we are building toward:<br/>one individual with a world made of shared blocks,<br/>which it can explore and rebuild from saved recipes.',15,21,'EBold',CREAM,align=1)
    text(c,M,740,CW,'Architecture by Tom Klootwijk. A friendly companion to <i>The Infallible Contract</i> (TK-LPLUT-2.0). The robot and rooms are explanatory pictures.',10,14,fill=MUTED)
    c.showPage(); c.save()

    reader=PdfReader(output)
    if len(reader.pages)!=6: raise ValueError('Expected six pages')
    qa=ROOT/'tmp/pdfs'; qa.mkdir(parents=True,exist_ok=True)
    (qa/'eli5-layout.json').write_text(json.dumps(LAYOUT,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(output),'pages':6,
                      'sha256':hashlib.sha256(output.read_bytes()).hexdigest()},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--font-dir',default='C:/Windows/Fonts')
    parser.add_argument('--output',type=Path,default=OUTPUT)
    args=parser.parse_args()
    fonts(args.font_dir)
    build(args.output)
