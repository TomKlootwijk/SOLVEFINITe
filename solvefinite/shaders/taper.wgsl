// DP2-DP9: typed taper instruction texture and prior-field interpreter.
// config: N,W,H,tape_length,step_bound,ball_bound,stack_bound,start_left,
// start_right,turns[3],gains[8],encoded_length,site_limit,expected_sites,scan_stride.
// Primitives, local frames, projected occupancy and signs are device outputs.
@group(0) @binding(0) var<storage, read> cfg: array<u32>;
@group(0) @binding(1) var<storage, read> prior: array<i32>;
@group(0) @binding(2) var tape: texture_2d<u32>;
@group(0) @binding(3) var moves: texture_2d<u32>;
@group(0) @binding(4) var move_target: texture_storage_2d<r32uint, write>;
@group(0) @binding(5) var<storage, read_write> traces: array<u32>;
@group(0) @binding(6) var<storage, read_write> segments: array<u32>;
@group(0) @binding(7) var<storage, read_write> primitives: array<u32>;
@group(0) @binding(8) var<storage, read_write> status: array<u32>;
@group(0) @binding(9) var<storage, read_write> signs: array<i32>;
@group(0) @binding(10) var<storage, read_write> occupancy: array<atomic<u32>>;
const NONE: u32 = 0xffffffffu;
fn packed(r:u32,g:u32,b:i32,a:u32)->u32 {
    let x=(r&255u)|((g&255u)<<8u)|((bitcast<u32>(b)&255u)<<16u)|((a&127u)<<24u);
    return x|((countOneBits(x)&1u)<<31u);
}
fn field(w:u32)->i32 { let b=(w>>16u)&255u; return select(i32(b),i32(b)-256,b>=128u); }
fn mirrored(w:u32)->u32 { return packed((256u-(w&255u))&255u,(w>>8u)&255u,field(w),((w>>24u)&127u)^16u); }
fn cls(b:i32)->u32 { return select(select(1u,2u,b>0),0u,b<0); }
// Direction order is u+,v+,u-,v-. The seam bit is independent of phase.
fn neighbor(n:u32,d:u32)->vec2<u32> {
    let w=cfg[1]; let h=cfg[2]; let u=n/h; let v=n%h;
    if d==0u { if u+1u==w { return vec2<u32>((h-v)%h,1u); } return vec2<u32>((u+1u)*h+v,0u); }
    if d==2u { if u==0u { return vec2<u32>((w-1u)*h+(h-v)%h,1u); } return vec2<u32>((u-1u)*h+v,0u); }
    if d==1u { return vec2<u32>(u*h+(v+1u)%h,0u); }
    return vec2<u32>(u*h+(v+h-1u)%h,0u);
}
@compute @workgroup_size(64)
fn compile_movements(@builtin(global_invocation_id) id:vec3<u32>) {
    if id.x>=4u*cfg[0] { return; }
    let n=id.x/4u; let d=id.x%4u; let dest=neighbor(n,d);
    let op=packed(cfg[9u+cls(prior[n])],dest.x,prior[dest.x],1u|(dest.y<<6u));
    textureStore(move_target,vec2<i32>(i32(d),i32(n)),vec4<u32>(op,0u,0u,0u));
}
fn score(n:u32,bank:u32,d:u32)->i32 {
    let gu=prior[neighbor(n,0u).x]-prior[neighbor(n,2u).x];
    let gv=prior[neighbor(n,1u).x]-prior[neighbor(n,3u).x];
    var a=abs(gu); var b=abs(gv);
    loop { if b==0 { break; } let z=a%b; a=b; b=z; }
    var pu=1; var pv=0;
    if a!=0 { pu=gu/a; pv=gv/a; }
    let qu=bitcast<i32>(cfg[12u+2u*bank])*(1+pu*pu)*gu;
    let qv=bitcast<i32>(cfg[13u+2u*bank])*(1+pv*pv)*gv;
    if d==0u { return qu; } if d==1u { return qv; }
    if d==2u { return -qu; } return -qv;
}
fn good_instruction(w:u32)->bool {
    if (w&0x70ff0000u)!=0u || (countOneBits(w)&1u)!=0u { return false; }
    let op=(w>>24u)&15u; let arg=w&65535u;
    if op>10u { return false; }
    if op>=8u { return arg>=1u; }
    if op==0u { return arg>=1u && arg<=256u; }
    if op==1u || op==2u { return arg>=1u && arg<=16u; }
    if op==5u { return arg>=1u && arg<=127u; }
    if op==7u { return arg<=4u; }
    return arg==0u;
}
fn direction(word:u32)->u32 {
    let node=(word>>8u)&255u; let eta=(word>>28u)&1u; let r=word&255u;
    let bank=select(r,(256u-r)&255u,eta!=0u)>>6u;
    var chosen=bank; var best=score(node,bank,chosen);
    for(var k=1u;k<4u;k+=1u) {
        let candidate=(bank+k)%4u; let value=score(node,bank,candidate);
        if value>best { chosen=candidate; best=value; }
    }
    return chosen;
}
@compute @workgroup_size(1)
fn interpret() {
    for(var i=0u;i<16u;i+=1u) { status[i]=0u; }
    let original=cfg[7]; let metadata=(original>>24u)&127u; let start=(original>>8u)&255u;
    if cfg[0]<9u || cfg[0]>256u || cfg[1]<3u || cfg[2]<3u || cfg[1]>85u || cfg[2]>85u
       || cfg[1]*cfg[2]!=cfg[0] || cfg[3]==0u || cfg[3]>1024u || cfg[4]>4096u
       || cfg[5]==0u || cfg[5]>64u || cfg[6]>32u || cfg[20]==0u || cfg[20]>1152u
       || cfg[21]==0u || cfg[21]>16777216u || cfg[22]>cfg[21]
       || start>=cfg[0] || (metadata!=6u && metadata!=22u)
       || (countOneBits(original)&1u)!=0u || mirrored(original)!=cfg[8] {
        status[0]=1u; return;
    }
    if field(original)!=prior[start] { status[0]=2u; return; }
    var word=packed(original&255u,start,prior[start],1u|(metadata&16u));
    var radius=1u; var scale=0u; var depth=0u; var top=NONE;
    var stack:array<vec4<u32>,32>; var parents:array<u32,32>;
    var ns=0u; var np=0u; var texel=0u; var sites=0u;
    for(var pc=0u;pc<cfg[3];pc+=1u) {
        if texel>=cfg[20] { status[0]=11u; return; }
        let instruction=textureLoad(tape,vec2<i32>(i32(texel),0),0).r;
        if !good_instruction(instruction) { status[0]=3u; return; }
        texel+=1u;
        let op=(instruction>>24u)&15u; let arg=instruction&65535u;
        if op==9u || op==10u { status[0]=12u; return; }
        if op==0u {
            let count=arg<<scale;
            if count>cfg[4]-ns { status[0]=4u; return; }
            for(var j=1u;j<=count;j+=1u) {
                let n=(word>>8u)&255u; let eta=(word>>28u)&1u; let r=word&255u;
                let dir=direction(word);
                let movement=textureLoad(moves,vec2<i32>(i32(dir),i32(n)),0).r;
                let dest=neighbor(n,dir); let delta=cfg[9u+cls(prior[n])];
                if movement!=packed(delta,dest.x,prior[dest.x],1u|(dest.y<<6u)) { status[0]=5u; return; }
                let departure=select(r+delta,r+256u-delta,eta!=0u)&255u;
                let next_r=select(departure,(256u-departure)&255u,dest.y!=0u);
                word=packed(next_r,dest.x,prior[dest.x],1u|((eta^dest.y)<<4u));
                let o=8u*ns; segments[o]=pc; segments[o+1u]=j; segments[o+2u]=top; segments[o+3u]=depth;
                segments[o+4u]=word; segments[o+5u]=mirrored(word); segments[o+6u]=0u; segments[o+7u]=0u; ns+=1u;
            }
        } else if op==1u || op==2u {
            let n=(word>>8u)&255u; let eta=(word>>28u)&1u;
            var delta=i32(arg*cfg[9u+cls(prior[n])]);
            if op==2u { delta=-delta; } if eta!=0u { delta=-delta; }
            word=packed(bitcast<u32>(i32(word&255u)+delta)&255u,n,prior[n],1u|(eta<<4u));
        } else if op==3u {
            if depth>=cfg[6] || depth>=32u { status[0]=6u; return; }
            stack[depth]=vec4<u32>(word,mirrored(word),radius,scale); parents[depth]=top;
            depth+=1u; top=pc;
        } else if op==4u {
            if depth==0u { status[0]=7u; return; }
            depth-=1u; let frame=stack[depth]; word=frame.x; radius=frame.z; scale=frame.w; top=parents[depth];
            if frame.y!=mirrored(word) { status[0]=8u; return; }
        } else if op==5u { radius=arg;
        } else if op==6u {
            let effective=radius<<scale;
            if effective>127u || np>=cfg[5] || cfg[0]>cfg[21]-sites { status[0]=9u; return; }
            let o=12u*np; primitives[o]=0u; primitives[o+1u]=pc; primitives[o+2u]=top; primitives[o+3u]=depth;
            primitives[o+4u]=(word>>8u)&255u; primitives[o+5u]=effective;
            primitives[o+6u]=0u; primitives[o+7u]=0u; primitives[o+8u]=0u;
            primitives[o+9u]=word; primitives[o+10u]=mirrored(word); primitives[o+11u]=sites;
            sites+=cfg[0]; np+=1u;
        } else if op==7u { scale=arg;
        } else {
            if cfg[20]-texel<2u || np>=cfg[5] { status[0]=13u; return; }
            let wp=textureLoad(tape,vec2<i32>(i32(texel),0),0).r;
            let wq=textureLoad(tape,vec2<i32>(i32(texel+1u),0),0).r;
            if !good_instruction(wp) || !good_instruction(wq)
               || ((wp>>24u)&15u)!=9u || ((wq>>24u)&15u)!=10u { status[0]=14u; return; }
            texel+=2u;
            let p=wp&65535u; let q=wq&65535u;
            var ga=p; var gb=q;
            loop { if gb==0u { break; } let remainder=ga%gb; ga=gb; gb=remainder; }
            if ga!=1u || arg>(2147483647u>>scale) { status[0]=15u; return; }
            let extent=arg<<scale;
            if p>2147483647u/extent { status[0]=16u; return; }
            let p_extent=p*extent; let transverse=p_extent/q;
            if transverse!=0u && q>2147483647u/transverse { status[0]=17u; return; }
            if extent>2147483647u-transverse
               || max(cfg[1]-1u,cfg[2]-1u)>2147483647u-(extent+transverse) { status[0]=18u; return; }
            let remaining=cfg[21]-sites;
            if remaining==0u || transverse>(remaining-1u)/2u { status[0]=19u; return; }
            let span=2u*transverse+1u;
            if extent>=remaining || extent+1u>remaining/span { status[0]=20u; return; }
            let tested=(extent+1u)*span;
            let o=12u*np; primitives[o]=1u; primitives[o+1u]=pc; primitives[o+2u]=top; primitives[o+3u]=depth;
            primitives[o+4u]=(word>>8u)&255u; primitives[o+5u]=extent;
            primitives[o+6u]=p; primitives[o+7u]=q; primitives[o+8u]=direction(word);
            primitives[o+9u]=word; primitives[o+10u]=mirrored(word); primitives[o+11u]=sites;
            sites+=tested; np+=1u;
        }
        let o=8u*pc; traces[o]=pc; traces[o+1u]=top; traces[o+2u]=depth; traces[o+3u]=word;
        traces[o+4u]=mirrored(word); traces[o+5u]=radius; traces[o+6u]=scale; traces[o+7u]=0u;
        status[1]=pc+1u;
    }
    if depth!=0u || np==0u || texel!=cfg[20] { status[0]=10u; return; }
    status[2]=ns; status[3]=np; status[4]=word; status[5]=mirrored(word);
    status[6]=radius; status[7]=scale; status[8]=depth; status[9]=top;
    status[10]=sites; status[11]=texel;
}
// Here -H < x < 2H. Translate into a positive representative before the
// unsigned remainder, so the device never needs a negative remainder here.
fn cyclic(x:i32,h:i32)->i32 { let z=i32(u32(x+2*h)%u32(h)); return min(z,h-z); }
fn floor_mod(x:i32,h:i32)->i32 {
    if x>=0 { return i32(u32(x)%u32(h)); }
    let r=u32(-x)%u32(h);
    return select(h-i32(r),0,r==0u);
}
fn project(x:i32,y:i32)->u32 {
    let w=i32(cfg[1]); let h=i32(cfg[2]);
    // Avoid x-mod(x,W), which could underflow near the negative i32 limit.
    // Use unsigned magnitudes for quotient/remainder so backend signed-mod
    // conventions cannot substitute truncation or reflected residues.
    var k=0;
    if x>=0 { k=i32(u32(x)/u32(w)); }
    else { let magnitude=u32(-x); k=-i32(magnitude/u32(w))-select(0,1,magnitude%u32(w)!=0u); }
    let u=floor_mod(x,w); let reflected=select(y,-y,(bitcast<u32>(k)&1u)!=0u);
    return u32(u*h+floor_mod(reflected,h));
}
@compute @workgroup_size(64)
fn clear_occupancy(@builtin(global_invocation_id) id:vec3<u32>) {
    if id.x<cfg[0] { atomicStore(&occupancy[id.x],0u); }
}
@compute @workgroup_size(64)
fn generate_occupancy(@builtin(global_invocation_id) id:vec3<u32>) {
    let site=id.x+id.y*cfg[23];
    if status[0]!=0u || site>=status[10] { return; }
    // Prefix offsets partition the charged rectangles. Binary search bounds
    // lookup by six comparisons even at the maximum64 primitives.
    var low=0u; var high=status[3];
    loop {
        if low+1u>=high { break; }
        let middle=(low+high)/2u;
        if primitives[12u*middle+11u]<=site { low=middle; } else { high=middle; }
    }
    let o=12u*low; let local=site-primitives[o+11u];
    let node=primitives[o+4u]; let extent=primitives[o+5u];
    let h=i32(cfg[2]); let a=i32(node)/h; let b=i32(node)%h;
    if primitives[o]==0u {
        let u=i32(local)/h; let v=i32(local)%h; let du=abs(u-a);
        let distance=min(du+cyclic(v-b,h),i32(cfg[1])-du+cyclic(v+b,h));
        if distance<=i32(extent) { atomicOr(&occupancy[local],1u); }
        return;
    }
    let p=primitives[o+6u]; let q=primitives[o+7u]; let dir=primitives[o+8u];
    let bound=p*extent/q; let span=2u*bound+1u;
    let s=local/span; let t=i32(local%span)-i32(bound);
    if q*u32(abs(t))>p*s { return; }
    var e=vec2<i32>(0,0);
    if dir==0u { e=vec2<i32>(1,0); } else if dir==1u { e=vec2<i32>(0,1); }
    else if dir==2u { e=vec2<i32>(-1,0); } else { e=vec2<i32>(0,-1); }
    let eta=(primitives[o+9u]>>28u)&1u;
    let f=vec2<i32>(-e.y,e.x)*select(1,-1,eta!=0u);
    let projected=project(a+i32(s)*e.x+t*f.x,b+i32(s)*e.y+t*f.y);
    atomicOr(&occupancy[projected],1u);
}
@compute @workgroup_size(64)
fn generate_signs(@builtin(global_invocation_id) id:vec3<u32>) {
    if id.x>=cfg[0] { return; }
    if atomicLoad(&occupancy[id.x])==0u { signs[id.x]=1; return; }
    for(var d=0u;d<4u;d+=1u) {
        if atomicLoad(&occupancy[neighbor(id.x,d).x])==0u { signs[id.x]=0; return; }
    }
    signs[id.x]=-1;
}
