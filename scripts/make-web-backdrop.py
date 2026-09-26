# Generates combat/backdrop.svg: a ruined post-collapse skyline in pixel art.
# Run from apps/web:  python3 ../../scripts/make-web-backdrop.py
# 240x90 logical pixels, deterministic (seeded), crisp edges.
import random
W,H=240,90
r=random.Random(26)
px={}
def rect(x,y,w,h,c):
    for yy in range(y,y+h):
        for xx in range(x,x+w):
            if 0<=xx<W and 0<=yy<H: px[(xx,yy)]=c
FAR='#1c2627'; MID='#141b1c'; NEAR='#0b0e0f'; RUST='#3b2317'; LIT='#d9a441'; LIT2='#3aa597'; DIM='#5a3a22'; SIGN='#ff4fa0'
# far: broken towers with jagged tops
x=0
while x<W:
    w=r.randint(8,16); top=r.randint(28,52)
    rect(x,top,w,H-top,FAR)
    for i in range(w):            # jagged broken roofline
        rect(x+i,top-r.randint(0,4),1,4,FAR) if r.random()<.5 else None
    if r.random()<.4: rect(x+w-3,top-6,1,6,FAR)   # bent antenna / rebar
    x+=w+r.randint(0,3)
# a leaning crane
for i in range(26): rect(170+i//3,20+i,2,1,FAR)
rect(160,20,40,2,FAR); rect(196,22,1,10,FAR); rect(195,32,3,2,FAR)
# mid: gutted blocks with a few lit windows
x=0
while x<W:
    w=r.randint(12,24); top=r.randint(50,64)
    rect(x,top,w,H-top,MID)
    for wy in range(top+3,H-8,5):
        for wx in range(x+2,x+w-2,4):
            q=r.random()
            if q<.07: rect(wx,wy,2,2,LIT)
            elif q<.11: rect(wx,wy,2,2,LIT2)
            elif q<.22: rect(wx,wy,2,2,DIM)
    if r.random()<.3: rect(x+w//2,top-5,3,5,MID); rect(x+w//2-1,top-6,5,1,MID)   # water tank
    x+=w+r.randint(1,5)
# dead billboard: a neon "OPEN" whose N burnt out long ago
FONT = {'O': ['111', '101', '101', '101', '111'], 'P': ['111', '101', '111', '100', '100'],
        'E': ['111', '100', '110', '100', '111'], 'N': ['101', '111', '111', '111', '101']}
rect(58, 40, 36, 15, '#101516'); rect(59, 41, 34, 13, '#1e2a2b')
for i, ch in enumerate('OPEN'):
    col = '#3a2a33' if ch == 'N' else SIGN
    for yy, row in enumerate(FONT[ch]):
        for xx, bit in enumerate(row):
            if bit == '1': rect(62 + i * 7 + xx * 2 - (xx > 0) * 1, 44 + yy, 2 if xx == 1 else 1, 1, col)
rect(70, 55, 2, 11, '#101516'); rect(84, 55, 2, 11, '#101516')
# smokestack
rect(130,30,6,40,MID); rect(129,30,8,2,RUST)
# near: rubble, wrecked car, fence
h=80
for x in range(W):
    h+=r.choice([-1,0,0,1]); h=max(76,min(84,h))
    rect(x,h,1,H-h,NEAR)
rect(20,74,18,6,'#1a1210'); rect(24,71,10,3,'#1a1210'); rect(22,80,4,3,NEAR); rect(33,80,4,3,NEAR)   # dead car
for x in range(100,W,5): rect(x,72,1,10,'#1a1f20')                                              # fence posts
rect(100,73,140,1,'#1a1f20'); rect(100,77,140,1,'#1a1f20')
by={}
for (x,y),c in px.items(): by.setdefault(c,set()).add((x,y))
out=[]
for c,pts in by.items():
    d=[]
    for y in range(H):
        x=0
        while x<W:
            if (x,y) in pts:
                s0=x
                while (x,y) in pts: x+=1
                d.append(f'M{s0} {y}h{x-s0}v1h-{x-s0}z')
            else: x+=1
    out.append(f'<path fill="{c}" d="{"".join(d)}"/>')
svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" shape-rendering="crispEdges" preserveAspectRatio="xMidYMax slice">'+''.join(out)+'</svg>'
open('combat/backdrop.svg','w').write(svg)
print(len(svg))
