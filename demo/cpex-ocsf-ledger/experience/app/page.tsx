'use client';

import { AnimatePresence, motion } from 'motion/react';
import Image from 'next/image';
import { useEffect, useMemo, useState } from 'react';
import { ProofFlow } from './components/ProofFlow';

type Mode = 'slides' | 'journey' | 'close';

const slides = [
  { kicker:'A BUSINESS STORY ABOUT AUTONOMOUS ACTION', title:'The $100 Agent', accent:'Give AI authority. Not unlimited trust.', body:'An operations agent can act at machine speed—inside a mandate the business can explain, enforce, and prove.', visual:'mandate' },
  { kicker:'THE ORDINARY WORLD', title:'At 2:13 AM, waiting is expensive.', accent:'The incident needs capacity now.', body:'A human approver is offline. The agent can solve the problem, but the company cannot hand it an open wallet.', visual:'clock' },
  { kicker:'THE CALL TO ADVENTURE', title:'Move fast without losing control.', accent:'Authorize the mission, not the machine.', body:'Alice delegates a narrow mandate: $100, approved vendors, spend scope, 30-minute expiry.', visual:'terms' },
  { kicker:'THE THRESHOLD', title:'Authority becomes executable policy.', accent:'Identity says who. Policy says whether. Evidence proves what happened.', body:'Three independent projects meet through open contracts—not shared implementation.', visual:'partners' },
  { kicker:'THE ORDEAL', title:'The agent asks for $30 more.', accent:'Only $15 remains.', body:'The policy engine stops the purchase before money moves. The denied attempt becomes signed evidence, not a missing log line.', visual:'deny' },
  { kicker:'THE ABYSS', title:'Then the policy plugin crashes.', accent:'The system fails closed.', body:'The panic becomes a terminal deny and still reaches the audit sink. Failure does not become permission.', visual:'panic' },
  { kicker:'THE RETURN', title:'Trust the proof, not the storyteller.', accent:'Every decision becomes portable evidence.', body:'An offline verifier proves signatures, continuity, identity, correlation, and durable ledger integrity. Rev 2 proves the pipeline today; Rev 3 will replace the staged panic record with the real path.', visual:'proof' },
  { kicker:'THE LIVE JOURNEY', title:'Let’s watch the mandate work.', accent:'The business outcome first. The cryptography when it matters.', body:'Run the executive cut or step through the full evidence journey.', visual:'launch' },
];

const journey = [
  { phase:'THE MENTOR’S GIFT', title:'Alice grants bounded authority', summary:'agent-7 receives a $100 emergency procurement mandate.', amount:0, balance:100, status:'AUTHORIZED', tone:'blue', detail:'Scope: spend · approved catalog only · TTL: 30 minutes', stream:'—', evidence:'Mandate signed' },
  { phase:'CROSSING THE THRESHOLD', title:'Purchase 01 · capacity credit', summary:'The agent buys $40 of approved emergency capacity.', amount:40, balance:60, status:'ALLOWED', tone:'green', detail:'Mandate valid · vendor approved · $40 ≤ $100', stream:'gw-1/boot-7 · 41', evidence:'OCSF signed · ledger position 1' },
  { phase:'TESTS AND ALLIES', title:'Purchase 02 · observability pack', summary:'A second $45 purchase is allowed. The running total reaches $85.', amount:45, balance:15, status:'ALLOWED', tone:'green', detail:'Cumulative spend: $85 · remaining authority: $15', stream:'gw-1/boot-7 · 42', evidence:'OCSF signed · ledger position 2' },
  { phase:'THE ORDEAL', title:'Purchase 03 · over the limit', summary:'The agent requests $30. Policy denies it before money moves.', amount:30, balance:15, status:'DENIED', tone:'red', detail:'Requested total: $115 · mandate cap: $100 · violation: spend_limit', stream:'gw-1/boot-7 · 43', evidence:'Blocked + signed denial' },
  { phase:'THE ABYSS', title:'The policy plugin panics', summary:'A real plugin panic is contained and becomes a terminal deny.', amount:0, balance:15, status:'FAIL-CLOSED', tone:'amber', detail:'catch_unwind → plugin_panic → finalized deny → audit sink', stream:'decision · fresh epoch', evidence:'Real path live · Rev 3 evidence pending' },
  { phase:'DEATH AND REBIRTH', title:'The gateway dies mid-stream', summary:'The process restarts. The new producer tells the truth about its new identity.', amount:0, balance:15, status:'RECOVERED', tone:'blue', detail:'Two streams remain independently dense; no stamps are rewritten.', stream:'new epoch · seq 1', evidence:'agent-7 + run correlation survive' },
  { phase:'THE REWARD', title:'The evidence converges', summary:'Identity and run correlation join every decision across both producer lifecycles.', amount:0, balance:15, status:'CORRELATED', tone:'green', detail:'agent-7: 6 records · run-4bf92f35: 6 records · request ID: Beat 05 only', stream:'2 streams', evidence:'1 durable cpex.decision chain' },
  { phase:'RETURN WITH THE ELIXIR', title:'A third party verifies the truth', summary:'No gateway, plugin, or ledger operator must be trusted to tell the story.', amount:0, balance:15, status:'PROVEN', tone:'green', detail:'Rev 2: 6/6 signatures · 0 gaps · chain valid · offline verification', stream:'accepted Rev 2 bundle', evidence:'Rev 3 swaps in the real panic record' },
];

