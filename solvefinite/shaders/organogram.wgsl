// OG1-OG7: typed instruction texture and prior-field branching interpreter.
// config: N,W,H,tape_length,step_bound,ball_bound,stack_bound,start_left,
// start_right,turns[3],gains[8]. All geometric results are device outputs.
@group(0) @binding(0) var<storage, read> cfg: array<u32>;
@group(0) @binding(1) var<storage, read> prior: array<i32>;
@group(0) @binding(2) var tape: texture_2d<u32>;
@group(0) @binding(3) var moves: texture_2d<u32>;
@group(0) @binding(4) var move_target: texture_storage_2d<r32uint, write>;
@group(0) @binding(5) var<storage, read_write> traces: array<u32>;
@group(0) @binding(6) var<storage, read_write> segments: array<u32>;
@group(0) @binding(7) var<storage, read_write> balls: array<u32>;
@group(0) @binding(8) var<storage, read_write> status: array<u32>;
@group(0) @binding(9) var<storage, read_write> signs: array<i32>;
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
    if (w&0x78ff0000u)!=0u || (countOneBits(w)&1u)!=0u { return false; }
    let op=(w>>24u)&7u; let arg=w&65535u;
    if op==0u { return arg>=1u && arg<=256u; }
    if op==1u || op==2u { return arg>=1u && arg<=16u; }
    if op==5u { return arg>=1u && arg<=127u; }
    if op==7u { return arg<=4u; }
    return arg==0u;
}
@compute @workgroup_size(1)
fn interpret() {
    for(var i=0u;i<12u;i+=1u) { status[i]=0u; }
    let original=cfg[7]; let metadata=(original>>24u)&127u; let start=(original>>8u)&255u;
    if cfg[0]<9u || cfg[0]>256u || cfg[1]<3u || cfg[2]<3u || cfg[1]*cfg[2]!=cfg[0]
       || cfg[3]>1024u || cfg[4]>4096u || cfg[5]>64u || cfg[6]>32u
       || start>=cfg[0] || (metadata!=6u && metadata!=22u)
       || (countOneBits(original)&1u)!=0u || mirrored(original)!=cfg[8] {
        status[0]=1u; return;
    }
    if field(original)!=prior[start] { status[0]=2u; return; }
    var word=packed(original&255u,start,prior[start],1u|(metadata&16u));
    var radius=1u; var scale=0u; var depth=0u; var top=NONE;
    var stack:array<vec4<u32>,32>; var parents:array<u32,32>;
    var ns=0u; var nb=0u;
    for(var pc=0u;pc<cfg[3];pc+=1u) {
        let instruction=textureLoad(tape,vec2<i32>(i32(pc),0),0).r;
        if !good_instruction(instruction) { status[0]=3u; return; }
        let op=(instruction>>24u)&7u; let arg=instruction&65535u;
        if op==0u {
            let count=arg<<scale;
            if count>cfg[4]-ns { status[0]=4u; return; }
            for(var j=1u;j<=count;j+=1u) {
                let n=(word>>8u)&255u; let eta=(word>>28u)&1u; let r=word&255u;
                let bank=(select(r,(256u-r)&255u,eta!=0u))>>6u;
                var dir=bank; var best=score(n,bank,dir);
                for(var k=1u;k<4u;k+=1u) { let d=(bank+k)%4u; let q=score(n,bank,d); if q>best { best=q; dir=d; } }
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
            if effective>127u || nb>=cfg[5] { status[0]=9u; return; }
            let o=8u*nb; balls[o]=pc; balls[o+1u]=top; balls[o+2u]=depth; balls[o+3u]=(word>>8u)&255u;
            balls[o+4u]=effective; balls[o+5u]=word; balls[o+6u]=mirrored(word); balls[o+7u]=0u; nb+=1u;
        } else { scale=arg; }
        let o=8u*pc; traces[o]=pc; traces[o+1u]=top; traces[o+2u]=depth; traces[o+3u]=word;
        traces[o+4u]=mirrored(word); traces[o+5u]=radius; traces[o+6u]=scale; traces[o+7u]=0u;
        status[1]=pc+1u;
    }
    if depth!=0u || nb==0u { status[0]=10u; return; }
    status[2]=ns; status[3]=nb; status[4]=word; status[5]=mirrored(word);
    status[6]=radius; status[7]=scale; status[8]=depth; status[9]=top;
}
// Here -H < x < 2H. Translate into a positive representative before the
// unsigned remainder, so the device never needs a negative remainder here.
fn cyclic(x:i32,h:i32)->i32 { let z=i32(u32(x+2*h)%u32(h)); return min(z,h-z); }
@compute @workgroup_size(64)
fn generate_signs(@builtin(global_invocation_id) id:vec3<u32>) {
    if id.x>=cfg[0] { return; }
    let h=i32(cfg[2]); let w=i32(cfg[1]); let u=i32(id.x)/h; let v=i32(id.x)%h;
    var q=2147483647;
    for(var i=0u;i<status[3];i+=1u) {
        let center=i32(balls[8u*i+3u]); let a=center/h; let b=center%h; let du=abs(u-a);
        let distance=min(du+cyclic(v-b,h),w-du+cyclic(v+b,h));
        q=min(q,distance-i32(balls[8u*i+4u]));
    }
    signs[id.x]=select(select(0,1,q>0),-1,q<0);
}
