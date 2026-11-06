"""Compone el manual PDF de la API con esquemas y ejemplos comprobados."""
import argparse
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape
import json
from pathlib import Path
import shutil
import textwrap
from urllib.parse import parse_qsl, urlsplit

import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Paragraph, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
W,H = A4
LEFT,WIDTH = 53,W-106
INK = colors.HexColor('#0F3D4C')
MUTED = colors.HexColor('#6B8794')
LINE = colors.HexColor('#D9E2E7')
GOLD = colors.HexColor('#C9A227')
TEAL = colors.HexColor('#2A9D8F')


def approximate_values(value, key: str = ''):
    """Redondea solo la presentación de ejemplos; conserva tipos y datos de origen."""
    if isinstance(value,dict):return {name:approximate_values(item,name) for name,item in value.items()}
    if isinstance(value,list):return [approximate_values(item,key) for item in value]
    if isinstance(value,bool) or value is None:return value
    if not isinstance(value,(str,int,float)):return value
    try:
        number=Decimal(str(value))
    except InvalidOperation:
        return value
    if not number.is_finite():return value
    if key in {'equity','cash','previous_equity','commission','vat','spread_cost','slippage_cost','total_cost'}:
        number=number.quantize(Decimal('1'),rounding=ROUND_HALF_UP)
    elif number and number!=number.to_integral_value():
        number=number.quantize(Decimal(1).scaleb(number.adjusted()-2),rounding=ROUND_HALF_UP)
    rendered=format(number.normalize(),'f') if number==0 or number.adjusted()>=-5 else format(number.normalize(),'.2E')
    if isinstance(value,str):return rendered
    return int(number) if number==number.to_integral_value() else float(number)


def register_fonts() -> None:
    folder = Path(reportlab.__file__).parent/'fonts'
    for name,file in [('Vera','Vera.ttf'),('Vera-Bold','VeraBd.ttf'),('Vera-Italic','VeraIt.ttf')]:
        pdfmetrics.registerFont(TTFont(name,str(folder/file)))
    pdfmetrics.registerFontFamily('Vera',normal='Vera',bold='Vera-Bold',italic='Vera-Italic',boldItalic='Vera-Bold')