function Brands() {
  return <header className="brand-bar"><Image src="/logos/redhat.svg" width={138} height={46} alt="Red Hat" className="logo redhat"/><span className="brand-divider"/><Image src="/logos/ibm.png" width={84} height={34} alt="IBM" className="logo ibm"/><span className="brand-divider"/><span className="ai-brand"><Image src="/logos/ai-identity.svg" width={25} height={25} alt=""/>AI Identity</span><span className="demo-name">Verdict to Proof</span></header>;
}

function SlideVisual({ kind }: { kind:string }) {
  if (kind === 'clock') return <div className="big-visual"><span className="clock">02:13</span><small>INCIDENT ACTIVE · APPROVER OFFLINE</small></div>;
  if (kind === 'terms') return <div className="term-grid"><span><b>$100</b>Spend cap</span><span><b>30m</b>Time to live</span><span><b>1</b>Approved catalog</span></div>;
  if (kind === 'partners') return <div className="partner-stack"><span><b>01</b> AI Identity · authority</span><span><b>02</b> IBM CPEX / Praxis · policy</span><span><b>03</b> OCSF · portable evidence</span><span><b>04</b> Red Hat · durable proof</span></div>;
  if (kind === 'deny') return <div className="limit-visual"><div><span>$85</span><small>CONSUMED</small></div><i>+</i><div className="danger"><span>$30</span><small>REQUESTED</small></div><strong>DENIED</strong></div>;
  if (kind === 'panic') return <div className="panic-visual"><span>PLUGIN PANIC</span><motion.i animate={{ opacity:[.2,1,.2] }} transition={{ repeat:Infinity,duration:1.2 }}/><strong>DENY + EVIDENCE</strong></div>;
  if (kind === 'proof') return <div className="proof-stats"><span><b>6/6</b>signatures</span><span><b>0</b>gaps</span><span><b>1</b>valid chain</span></div>;
  if (kind === 'launch') return <div className="launch-visual"><span>ALLOW</span><span>OVER-LIMIT DENY</span><span>FAIL-CLOSED PANIC</span><strong>OFFLINE PROOF</strong></div>;
  return <MandateCard/>;
}

function MandateCard() {
  return <aside className="mandate-card"><div className="agent-orb">A7</div><div><p className="micro-label">DELEGATED AUTHORITY</p><h3>agent-7</h3></div><div className="mandate-amount">$100</div><dl><div><dt>Scope</dt><dd>Emergency procurement</dd></div><div><dt>Vendor</dt><dd>Approved catalog only</dd></div><div><dt>Expires</dt><dd>30 minutes</dd></div></dl><span className="signed-chip">Cryptographically signed</span></aside>;
}

