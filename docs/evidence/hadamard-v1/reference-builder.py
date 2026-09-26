"""Independent scratch arithmetic: imports no solvefinite runtime module."""
import json
from collections import deque
from heapq import heappop, heappush
from math import gcd
from pathlib import Path

W,H,CENTER,RADIUS=4,5,0,2
N=W*H
GAINS=((1,1),(-1,1),(-1,-1),(1,-1))
TURNS=(11,53,137)
DIRS=((1,0),(-1,0),(0,1),(0,-1))
NAMES=tuple(f'k:{u}:{v}' for u in range(W) for v in range(H))

def step(i,e):
    u,v=divmod(i,H); du,dv=e
    qu,u=divmod(u+du,W)
    return u*H+((-v-dv if qu%2 else v+dv)%H),qu%2

ADJ=tuple(tuple(sorted((step(i,e)[0] for e in DIRS),key=NAMES.__getitem__)) for i in range(N))
EDIR={(i,step(i,e)[0]):e for i in range(N) for e in DIRS}

def distances(seeds):
    ds=[None]*N; q=deque(seeds)
    for i in seeds:ds[i]=0
    while q:
        i=q.popleft()
        for j in ADJ[i]:
            if ds[j] is None:ds[j]=ds[i]+1;q.append(j)
    return tuple(ds)

CENTER_D=distances((CENTER,))
SIGNS=tuple((d>RADIUS)-(d<RADIUS) for d in CENTER_D)
BOUNDARY_D=distances(tuple(i for i,s in enumerate(SIGNS) if not s))
PHI=tuple(s*d for s,d in zip(SIGNS,BOUNDARY_D))
GRAD=tuple((PHI[step(i,(1,0))[0]]-PHI[step(i,(-1,0))[0]],
            PHI[step(i,(0,1))[0]]-PHI[step(i,(0,-1))[0]]) for i in range(N))
