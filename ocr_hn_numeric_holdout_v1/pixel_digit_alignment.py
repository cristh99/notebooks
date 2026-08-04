"""Conservative independent pixel-to-digit alignment for one numeric token."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from functools import cached_property
from pathlib import Path
from typing import Iterable
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

DEFAULT_TEMPLATE_FONTS=(
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
    '/usr/share/fonts/truetype/lato/Lato-Regular.ttf',
    '/usr/share/fonts/opentype/inter/InterDisplay-Regular.otf',
)
class AlignmentStatus(str,Enum):
    ALIGNED='ALIGNED'; MISALIGNED='MISALIGNED'; INDETERMINATE='INDETERMINATE'
@dataclass(frozen=True)
class AlignmentThresholds:
    aligned_absolute:float=.69
    aligned_margin:float=.012
    mismatch_absolute:float=.74
    mismatch_delta:float=.08
    mismatch_margin:float=.015
@dataclass(frozen=True)
class PositionDecision:
    index:int; claim:str; predicted:str; state:str
    top_score:float; claim_score:float; top_margin:float; mismatch_delta:float
    def to_data(self):
        return {k:(round(v,9) if isinstance(v,float) else v) for k,v in self.__dict__.items()}
@dataclass(frozen=True)
class AlignmentDecision:
    status:AlignmentStatus; claim:str; predicted:str
    positions:tuple[PositionDecision,...]; cuts:tuple[int,...]
    def to_data(self, include_positions=True):
        payload={'status':self.status.value,'claim':self.claim,'predicted':self.predicted,'cuts':list(self.cuts)}
        if include_positions: payload['positions']=[p.to_data() for p in self.positions]
        return payload

def render_numeric_token(text,font_path,size=48,angle=0,spacing=0,stroke=0):
    if not text or not text.isdigit(): raise ValueError('digits required')
    font=ImageFont.truetype(font_path,size)
    scratch=ImageDraw.Draw(Image.new('L',(1,1),255))
    if spacing==0:
        box=scratch.textbbox((0,0),text,font=font,stroke_width=stroke)
        image=Image.new('L',(box[2]-box[0]+28,box[3]-box[1]+28),255)
        ImageDraw.Draw(image).text((14-box[0],14-box[1]),text,font=font,fill=0,stroke_width=stroke,stroke_fill=0)
    else:
        boxes=[scratch.textbbox((0,0),c,font=font,stroke_width=stroke) for c in text]
        widths=[b[2]-b[0] for b in boxes]
        image=Image.new('L',(sum(widths)+spacing*(len(text)-1)+28,max(b[3]-b[1] for b in boxes)+28),255)
        draw=ImageDraw.Draw(image); x=14
        for c,b,w in zip(text,boxes,widths,strict=True):
            draw.text((x-b[0],14-b[1]),c,font=font,fill=0,stroke_width=stroke,stroke_fill=0); x+=w+spacing
    if angle: image=image.rotate(angle,expand=True,fillcolor=255,resample=Image.Resampling.BICUBIC)
    return image

def _ink(image):
    a=np.array(image.convert('L'))
    a=cv2.GaussianBlur(a,(3,3),0)
    _,binary=cv2.threshold(a,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)
    n,labels,stats,_=cv2.connectedComponentsWithStats((binary>0).astype(np.uint8),8)
    cleaned=np.zeros_like(binary); minimum=max(2,int(binary.size*.0003))
    for i in range(1,n):
        if stats[i,cv2.CC_STAT_AREA]>=minimum: cleaned[labels==i]=255
    rows,cols=np.where(cleaned>0)
    if not len(cols): return np.zeros((1,1),np.uint8)
    return cleaned[rows.min():rows.max()+1,cols.min():cols.max()+1]

def _normalize(binary,shape=(64,48)):
    h,w=shape; rows,cols=np.where(binary>0)
    if not len(cols): return np.zeros(shape,np.uint8)
    binary=binary[rows.min():rows.max()+1,cols.min():cols.max()+1]
    sh,sw=binary.shape; scale=min((h-10)/sh,(w-10)/sw)
    rw=max(1,round(sw*scale)); rh=max(1,round(sh*scale))
    resized=cv2.resize(binary,(rw,rh),interpolation=cv2.INTER_AREA if scale<1 else cv2.INTER_CUBIC)
    _,resized=cv2.threshold(resized,127,255,cv2.THRESH_BINARY)
    result=np.zeros(shape,np.uint8); y=(h-rh)//2; x=(w-rw)//2
    result[y:y+rh,x:x+rw]=resized
    return result

def _projection_cuts(binary,length):
    _,width=binary.shape
    if length<=1:return (0,width)
    projection=(binary>0).sum(axis=0).astype(float)
    projection=np.convolve(projection,np.ones(3)/3,mode='same')
    expected=width/length; cuts=[0]
    for index in range(1,length):
        center=index*expected
        low=max(cuts[-1]+1,int(center-expected*.35)); high=min(width-1,int(center+expected*.35)+1)
        if low>=high: cut=round(center)
        else: cut=min(range(low,high),key=lambda c:(projection[c]+.15*abs(c-center),abs(c-center),c))
        cuts.append(cut)
    cuts.append(width); return tuple(cuts)

def _segment(binary,length):
    cuts=_projection_cuts(binary,length); patches=[]
    for left,right in zip(cuts,cuts[1:]):
        patch=binary[:,left:right]; rows,cols=np.where(patch>0)
        if len(cols): patch=patch[rows.min():rows.max()+1,cols.min():cols.max()+1]
        patches.append(patch)
    return tuple(patches),cuts

class PixelDigitAligner:
    _shape=(64,48)
    _hog=cv2.HOGDescriptor(_winSize=(48,64),_blockSize=(16,16),_blockStride=(8,8),_cellSize=(8,8),_nbins=9)
    def __init__(self,template_fonts:Iterable[str]=DEFAULT_TEMPLATE_FONTS,thresholds=AlignmentThresholds()):
        fonts=tuple(str(Path(f)) for f in template_fonts if Path(f).exists())
        if not fonts: raise ValueError('no fonts')
        self.template_fonts=fonts; self.thresholds=thresholds
    @classmethod
    def _feature(cls,binary):
        n=_normalize(binary,cls._shape)
        hog=cls._hog.compute(n).ravel().astype(np.float32)
        low=(cv2.resize(n,(12,16),interpolation=cv2.INTER_AREA).ravel().astype(np.float32)/255)
        horiz=(n>0).mean(axis=1).astype(np.float32); vert=(n>0).mean(axis=0).astype(np.float32)
        v=np.concatenate([hog,low*.8,horiz*.5,vert*.5]); norm=np.linalg.norm(v)
        return v/norm if norm else v
    @cached_property
    def _bank(self):
        features=[]; labels=[]
        for digit in '0123456789':
            for font in self.template_fonts:
                for size in (42,52,62):
                    for angle in (-2,-1,0,1,2):
                        for stroke in (0,1):
                            features.append(self._feature(_ink(render_numeric_token(digit,font,size=size,angle=angle,stroke=stroke))))
                            labels.append(digit)
        return np.vstack(features),np.array(labels)
    def _digit_scores(self,patch):
        features,labels=self._bank; sims=features@self._feature(patch); scores={}
        for d in '0123456789': scores[d]=float(np.sort(sims[labels==d])[-7:].mean())
        return scores
    def align(self,image,claim):
        if not claim or not claim.isdigit(): raise ValueError('claim digits required')
        if isinstance(image,(str,Path)):
            with Image.open(image) as im: source=im.convert('L')
        else: source=image.convert('L')
        patches,cuts=_segment(_ink(source),len(claim)); positions=[]; predicted=[]; t=self.thresholds
        for index,(patch,claimed) in enumerate(zip(patches,claim,strict=True)):
            scores=self._digit_scores(patch)
            ranking=sorted(((s,d) for d,s in scores.items()),reverse=True)
            top_score,top_digit=ranking[0]; second=ranking[1][0]; claim_score=scores[claimed]
            margin=top_score-second; delta=top_score-claim_score
            if top_digit==claimed and top_score>=t.aligned_absolute and margin>=t.aligned_margin: state='ALIGNED'
            elif top_digit!=claimed and top_score>=t.mismatch_absolute and delta>=t.mismatch_delta and margin>=t.mismatch_margin: state='MISMATCH_CANDIDATE'
            else: state='INDETERMINATE'
            predicted.append(top_digit); positions.append(PositionDecision(index,claimed,top_digit,state,top_score,claim_score,margin,delta))
        states=[p.state for p in positions]
        if all(s=='ALIGNED' for s in states): status=AlignmentStatus.ALIGNED
        elif states.count('MISMATCH_CANDIDATE')==1 and states.count('ALIGNED')==len(states)-1: status=AlignmentStatus.MISALIGNED
        else: status=AlignmentStatus.INDETERMINATE
        return AlignmentDecision(status,claim,''.join(predicted),tuple(positions),cuts)