class Tutorial:
    """Dibuja páginas con una identidad visual común y controla sus márgenes."""
    def __init__(self, name: str, specification: dict, version: int, examples: dict, author: str) -> None:
        self.name,self.specification,self.version,self.examples = name,specification,str(version),examples
        self.author = author
        self.path = ROOT/'docs'/f'{name}-tutorial-v{version}.pdf'
        self.canvas = Canvas(str(self.path),pagesize=A4,pageCompression=1)
        self.canvas.setTitle(specification['title']+' · v'+str(version))
        self.canvas.setAuthor(author)
        self.canvas.setSubject('Manual de uso independiente del manuscrito de tesis')
        self.canvas.setDateFormatter(lambda *parts: '')
        self.number = 0
        self.y = H-115
        self.audit: list[dict] = []

    def chrome(self, section: str) -> None:
        canvas = self.canvas
        canvas.setStrokeColor(INK);canvas.setLineWidth(.8)
        border = canvas.beginPath()
        border.moveTo(18,44);border.lineTo(18,H-44);border.lineTo(42,H-20)
        border.lineTo(W-42,H-20);border.lineTo(W-18,H-44)
        border.lineTo(W-18,44);border.lineTo(W-42,20);border.lineTo(42,20);border.close()
        canvas.drawPath(border)
        canvas.setFillColor(INK)
        for x in [31,36,41]:
            for y in [H-54,H-59,H-64]:canvas.circle(x,y,.65,stroke=0,fill=1)
        canvas.setStrokeColor(GOLD);canvas.setLineWidth(1.3);canvas.line(LEFT,H-33,LEFT+66,H-33)
        canvas.setFont('Vera-Bold',8);canvas.drawString(LEFT,H-53,'MANUALES DE USO  /  API')
        canvas.setFont('Vera',8);canvas.setFillColor(MUTED);canvas.drawRightString(W-LEFT,H-53,'v'+self.version)
        canvas.setStrokeColor(LINE);canvas.setLineWidth(.5);canvas.line(LEFT,56,W-LEFT,56)
        canvas.setFillColor(MUTED);canvas.setFont('Vera',7)
        canvas.drawString(LEFT,42,self.author);canvas.drawRightString(W-LEFT,42,str(self.number).zfill(2))
        canvas.setStrokeColor(MUTED);canvas.setLineWidth(.5)
        for index in range(3):
            x=W-43-index*8;canvas.line(x,26,x+4,30)

    def paragraph(self, content: str, size: float = 10, color=INK, after: float = 12) -> None:
        style = ParagraphStyle('body',fontName='Vera',fontSize=size,leading=size*1.5,textColor=color,alignment=TA_LEFT)
        paragraph = Paragraph(content,style)
        _,height = paragraph.wrap(WIDTH,700)
        paragraph.drawOn(self.canvas,LEFT,self.y-height)
        self.y -= height+after

    def image(self, filename: str, height: float = 300, caption: str = '', framed: bool = True) -> None:
        reader = ImageReader(str(ROOT/'docs/images'/filename))
        width,pixels_height = reader.getSize()
        scale = min(WIDTH/width,height/pixels_height)
        draw_width,draw_height = width*scale,pixels_height*scale
        x = LEFT+(WIDTH-draw_width)/2
        if framed:
            self.canvas.setStrokeColor(LINE);self.canvas.setLineWidth(.6)
            self.canvas.roundRect(x-3,self.y-draw_height-3,draw_width+6,draw_height+6,5,stroke=1,fill=0)
        self.canvas.drawImage(reader,x,self.y-draw_height,width=draw_width,height=draw_height,mask='auto')
        self.y -= draw_height+13
        if caption:self.paragraph(escape(caption),8,MUTED,14)

    def callout(self, title: str, content: str, level: str | None = None) -> None:
        if level:
            self.message(content,level)
            return
        style=ParagraphStyle('note',fontName='Vera',fontSize=9.2,leading=14,textColor=INK)
        paragraph=Paragraph('<b>'+escape(title)+'</b><br/>'+content,style)
        _,height=paragraph.wrap(WIDTH-28,700)
        self.canvas.setFillColor(colors.HexColor('#EFF7F6'))
        self.canvas.roundRect(LEFT,self.y-height-22,WIDTH,height+22,6,stroke=0,fill=1)
        self.canvas.setFillColor(TEAL);self.canvas.rect(LEFT,self.y-height-22,3,height+22,stroke=0,fill=1)
        paragraph.drawOn(self.canvas,LEFT+14,self.y-height-10)
        self.y -= height+36

    def message(self, content: str, level: str) -> None:
        """Presenta mensajes tipificados con un símbolo vectorial y color propio."""
        title,accent,background = {
            'info':('Información','#246C9F','#EDF5FC'),
            'warning':('Advertencia','#946414','#FFF7DF'),
            'important':('Importante','#AA3840','#FFF0F1'),
        }[level]
        style=ParagraphStyle('message',fontName='Vera',fontSize=9.2,leading=14,textColor=INK)
        paragraph=Paragraph(content,style)
        _,height=paragraph.wrap(WIDTH-30,700)
        total=height+49
        canvas=self.canvas
        canvas.setFillColor(colors.HexColor(background))
        canvas.roundRect(LEFT,self.y-total,WIDTH,total,6,stroke=0,fill=1)
        canvas.setFillColor(colors.HexColor(accent))
        canvas.rect(LEFT,self.y-total,3,total,stroke=0,fill=1)
        x,y=LEFT+22,self.y-19
        if level=='info':
            canvas.circle(x,y,7,stroke=0,fill=1)
        else:
            path=canvas.beginPath()
            points=([(x,y+8),(x+8,y-6),(x-8,y-6)] if level=='warning' else
                    [(x-3,y+8),(x+3,y+8),(x+8,y+3),(x+8,y-3),
                     (x+3,y-8),(x-3,y-8),(x-8,y-3),(x-8,y+3)])
            path.moveTo(*points[0])
            for point in points[1:]:path.lineTo(*point)
            path.close();canvas.drawPath(path,stroke=0,fill=1)
        canvas.setFillColor(colors.white);canvas.setFont('Vera-Bold',9)
        canvas.drawCentredString(x,y-3,'i' if level=='info' else '!')
        canvas.setFillColor(colors.HexColor(accent));canvas.setFont('Vera-Bold',9.2)
        canvas.drawString(LEFT+36,self.y-22,title)
        paragraph.drawOn(canvas,LEFT+15,self.y-35-height)
        self.y -= total+14

    def table(self, headers: list[str], rows: list[list[str]], widths: list[float]) -> None:
        """Compone catálogos de opciones y comparaciones sin cortar su texto."""
        style=ParagraphStyle('cell',fontName='Vera',fontSize=8.8,leading=13,textColor=INK)
        heading=ParagraphStyle('heading',parent=style,fontName='Vera-Bold',textColor=colors.white)
        cells=[[Paragraph(escape(value),heading) for value in headers]]
        cells += [[Paragraph(value,style) for value in row] for row in rows]
        table=Table(cells,colWidths=[WIDTH*value for value in widths])
        table.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),INK),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.HexColor('#F1F6F8'),colors.white]),
            ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),
            ('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),9),
            ('LINEBELOW',(0,0),(-1,0),1,GOLD),
        ]))
        _,height=table.wrap(WIDTH,700)
        table.drawOn(self.canvas,LEFT,self.y-height)
        self.y -= height+17

    def code(self, title: str, content: str, response: bool = False) -> None:
        lines=[]
        for original in content.splitlines():
            lines.extend(textwrap.wrap(original,width=88,replace_whitespace=False,drop_whitespace=False,break_long_words=True,break_on_hyphens=False) or [''])
        font_size,leading=8,11
        height=33+leading*len(lines)
        self.canvas.setFillColor(colors.HexColor('#F0F6F3' if response else '#F1F5F8'))
        self.canvas.roundRect(LEFT,self.y-height,WIDTH,height,6,stroke=0,fill=1)
        self.canvas.setFillColor(TEAL if response else INK);self.canvas.setFont('Vera-Bold',8)
        self.canvas.drawString(LEFT+12,self.y-16,title)
        self.canvas.setFillColor(INK);self.canvas.setFont('Courier',font_size)
        cursor=self.y-33
        for line in lines:
            self.canvas.drawString(LEFT+12,cursor,line)
            cursor -= leading
        self.y -= height+15

    def diagram(self, labels: list[list[str]]) -> None:
        """Esquema vectorial del flujo: permanece nítido al ampliar o imprimir."""
        canvas=self.canvas
        count=len(labels);gap=17;box=(WIDTH-gap*(count-1))/count
        bottom=self.y-83
        for index,(title,description) in enumerate(labels):
            x=LEFT+index*(box+gap)
            canvas.setFillColor(colors.HexColor('#F1F6F8'));canvas.setStrokeColor(LINE)
            canvas.roundRect(x,bottom,box,80,7,stroke=1,fill=1)
            canvas.setFillColor(TEAL);canvas.circle(x+14,bottom+65,3,stroke=0,fill=1)
            style=ParagraphStyle('diagram',fontName='Vera',fontSize=8,leading=12,textColor=INK)
            paragraph=Paragraph('<b>'+escape(title)+'</b><br/>'+escape(description),style)
            _,height=paragraph.wrap(box-20,70);paragraph.drawOn(canvas,x+10,bottom+51-height)
            if index<count-1:
                canvas.setStrokeColor(INK);canvas.line(x+box+2,bottom+40,x+box+gap-3,bottom+40)
                path=canvas.beginPath();path.moveTo(x+box+gap-7,bottom+43);path.lineTo(x+box+gap-3,bottom+40);path.lineTo(x+box+gap-7,bottom+37);canvas.drawPath(path)
        self.y=bottom-20

    def example(self, block: dict) -> None:
        example=self.examples[block['name']]
        if block.get('request',True):
            parsed=urlsplit(example['path'])
            path=parsed.path
            if path.startswith('/api/v1/executions/'):
                pieces=path.split('/');pieces[4]='{execution_id}';path='/'.join(pieces)
            request=example['method']+' '+path
            if parsed.query:
                request+='\n\nFiltros:\n'+'\n'.join('  '+key+': '+value for key,value in parse_qsl(parsed.query))
            if example['request'] is not None:request+='\n\n'+json.dumps(example['request'],ensure_ascii=False,indent=2)
            self.code('CONSULTA  ·  '+example['method'],request)
        body=example['response']
        fragment=False
        if block.get('fields'):
            body={key:body[key] for key in block['fields']};fragment=True
        if block.get('item_fields'):
            body=dict(body);body['items']=[{key:row[key] for key in block['item_fields']} for row in body['items']];fragment=True
        if block.get('max_items'):
            body=dict(body);body['items']=body['items'][:block['max_items']];fragment=True
        if block.get('symbolic_ids'):
            body=dict(body)
            body['items']=[dict(row,execution_id='{execution_id}') for row in body['items']]
            fragment=True
        if block.get('approximate'):
            body=approximate_values(body)
        label=('RESPUESTA  ·  HTTP '+str(example['status'])+'  ·  valores aproximados' if block.get('approximate') else
               'RESPUESTA  ·  HTTP '+str(example['status'])+'  ·  identificador simbólico' if block.get('symbolic_ids') else
               'RESPUESTA REAL  ·  HTTP '+str(example['status'])+('  ·  fragmento' if fragment else ''))
        self.code(label,
                  json.dumps(body,ensure_ascii=False,indent=2),True)

    def build(self) -> None:
        pages=self.specification['pages']
        previous_section=None
        for index,page in enumerate(pages):
            self.number=index+1
            self.chrome(page.get('section',self.specification['title']))
            key=self.name+'-'+str(self.number)
            self.canvas.bookmarkPage(key)
            section=page.get('section',self.specification['title'])
            if section!=previous_section:
                self.canvas.addOutlineEntry(section,key,level=0,closed=False)
            else:
                self.canvas.addOutlineEntry(page['title'],key,level=1,closed=False)
            previous_section=section
            self.y=H-88
            if index==0:
                self.y=H-110
                self.paragraph(escape(self.specification['title']),22,INK,15)
                if self.specification.get('subtitle'):
                    self.paragraph(escape(self.specification['subtitle']),11,MUTED,16)
            else:
                self.paragraph(escape(page['title']),21,INK,7)
                if page.get('subtitle'):self.paragraph(escape(page['subtitle']),9,MUTED,16)
            for block in page['blocks']:
                kind=block['type']
                if kind=='text':self.paragraph(block['text'])
                elif kind=='image':self.image(block['file'],block.get('height',300),block.get('caption',''),block.get('framed',True))
                elif kind=='callout':self.callout(block.get('title',''),block['text'],block.get('level'))
                elif kind=='table':self.table(block['headers'],block['rows'],block['widths'])
                elif kind=='code':self.code(block['title'],block['text'],block.get('response',False))
                elif kind=='diagram':self.diagram(block['labels'])
                elif kind=='example':self.example(block)
                elif kind=='toc':
                    for entry in block['entries']:self.paragraph(escape(entry),11,INK,12)
            self.audit.append({'page':self.number,'title':page['title'],'bottom_y':round(self.y,1)})
            if self.y<68:
                raise ValueError(f'Contenido fuera del margen: {self.name}, página {self.number}, y={self.y:.1f}')
            self.canvas.showPage()
        self.canvas.save()


def main(output_dir: Path | None = None, manual: str | None = None) -> None:
    register_fonts()
    content=json.loads((ROOT/'docs/tutorial-content.json').read_text())
    examples=json.loads((ROOT/'docs/api-examples.json').read_text())['examples']
    audit_path=ROOT/'docs/validation/pdf-layout.json'
    audits=json.loads(audit_path.read_text()) if audit_path.exists() else {}
    for name in ([manual] if manual else ['api']):
        version=content[name].get('version',content['version'])
        tutorial=Tutorial(name,content[name],version,examples,content['author'])
        tutorial.build();audits[name]=tutorial.audit
        if output_dir:
            output_dir.mkdir(parents=True,exist_ok=True)
            shutil.copy2(tutorial.path,output_dir/tutorial.path.name)
        print(tutorial.path, len(tutorial.audit),'pages')
    audit_path.write_text(json.dumps(audits,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--manual',choices=['api'])
    arguments=parser.parse_args()
    main(arguments.output_dir,arguments.manual)