PSI=tuple((gu//gcd(abs(gu),abs(gv)),gv//gcd(abs(gu),abs(gv))) if gu or gv else (1,0) for gu,gv in GRAD)

def arithmetic(i,t,j,hazard,gains=GAINS):
    a,b=gains[t//64]; pu,pv=PSI[i]; gu,gv=GRAD[i]
    d=(a*(1+pu*pu),b*(1+pv*pv)); q=(d[0]*gu,d[1]*gv)
    e=EDIR[i,j]; m=max(abs(q[0]),abs(q[1])); penalty=m-q[0]*e[0]-q[1]*e[1]
    return {'phase':t,'sector':t//64,'g':list(GRAD[i]),'psi':list(PSI[i]),
            'gain':list(gains[t//64]),'diagonal':list(d),'q':list(q),'direction':list(e),
            'maximum':m,'penalty':penalty,'cost':1+abs(PHI[j])+hazard+penalty}

def next_phase(i,t):return (t+TURNS[(PHI[i]>0)-(PHI[i]<0)+1])%256

def route(i,target,t,known,max_hops=255,gains=GAINS,collapse=False):
    remain=distances((target,)); frontier=[(0,(),i,t,0)]; key=lambda v,p,h:(v,h) if collapse else (v,p,h)
    best={key(i,t,0):(0,())}; expansions=0
    while frontier:
        total,path,i,t,h=heappop(frontier)
        if best[key(i,t,h)]!=(total,path):continue
        if i==target:
            return {'route':[NAMES.index(n) for n in path],'paths':list(path),'cost':total,'expansions':expansions}
        expansions+=1; nh=h+1; nt=next_phase(i,t)
        for j in ADJ[i]:
            if nh+remain[j]>max_hops:continue
            candidate=total+arithmetic(i,t,j,known.get(j,0),gains)['cost'],path+(NAMES[j],)
            state=key(j,nt,nh)
            if state not in best or candidate<best[state]:
                best[state]=candidate;heappush(frontier,(*candidate,j,nt,nh))
    return None

def verify_by_layers(start,target,t,known,result,max_hops=255,gains=GAINS):
    # Every edge costs >=1: no path longer than the candidate cost can tie it.
    limit=result['cost']; current={(start,t):(0,())}; goal=None
    for h in range(min(max_hops,limit)+1):
        following={}
        for (i,t),(cost,path) in current.items():
            if i==target:
                if goal is None or (cost,path)<goal:goal=cost,path
                continue
            for j in ADJ[i]:
                candidate=(cost+arithmetic(i,t,j,known.get(j,0),gains)['cost'],path+(NAMES[j],))
                if candidate[0]>limit:continue
                state=j,next_phase(i,t)
                if state not in following or candidate<following[state]:following[state]=candidate
        current=following
    assert goal==(result['cost'],tuple(result['paths'])),(goal,result)

def word(r,i,eta,opcode=1):
    raw=r|(i<<8)|((PHI[i]&255)<<16)|((opcode|(eta<<4))<<24)
    return raw|((raw.bit_count()%2)<<31)

def pair(r,i,eta,opcode=1):
    return f'{word((-r)%256,i,eta^1,opcode):08X}{word(r,i,eta,opcode):08X}'

def transition(r,i,eta,j):
    delta=TURNS[(PHI[i]>0)-(PHI[i]<0)+1]
    r=(r+(-1 if eta else 1)*delta)%256
    _,tau=step(i,EDIR[i,j]);return ((-r)%256 if tau else r),j,eta^tau

def mission(initial_phase=250,hazard_after=True,gains=GAINS):
    i,r,eta,energy=0,initial_phase,0,100; known={}; events=[]
    initial={'node':i,'phase':r,'orientation':eta,'pair':pair(r,i,eta),'energy':energy}
    for cycle in range(1,101):
        visible=tuple(sorted((i,*ADJ[i]),key=NAMES.__getitem__))
        frame={j:70 if hazard_after and cycle>=2 and j==3 else 0 for j in visible}
        known.update(frame); t=((-r)%256 if eta else r)
        if i==17:
            assert energy>=5;energy-=5
            events.append({'cycle':cycle,'kind':'REPAIR','input':{NAMES[j]:v for j,v in frame.items()},
                           'route':[],'cost':5,'node':i,'phase':r,'orientation':eta,'pair':pair(r,i,eta,6),'energy':energy})
            break
        result=route(i,17,t,known,gains=gains);verify_by_layers(i,17,t,known,result,gains=gains)
        if result['cost']+5>energy:
            events.append({'cycle':cycle,'kind':'INSUFFICIENT_ENERGY','input':{NAMES[j]:v for j,v in frame.items()},
                           **result,'node':i,'phase':r,'orientation':eta,'pair':pair(r,i,eta),'energy':energy})
            break
        j=result['route'][0]; audit=arithmetic(i,t,j,frame[j],gains)
        forecast=[];fr,fi,fe=r,i,eta
        for dest in result['route']:
            fr,fi,fe=transition(fr,fi,fe,dest);forecast.append(pair(fr,fi,fe))
        r,i,eta=transition(r,i,eta,j);energy-=audit['cost']
        events.append({'cycle':cycle,'kind':'MOVE','input':{NAMES[j]:v for j,v in frame.items()},
                       **result,'action':audit,'node':i,'phase':r,'orientation':eta,'pair':pair(r,i,eta),
                       'energy':energy,'forecast':forecast})
    else:raise AssertionError('mission did not terminate')
    return {'initial':initial,'events':events,'final':{k:events[-1][k] for k in ('kind','node','phase','orientation','pair','energy')}}

def covariance_checks():
    count=0
    for gu in range(-2,3):
      for gv in range(-2,3):
        gg=gcd(abs(gu),abs(gv)); pu,pv=(gu//gg,gv//gg) if gg else (1,0)
        for au in range(-4,5):
          for av in range(-4,5):
            q=(au*(1+pu*pu)*gu,av*(1+pv*pv)*gv)
            qr=(au*(1+pu*pu)*gu,av*(1+(-pv)**2)*(-gv))
            assert qr==(q[0],-q[1]); m=max(map(abs,q));assert m<=40
            for eu,ev in DIRS:
                p=m-q[0]*eu-q[1]*ev;pr=m-qr[0]*eu-qr[1]*(-ev)
                assert p==pr and 0<=p<=80;count+=1
    for r in range(256):
      for eta in (0,1):
        t=((-r)%256 if eta else r); mr=(-r)%256;me=eta^1
        assert ((-mr)%256 if me else mr)==t
        for tau in (0,1):
          for delta in range(256):
            nr=(r+(-1 if eta else 1)*delta)%256;nr=(-nr)%256 if tau else nr;ne=eta^tau
            assert ((-nr)%256 if ne else nr)==(t+delta)%256
    return {'local_product_direction_checks':count,'phase_mirror_cases':512,'phase_transport_cases':262144,
            'all_signed_gains':True,'all_bounded_gradients':True}

counter=None
for start in range(N):
  if counter:break
  for target in range(N):
    if counter:break
    if start==target:continue
    for phase in (0,32,64,96,128,160,192,224,250):
        good=route(start,target,phase,{},max_hops=12);bad=route(start,target,phase,{},max_hops=12,collapse=True)
        if (good['cost'],good['paths'])!=(bad['cost'],bad['paths']):
            verify_by_layers(start,target,phase,{},good,max_hops=12)
            counter={'start':start,'target':target,'initial_intrinsic_phase':phase,'max_hops':12,
                     'correct_state_key':['node','intrinsic_phase','hops'],'incorrect_state_key':['node','hops'],
                     'correct':good,'incorrect':bad};break
assert counter is not None
result={'format':'hadamard-independent-formal-reference-v1',
        'provenance':'Independent quotient arithmetic, BFS, integer lane operations, phase-state Dijkstra, layered-DP cross-check; imports no solvefinite module.',
        'recipe':{'width':W,'height':H,'center':CENTER,'radius':RADIUS,'turns':list(TURNS)},
        'binding':{'format':'hadamard-klein-routing-v1','gains':[list(p) for p in GAINS]},
        'field':list(PHI),'gradient':[list(p) for p in GRAD],'psi':[list(p) for p in PSI],
        'mission':mission(), 'phase_ablations':{str(p):mission(p) for p in (0,64,128,192)},
        'zero_gain_ablation':mission(gains=((0,0),)*4),'phase_state_counterexample':counter,
        'covariance':covariance_checks(),
        'expansion_rule':'Count every non-stale, non-target popped (node,t,hops) label whose outgoing edges are inspected; reverse hop-distance pruning; lexicographic canonical-name route ties.'}
out=Path('output/hadamard-formal-reference.json');out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({'output':str(out),'mission':[(e['cycle'],e['kind'],e['route'],e['cost'],e['pair'],e['energy'],e.get('expansions')) for e in result['mission']['events']],
                  'ablation_first':{k:(v['events'][0]['route'],v['events'][0]['cost']) for k,v in result['phase_ablations'].items()},
                  'counterexample':counter,'covariance':result['covariance']},indent=2))
