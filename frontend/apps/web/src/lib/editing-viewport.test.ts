import { describe, expect, it } from 'vitest'
import { observeEditingViewport } from './editing-viewport'

function fixture() {
  const frames=new Map<number,FrameRequestCallback>();let id=0
  const root={style:{setProperty:()=>{},removeProperty:()=>{}},setAttribute:()=>{},removeAttribute:()=>{}}
  const viewport=Object.assign(new EventTarget(),{height:844,offsetTop:0,scale:1})
  const scroller={parentElement:null,clientHeight:160,clientTop:0,scrollHeight:700,scrollTop:0,
    getBoundingClientRect:()=>({top:148,bottom:308,height:160}),overflowY:'auto'}
  const field={isConnected:true,parentElement:scroller,matches:()=>true,closest:()=>null,
    getBoundingClientRect:()=>({top:526-scroller.scrollTop,bottom:570-scroller.scrollTop,height:44})}
  const doc=Object.assign(new EventTarget(),{documentElement:root,body:{},activeElement:null as unknown,scrollingElement:null,querySelector:()=>null})
  const win=Object.assign(new EventTarget(),{innerHeight:844,innerWidth:390,visualViewport:viewport,
    matchMedia:()=>({matches:false}),getComputedStyle:(el:unknown)=>({overflowY:(el as typeof scroller).overflowY || 'visible'}),
    requestAnimationFrame:(fn:FrameRequestCallback)=>{frames.set(++id,fn);return id},cancelAnimationFrame:(key:number)=>frames.delete(key)})
  const flush=()=>{for(let n=0;n<4 && frames.size;n++){const batch=[...frames.values()];frames.clear();batch.forEach(fn=>fn(n))}}
  return {win,doc,field,scroller,viewport,flush,frames}
}

describe('editing viewport focus visibility',()=>{
  it('reveals the existing focused field after a tap ends when keyboard resize occurred during that tap, without typing',()=>{
    const f=fixture();const stop=observeEditingViewport(f.win as unknown as Window,f.doc as unknown as Document)
    f.doc.activeElement=f.field;f.scroller.scrollTop=274
    f.doc.dispatchEvent(new Event('focusin'));f.flush()
    f.doc.dispatchEvent(new Event('pointerdown'));f.doc.dispatchEvent(new Event('touchstart'))
    f.scroller.scrollTop=0;f.viewport.height=350;f.viewport.offsetTop=52
    f.viewport.dispatchEvent(new Event('resize'));f.flush()
    expect(f.scroller.scrollTop).toBe(0)
    f.doc.dispatchEvent(new Event('pointerup'));f.doc.dispatchEvent(new Event('touchend'));f.flush()
    expect(f.field.getBoundingClientRect().bottom).toBeLessThanOrEqual(296)
    stop()
  })
  it('rechecks the currently focused input after a delayed keyboard/layout resize',()=>{
    const f=fixture();const stop=observeEditingViewport(f.win as unknown as Window,f.doc as unknown as Document)
    f.doc.activeElement=f.field
    f.doc.dispatchEvent(new Event('focusin'));f.flush()
    f.scroller.scrollTop=0
    f.viewport.height=350;f.viewport.offsetTop=52;f.viewport.dispatchEvent(new Event('resize'));f.flush()
    expect(f.field.getBoundingClientRect().bottom).toBeLessThanOrEqual(296)
    expect(f.field.getBoundingClientRect().top).toBeGreaterThanOrEqual(160)
    stop()
  })
  it('reads the latest focus rather than moving a previous input after focus changes',()=>{
    const f=fixture();const stop=observeEditingViewport(f.win as unknown as Window,f.doc as unknown as Document)
    f.doc.activeElement=f.field;f.doc.dispatchEvent(new Event('focusin'))
    f.doc.activeElement=null;f.flush()
    expect(f.scroller.scrollTop).toBe(0)
    stop()
  })
  it('does not fight a manual drag, already visible input or explicit zoom',()=>{
    const f=fixture();const stop=observeEditingViewport(f.win as unknown as Window,f.doc as unknown as Document)
    f.doc.activeElement=f.field
    f.doc.dispatchEvent(Object.assign(new Event('pointerdown'),{clientX:20,clientY:200}))
    f.doc.dispatchEvent(Object.assign(new Event('pointermove'),{clientX:20,clientY:250}))
    f.viewport.height=350;f.viewport.dispatchEvent(new Event('resize'));f.flush()
    expect(f.scroller.scrollTop).toBe(0)
    f.doc.dispatchEvent(new Event('pointerup'));f.flush()
    expect(f.scroller.scrollTop).toBe(0)
    f.viewport.scale=2;f.doc.dispatchEvent(new Event('focusin'));f.flush()
    expect(f.scroller.scrollTop).toBe(0)
    f.viewport.scale=1;f.scroller.scrollTop=274;f.doc.dispatchEvent(new Event('focusin'));f.flush()
    expect(f.scroller.scrollTop).toBe(274)
    stop()
  })
  it('does not move desktop fields or leave queued work after cleanup',()=>{
    const f=fixture();f.win.innerWidth=1280
    const stop=observeEditingViewport(f.win as unknown as Window,f.doc as unknown as Document)
    f.doc.activeElement=f.field;f.doc.dispatchEvent(new Event('focusin'));f.flush()
    expect(f.scroller.scrollTop).toBe(0)
    f.win.innerWidth=390;f.doc.dispatchEvent(new Event('focusin'));stop();f.flush()
    expect(f.frames.size).toBe(0)
    expect(f.scroller.scrollTop).toBe(0)
    f.viewport.dispatchEvent(new Event('resize'));f.flush();expect(f.scroller.scrollTop).toBe(0)
  })
  it('brings a nested scroll region into the page viewport before correcting its own scroll',()=>{
    const f=fixture()
    const page={scrollTop:0,scrollHeight:2000,clientHeight:844}
    Object.assign(f.doc,{scrollingElement:page})
    f.scroller.getBoundingClientRect=()=>({top:500-page.scrollTop,bottom:660-page.scrollTop,height:160})
    f.field.getBoundingClientRect=()=>({top:620-page.scrollTop-f.scroller.scrollTop,bottom:664-page.scrollTop-f.scroller.scrollTop,height:44})
    const stop=observeEditingViewport(f.win as unknown as Window,f.doc as unknown as Document)
    f.doc.activeElement=f.field;f.viewport.height=350;f.viewport.offsetTop=52
    f.viewport.dispatchEvent(new Event('resize'));f.flush()
    expect(page.scrollTop).toBeGreaterThan(0)
    expect(f.field.getBoundingClientRect().bottom).toBeLessThanOrEqual(390)
    stop()
  })
})