export default function Home() {
  const [mode,setMode] = useState<Mode>('slides');
  const [slide,setSlide] = useState(0);
  const [step,setStep] = useState(0);
  const [auto,setAuto] = useState(false);
  const current = journey[step];
  const spent = useMemo(() => 100-current.balance,[current.balance]);

  useEffect(() => {
    if (!auto || mode !== 'journey') return;
    const timer = setTimeout(() => {
      if (step >= journey.length - 1) {
        setAuto(false);
        setMode('close');
        return;
      }
      const next = step + 1;
      setStep(next);
    }, 2600);
    return () => clearTimeout(timer);
  }, [auto, mode, step]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'ArrowRight') {
        if (mode === 'slides') {
          if (slide < slides.length - 1) setSlide(slide + 1);
          else setMode('journey');
        } else {
          setStep(Math.min(journey.length - 1, step + 1));
        }
      }
      if (event.key === 'ArrowLeft') {
        if (mode === 'slides') setSlide(Math.max(0, slide - 1));
        else setStep(Math.max(0, step - 1));
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [mode, slide, step]);

  if (mode === 'slides') {
    const item=slides[slide];
    return <main className="stage"><Brands/><div className="story-index">{slides.map((_,i)=><button key={i} className={i===slide?'active':''} onClick={()=>setSlide(i)} aria-label={`Go to slide ${i+1}`}/>)}</div><section className="hero-shell"><AnimatePresence mode="wait"><motion.div key={slide} className="hero-copy" initial={{opacity:0,y:28}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-18}} transition={{duration:.45}}><p className="eyebrow">{item.kicker}</p><h1>{item.title}</h1><h2>{item.accent}</h2><p className="lede">{item.body}</p></motion.div></AnimatePresence><motion.aside key={`${slide}-visual`} className="visual-shell" initial={{opacity:0,x:34}} animate={{opacity:1,x:0}} transition={{delay:.18,duration:.45}}><SlideVisual kind={item.visual}/></motion.aside></section><footer className="stage-footer"><button className="ghost" disabled={slide===0} onClick={()=>setSlide(Math.max(0,slide-1))}>← Back</button><span>{slide+1} / {slides.length}</span><button className="primary" onClick={()=>slide===slides.length-1?setMode('journey'):setSlide(slide+1)}>{slide===slides.length-1?'Enter the live journey':'Next →'}</button></footer></main>;
  }

  if (mode === 'close') {
    return <main className="stage close-stage"><Brands/><section className="close-shell"><motion.div className="close-copy" initial={{opacity:0,y:24}} animate={{opacity:1,y:0}} transition={{duration:.55}}><p className="eyebrow">RETURN WITH THE ELIXIR</p><h1>Move at machine speed.<br/><span>Keep human accountability.</span></h1><p className="lede">The agent completed the mission inside a business mandate. Policy stopped what exceeded it. Failure denied safely. Independent proof survived the systems that produced it.</p><div className="close-outcomes"><span><b>MOVE</b>Autonomous action</span><span><b>CONTROL</b>Bounded authority</span><span><b>PROVE</b>Portable evidence</span></div></motion.div><motion.aside className="close-mark" initial={{opacity:0,scale:.9}} animate={{opacity:1,scale:1}} transition={{delay:.2,duration:.55}}><div className="close-ring"><span>$100</span><small>MISSION<br/>COMPLETE</small></div><p>AI Identity grants the mandate.<br/>IBM policy enforces it.<br/>Red Hat makes the evidence durable.</p></motion.aside></section><footer className="stage-footer close-footer"><span>THE $100 AGENT · VERDICT TO PROOF</span><button className="primary" onClick={()=>{setMode('slides');setSlide(0);setStep(0);setAuto(false)}}>Run again ↻</button></footer></main>;
  }

  return <main className="journey-stage"><Brands/><div className="journey-progress">{journey.map((item,i)=><button key={item.phase} onClick={()=>{setStep(i);setAuto(false)}} className={i===step?'active':i<step?'done':''}><span>{String(i+1).padStart(2,'0')}</span>{item.phase}</button>)}</div><section className="journey-grid"><div className="outcome-panel"><AnimatePresence mode="wait"><motion.div key={step} initial={{opacity:0,y:16}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-12}}><p className="eyebrow">{current.phase}</p><div className={`status-pill ${current.tone}`}>{current.status}</div><h1>{current.title}</h1><p className="journey-summary">{current.summary}</p><div className="transaction-card"><div><small>REQUEST</small><strong>{current.amount?`$${current.amount}`:'—'}</strong></div><div><small>SPENT</small><strong>${spent}</strong></div><div><small>REMAINING</small><strong className={current.balance<=15?'warn':''}>${current.balance}</strong></div></div><div className="spend-track"><motion.span animate={{width:`${spent}%`}} transition={{duration:.7}}/><i style={{left:'100%'}}>CAP</i></div><p className="decision-detail">{current.detail}</p><div className="evidence-row"><span><small>PRODUCER</small>{current.stream}</span><span><small>EVIDENCE</small>{current.evidence}</span></div></motion.div></AnimatePresence></div><div className="proof-panel"><ProofFlow activeIndex={step}/><div className="proof-caption"><span>BUSINESS JOIN</span><b>agent-7</b><i>+</i><b>run-4bf92f35</b><small>Identity and conversation survive process and stream boundaries.</small></div></div></section><footer className="journey-footer"><button className="ghost" onClick={()=>{setMode('slides');setSlide(slides.length-1);setAuto(false)}}>← Presentation</button><div className="journey-controls"><button className="ghost" disabled={step===0} onClick={()=>{setStep(Math.max(0,step-1));setAuto(false)}}>Back</button><span>{step+1} / {journey.length}</span><button className={auto?'pause':'primary'} onClick={()=>setAuto(!auto)}>{auto?'Pause':'Run story'}</button><button className="primary" onClick={()=>{if(step===journey.length-1)setMode('close');else setStep(step+1);setAuto(false)}}>{step===journey.length-1?'Close →':'Next →'}</button></div></footer></main>;
}
