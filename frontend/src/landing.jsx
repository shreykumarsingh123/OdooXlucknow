import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from './api'
import './landing.css'
import { label, money } from './ui'

const calm = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

function useReveal() {
  const root = useRef(null)
  useEffect(() => {
    const seen = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('in')
          seen.unobserve(entry.target)
        }
      })
    }, { threshold: 0.12 })
    const watch = () => root.current?.querySelectorAll('.reveal:not(.in)').forEach((node) => seen.observe(node))
    watch()
    // Pricing cards arrive after the page does.
    const later = new MutationObserver(watch)
    if (root.current) later.observe(root.current, { childList: true, subtree: true })
    return () => { seen.disconnect(); later.disconnect() }
  }, [])
  return root
}

function CountUp({ to, format = (v) => v }) {
  const [value, setValue] = useState(calm() ? to : 0)
  useEffect(() => {
    if (calm()) return undefined
    let frame
    const began = performance.now()
    const tick = (now) => {
      const t = Math.min((now - began) / 1400, 1)
      setValue(to * (1 - (1 - t) ** 3))
      if (t < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [to])
  return <>{format(value)}</>
}

const SAMPLE_FEED = [
  ['good', 'Invoice paid', 'Online by card'],
  ['info', 'Billing run finished', 'Nothing billed twice'],
  ['good', 'Trial converted', 'First invoice created'],
  ['warn', 'Reminder sent', 'Invoice 6 days overdue'],
  ['info', 'Plan upgraded', 'Difference prorated'],
  ['good', 'Promo code applied', 'On the next invoice'],
]

function Feed() {
  const [index, setIndex] = useState(0)
  useEffect(() => {
    if (calm()) return undefined
    const timer = setInterval(() => setIndex((i) => (i + 1) % SAMPLE_FEED.length), 2600)
    return () => clearInterval(timer)
  }, [])
  const [tone, title, note] = SAMPLE_FEED[index]
  return (
    <div className="feed" key={index}>
      <span className={`dot ${tone}`} aria-hidden="true" />
      <div><b>{title}</b><small>{note}</small></div>
    </div>
  )
}

const LINE = 'M0 96 C 34 92, 50 78, 84 76 S 136 84, 168 60 S 226 52, 258 38 S 312 30, 340 12'

function HeroMock() {
  const frame = useRef(null)
  const tilt = (event) => {
    if (calm() || !frame.current) return
    const box = frame.current.getBoundingClientRect()
    frame.current.style.setProperty('--ry', `${((event.clientX - box.left) / box.width - 0.5) * 7}deg`)
    frame.current.style.setProperty('--rx', `${((event.clientY - box.top) / box.height - 0.5) * -7}deg`)
  }
  const level = () => {
    frame.current?.style.setProperty('--ry', '0deg')
    frame.current?.style.setProperty('--rx', '0deg')
  }
  return (
    <div className="mock-wrap" onMouseMove={tilt} onMouseLeave={level}>
      <div className="mock" ref={frame} role="img" aria-label="Sample billing dashboard showing recurring revenue rising">
        <div className="mock-bar"><i /><i /><i /><span>Finance summary</span><em>Sample data</em></div>
        <div className="mock-tiles">
          <div><span>Monthly recurring</span><strong><CountUp to={482350} format={(v) => money(Math.round(v))} /></strong></div>
          <div><span>Active subscriptions</span><strong><CountUp to={1284} format={(v) => Math.round(v).toLocaleString('en-IN')} /></strong></div>
          <div className="wide-only"><span>Overdue</span><strong className="warm"><CountUp to={36900} format={(v) => money(Math.round(v))} /></strong></div>
        </div>
        <svg viewBox="0 0 340 110" preserveAspectRatio="none" aria-hidden="true">
          <defs>
            <linearGradient id="fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#8b6fff" stopOpacity=".45" /><stop offset="1" stopColor="#8b6fff" stopOpacity="0" /></linearGradient>
          </defs>
          <path className="area" d={`${LINE} L340 110 L0 110 Z`} fill="url(#fill)" />
          <path className="line" d={LINE} pathLength="1" fill="none" stroke="#a892ff" strokeWidth="2.5" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        </svg>
      </div>
      <Feed />
    </div>
  )
}

const CAPABILITIES = ['Monthly and yearly plans', 'Product variants', 'Automatic tax', 'Free trials', 'Promo codes', 'Proration', 'Add-ons', 'Quotation templates', 'Card payments', 'Overdue reminders', 'Customer portal', 'CSV exports']

const FEATURES = [
  ['M17 2l4 4-4 4M3 11V9a3 3 0 0 1 3-3h15M7 22l-4-4 4-4M21 13v2a3 3 0 0 1-3 3H3', 'Recurring billing', 'Hundreds of invoices created on billing day, with lines, taxes and totals filled in. A database rule stops anything being billed twice.'],
  ['M4 6h16M4 12h16M4 18h10', 'Plans your way', 'Daily to yearly billing, minimum quantities, availability dates and free trials, with pause, renew and close set plan by plan.'],
  ['M3 12V3h9l9 9-9 9zM8 8h.01', 'Discounts and codes', 'Fixed or percentage, with minimums, dates and usage limits. They appear on the next invoice and stop when they run out.'],
  ['M2 6h20v13H2zM2 10h20M6 15h4', 'Get paid', 'Customers pay online by card. The team records bank, UPI, cash and cheque payments against the right invoice.'],
  ['M12 8v4l3 2M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20', 'Keep customers', 'Offer a pause before someone cancels, learn why people leave, and chase overdue invoices with spaced reminders.'],
  ['M3 13h7V3H3zM14 21h7V11h-7zM14 7h7V3h-7zM3 21h7v-4H3z', 'Know your numbers', 'Recurring revenue, churn, overdue aging and revenue by plan in one view, with filters and CSV exports.'],
]

const SCENES = [
  ['Signing up', 'A new customer creates an account in a minute, with Google or an email and a strong password. Admin, staff and customer each see only what they should.', [['Role', 'Customer'], ['Portal', 'Own records only']]],
  ['Launching a plan', 'The admin adds the product and its variants, then sets the price, the billing period, the dates and what the plan allows.', [['Brand: Odoo', '+ ₹560'], ['Bills', 'Monthly'], ['Free trial', '14 days']]],
  ['Quote to subscription', 'A sales rep starts from a template, and the offer moves from Draft to Quotation, Confirmed and Active where everyone can see it.', [['Number', 'SUB-000128'], ['Valid for', '30 days'], ['Stage', 'Confirmed']]],
  ['Billing day', 'Every subscription that is due gets its invoice. Missed periods are caught up, and running it twice creates nothing new.', [['Due today', '312'], ['Invoices created', '312'], ['Billed twice', '0']]],
  ['A better price', 'A discount or promo code lands on the next invoice by itself, and stops on its end date or usage limit.', [['Seats', '25'], ['Discount', '10% off'], ['Applied', 'Automatically']]],
  ['The money comes in', 'Each payment is recorded against its invoice, and paid, outstanding and overdue are always one click apart.', [['Paid', '84%'], ['Outstanding', '11%'], ['Overdue', '5%']]],
  ['Month end', 'The finance lead opens one page for active subscriptions, revenue, payments and overdue invoices, instead of waiting days.', [['Report built in', 'Seconds'], ['Export', 'CSV'], ['Filters', 'By date']]],
]

function Month() {
  const [active, setActive] = useState(0)
  const list = useRef(null)
  useEffect(() => {
    const spy = new IntersectionObserver((entries) => {
      entries.forEach((entry) => { if (entry.isIntersecting) setActive(Number(entry.target.dataset.index)) })
    }, { rootMargin: '-45% 0px -45% 0px' })
    list.current?.querySelectorAll('[data-index]').forEach((node) => spy.observe(node))
    return () => spy.disconnect()
  }, [])
  const [title, , rows] = SCENES[active]
  return (
    <div className="month">
      <div className="month-screen">
        <div className="progress-dots" aria-hidden="true">{SCENES.map(([name], i) => <i key={name} className={i <= active ? 'on' : ''} />)}</div>
        <div className="screen-card" key={active}>
          <small>Step {active + 1} of {SCENES.length}. Sample data</small>
          <h3>{title}</h3>
          <dl>{rows.map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl>
        </div>
      </div>
      <ol className="month-list" ref={list}>
        {SCENES.map(([name, text], i) => (
          <li key={name} data-index={i} className={i === active ? 'now' : ''}>
            <h3>{name}</h3>
            <p>{text}</p>
          </li>
        ))}
      </ol>
    </div>
  )
}

function Pricing() {
  const [plans, setPlans] = useState(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    api.get('/public/plans/').then(setPlans).catch(() => setFailed(true))
  }, [])
  if (failed) return <p className="center soft">Prices could not load just now. <Link to="/signup">Create an account</Link> to see them.</p>
  if (!plans) return <div className="plans">{[0, 1, 2].map((i) => <div className="plan skeleton" key={i} />)}</div>
  if (!plans.length) return <p className="center soft">Plans are being prepared. <Link to="/signup">Create an account</Link> to hear first.</p>
  const featured = plans.find((p) => p.trial_days > 0)?.id
  return (
    <div className="plans">
      {plans.map((plan, i) => (
        <article className={`plan reveal ${plan.id === featured ? 'featured' : ''}`} style={{ '--delay': `${i * 70}ms` }} key={plan.id}>
          {plan.id === featured && <span className="ribbon">Free trial</span>}
          <h3>{plan.name}</h3>
          <p className="price">{money(plan.price)}<small> / {label(plan.billing_period).toLowerCase().replace('ly', '').replace('dai', 'day')}</small></p>
          <ul>
            <li>{plan.trial_days ? `${plan.trial_days} days free before the first invoice` : 'Billed from the day you start'}</li>
            <li>Customer portal and online payment</li>
            <li>{plan.pausable ? 'Pause whenever you need to' : 'Switch add-ons on and off'}</li>
            {plan.min_quantity > 1 && <li>From {plan.min_quantity} seats</li>}
          </ul>
          <Link className="cta" to="/signup?next=plans">{plan.self_serve ? (plan.trial_days ? 'Start free trial' : 'Get started') : 'Talk to our team'}</Link>
        </article>
      ))}
    </div>
  )
}

const QUESTIONS = [
  ['Can an invoice be billed twice?', 'No. Each billing period has a unique key in the database, so a repeat run or a second server cannot create the same invoice again.'],
  ['What happens if I change plan mid-month?', 'The change applies straight away. An upgrade charges the difference for the days left, and a downgrade leaves a credit for your next invoices.'],
  ['Can I pause instead of cancelling?', 'Yes, where the plan allows it. You are not billed while paused, and paused time is not charged later.'],
  ['How do I pay?', 'Pay any confirmed invoice online by card, or pay by bank transfer, UPI, cash or cheque and the team records it.'],
  ['Who can see my data?', 'You see only your own subscriptions and invoices. Access is checked on the server for every request.'],
]

function Faq() {
  const [open, setOpen] = useState(0)
  return (
    <div className="faq">
      {QUESTIONS.map(([question, answer], i) => (
        <div className={`faq-row ${open === i ? 'open' : ''}`} key={question}>
          <button aria-expanded={open === i} onClick={() => setOpen(open === i ? -1 : i)}>{question}<span aria-hidden="true">+</span></button>
          <div className="faq-body"><div><p>{answer}</p></div></div>
        </div>
      ))}
    </div>
  )
}

export function Landing({ user }) {
  const root = useReveal()
  const bar = useRef(null)
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    const onScroll = () => {
      const room = document.documentElement.scrollHeight - window.innerHeight
      if (bar.current) bar.current.style.transform = `scaleX(${room > 0 ? window.scrollY / room : 0})`
      setScrolled(window.scrollY > 12)
    }
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  const start = user ? <Link className="cta" to="/">Open the app</Link> : <Link className="cta" to="/signup">Start for free</Link>
  return (
    <div className="landing" ref={root}>
      <div className="scroll-bar" ref={bar} aria-hidden="true" />
      <header className={`top ${scrolled ? 'scrolled' : ''}`}>
        <a className="brand" href="#start">Brightloop</a>
        <nav aria-label="Page sections">
          <a href="#features">Features</a>
          <a href="#month">How it works</a>
          <a href="#pricing">Pricing</a>
          <a href="#faq">Questions</a>
        </nav>
        <div className="top-actions">
          {!user && <Link className="quiet" to="/login">Sign in</Link>}
          {start}
        </div>
      </header>

      <main>
        <section className="hero" id="start">
          <div className="aurora" aria-hidden="true"><i /><i /><i /></div>
          <div className="hero-copy">
            <p className="eyebrow rise">Subscription management</p>
            <h1 className="rise r2">Recurring revenue that runs <span>itself.</span></h1>
            <p className="lead rise r3">Plans, quotations, invoices, payments and revenue reports in one place. Built for a business that earns every month, not just once.</p>
            <div className="hero-actions rise r4">
              {start}
              <a className="ghost" href="#month">See a billing month</a>
            </div>
          </div>
          <div className="rise r3 hero-visual"><HeroMock /></div>
        </section>

        <div className="marquee" aria-hidden="true">
          <div>{[...CAPABILITIES, ...CAPABILITIES].map((item, i) => <span key={i}>{item}</span>)}</div>
        </div>

        <section className="band" id="features">
          <div className="heading reveal"><p className="eyebrow">Everything in one place</p><h2>Replace the spreadsheet, the reminders and the month-end scramble.</h2></div>
          <div className="features">
            {FEATURES.map(([icon, title, text], i) => (
              <article className="feature reveal" style={{ '--delay': `${i * 60}ms` }} key={title}>
                <span className="icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={icon} /></svg></span>
                <h3>{title}</h3>
                <p>{text}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="band tint" id="month">
          <div className="heading reveal"><p className="eyebrow">How it works</p><h2>One billing month, start to finish.</h2></div>
          <Month />
        </section>

        <section className="facts-band">
          {[['4', 'billing periods, daily to yearly'], ['6', 'stages, visible to the whole team'], ['0', 'invoices billed twice, by database rule'], ['< 2 s', 'target for every page, checked on 5,000 subscriptions']].map(([big, small], i) => (
            <div className="reveal" style={{ '--delay': `${i * 70}ms` }} key={small}><strong>{big}</strong><span>{small}</span></div>
          ))}
        </section>

        <section className="band" id="pricing">
          <div className="heading reveal"><p className="eyebrow">Pricing</p><h2>Live plans, ready to start today.</h2><p className="soft">Prices before tax.</p></div>
          <Pricing />
        </section>

        <section className="band tint" id="faq">
          <div className="heading reveal"><p className="eyebrow">Questions</p><h2>Good to know.</h2></div>
          <Faq />
        </section>

        <section className="closing">
          <div className="aurora" aria-hidden="true"><i /><i /></div>
          <div className="reveal">
            <h2>Stop chasing renewals. Start seeing the numbers.</h2>
            {start}
          </div>
        </section>
      </main>

      <footer className="foot-bar">
        <span className="brand">Brightloop</span>
        <nav aria-label="Footer">
          <a href="#features">Features</a>
          <a href="#pricing">Pricing</a>
          {!user && <Link to="/login">Sign in</Link>}
        </nav>
      </footer>
    </div>
  )
}
