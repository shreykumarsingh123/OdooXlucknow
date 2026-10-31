import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from './api'
import './landing.css'
import { label, money, Modal } from './ui'

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

/* ------------------------------------------------------------ hero */

const SAMPLE_FEED = [
  ['good', 'Invoice paid', 'Online by card'],
  ['info', 'Billing run finished', 'Nothing billed twice'],
  ['good', 'Trial converted', 'First invoice created'],
  ['warn', 'Reminder sent', 'Invoice 6 days overdue'],
  ['info', 'Plan upgraded', 'Difference prorated'],
  ['good', 'Cancellation saved', 'Customer chose to pause'],
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
          <div><span>Active subscribers</span><strong><CountUp to={1284} format={(v) => Math.round(v).toLocaleString('en-IN')} /></strong></div>
          <div className="wide-only"><span>Saved this month</span><strong className="mint"><CountUp to={36900} format={(v) => money(Math.round(v))} /></strong></div>
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

/* ------------------------------------------------------------ content */

const CUSTOMERS = ['Harbor & Pine', 'Kestrel Labs', 'Tideline Media', 'Orbit Fitness', 'Fernway Foods', 'Acme Retail', 'Globex Industries', 'Lumen Learning']

const PILLARS = [
  ['M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6', 'Spot it early', 'Overdue invoices, expiring contracts and quiet churn surface on one screen, before they become lost revenue.'],
  ['M3 17l6-6 4 4 8-8M15 7h6v6', 'Grow on purpose', 'See which plans and customers actually earn, month by month, then double down on what works.'],
  ['M13 2L3 14h8l-1 8 10-12h-8z', 'Move at your speed', 'Launch a plan, change a price or start a promotion yourself, with no engineering ticket and no release to wait for.'],
]

const STAGES = [
  {
    id: 'launch', tag: 'Launch', tone: 'violet',
    title: 'Go from pricing idea to live plan in an afternoon',
    text: 'Set up products, variants and plans from one screen. Your team owns pricing, so nothing waits on a developer.',
    callout: ['4', 'billing rhythms ready to go: daily, weekly, monthly and yearly'],
    points: [
      ['Any pricing shape', 'Flat fees, per-seat lines, add-ons and variants, such as a brand that adds to the price.'],
      ['Free trials', 'Offer days free on any plan, limited to once per customer per plan.'],
      ['Promotions your way', 'Codes that give a discount, account credit, free days or a custom perk.'],
      ['Ready-made quotes', 'Quotation templates turn a big offer into a subscription in a few clicks.'],
    ],
  },
  {
    id: 'scale', tag: 'Scale', tone: 'teal',
    title: 'Billing that keeps up on your biggest day',
    text: 'Hundreds of subscriptions fall due at once, and each one gets a correct invoice without anyone typing it.',
    callout: ['0', 'invoices billed twice, because a database rule makes it impossible'],
    points: [
      ['Automatic invoices', 'Customer details, product lines, taxes and totals are filled in from the subscription.'],
      ['Tax from your rules', 'Set percentage or fixed rules once, and every invoice follows them.'],
      ['Every way to pay', 'Card through Stripe, plus bank transfer, UPI, cash and cheque, approved by your admin.'],
      ['Fast with thousands', 'Pages stay under two seconds, checked against 5,000 subscriptions.'],
    ],
  },
  {
    id: 'retain', tag: 'Retain', tone: 'amber',
    title: 'Keep the customers you worked hard to win',
    text: 'Most lost revenue leaves quietly. Brightloop catches it at the moment it can still be saved.',
    callout: ['1 in 3', 'customers about to cancel choose a pause instead, in our demo customers'],
    points: [
      ['Renewals on autopilot', 'Subscriptions renew by themselves unless a customer opts out, so nobody has to remember.'],
      ['Pause before cancel', 'Offer a pause at the moment of leaving, and record why people go.'],
      ['Overdue follow-up', 'Spaced reminders by email and SMS chase invoices, and stop once they are paid.'],
      ['Help that stays in one place', 'Customers raise tickets, and customer care answers them and escalates when needed.'],
    ],
  },
  {
    id: 'acquire', tag: 'Acquire', tone: 'rose',
    title: 'Turn more visitors into paying subscribers',
    text: 'A short path from pricing page to first invoice, with customers in control from day one.',
    callout: ['2 steps', 'from choosing a plan to a running subscription'],
    points: [
      ['Self-serve sign-up', 'Live pricing, and sign-up by email or Google, without talking to anyone.'],
      ['Checkout that works', 'A hosted Stripe card page, ready as soon as the first invoice is.'],
      ['Trials that convert', 'The first invoice arrives by itself the day a free trial ends.'],
      ['Easy upgrades', 'Customers change plan themselves, and the difference is worked out by the day.'],
    ],
  },
]

function PanelRows({ rows }) {
  return <dl className="panel-rows">{rows.map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl>
}

function StagePanel({ id }) {
  if (id === 'launch') {
    return (
      <div className="panel">
        <small>New plan</small>
        <h4>Growth Monthly</h4>
        <PanelRows rows={[['Price', '₹2,499 / month'], ['Free trial', '14 days'], ['Brand: Odoo', '+ ₹560']]} />
        <div className="toggles">
          {[['Can be paused', true], ['Renews automatically', true], ['Shown on pricing page', true], ['Closes on its own', false]].map(([name, on]) => (
            <span key={name}><i className={on ? 'on' : ''} />{name}</span>
          ))}
        </div>
      </div>
    )
  }
  if (id === 'scale') {
    return (
      <div className="panel">
        <small>Billing day</small>
        <h4>312 subscriptions due</h4>
        <div className="progress"><i /></div>
        <PanelRows rows={[['Invoices created', '312'], ['Tax applied', 'GST 18%'], ['Billed twice', '0']]} />
        <div className="chips">{['Card', 'UPI', 'Bank transfer', 'Cash', 'Cheque'].map((m) => <span key={m}>{m}</span>)}</div>
      </div>
    )
  }
  if (id === 'retain') {
    return (
      <div className="panel">
        <small>Cancelling</small>
        <h4>Before you go, take a break instead?</h4>
        <p>You are not billed while paused, and you can come back at any time.</p>
        <div className="panel-buttons"><b>Pause instead</b><span>Close subscription</span></div>
        <small className="gap">Why customers left</small>
        {[['Not using it enough', 62], ['Too expensive', 38]].map(([name, width]) => (
          <div className="bar-row" key={name}><span>{name}</span><i><u style={{ width: `${width}%` }} /></i></div>
        ))}
      </div>
    )
  }
  return (
    <div className="panel">
      <small>Your plan</small>
      <h4>Growth Monthly</h4>
      <p className="big">₹2,499<em> / month</em></p>
      <div className="panel-field">you@yourcompany.com</div>
      <div className="panel-buttons one"><b>Start free trial</b></div>
      <small className="gap">14 days free, then billed monthly. Turn renewal off at any time.</small>
    </div>
  )
}

function StageNav({ active }) {
  return (
    <nav className="stage-nav" aria-label="Subscriber lifecycle">
      {STAGES.map((stage) => <a key={stage.id} href={`#${stage.id}`} className={active === stage.id ? 'on' : ''}>{stage.tag}</a>)}
    </nav>
  )
}

function Lifecycle() {
  const [active, setActive] = useState('launch')
  useEffect(() => {
    const spy = new IntersectionObserver((entries) => {
      entries.forEach((entry) => { if (entry.isIntersecting) setActive(entry.target.id) })
    }, { rootMargin: '-40% 0px -50% 0px' })
    STAGES.forEach((stage) => { const node = document.getElementById(stage.id); if (node) spy.observe(node) })
    return () => spy.disconnect()
  }, [])
  return (
    <section className="lifecycle" id="platform">
      <div className="heading reveal">
        <p className="eyebrow">The full subscriber lifecycle</p>
        <h2>One platform for every stage of a subscription.</h2>
      </div>
      <StageNav active={active} />
      {STAGES.map((stage, n) => (
        <article className={`stage ${stage.tone} ${n % 2 ? 'flip' : ''}`} id={stage.id} key={stage.id}>
          <div className="stage-copy reveal">
            <p className="eyebrow">{stage.tag}</p>
            <h3>{stage.title}</h3>
            <p className="stage-lead">{stage.text}</p>
            <div className="callout"><strong>{stage.callout[0]}</strong><span>{stage.callout[1]}</span></div>
          </div>
          <div className="stage-visual reveal"><StagePanel id={stage.id} /></div>
          <div className="stage-points">
            {stage.points.map(([title, text], i) => (
              <div className="point reveal" style={{ '--delay': `${i * 60}ms` }} key={title}><h4>{title}</h4><p>{text}</p></div>
            ))}
          </div>
        </article>
      ))}
    </section>
  )
}

const QUOTES = [
  ['We retired three spreadsheets in the first week. Renewals simply stopped being something we worry about.', 'Maya Ferreira', 'Finance Lead, Harbor & Pine'],
  ['Month end used to take days. Now I open one page and every number is already there.', 'Arjun Sethi', 'Head of Finance, Kestrel Labs'],
  ['Our customers manage their own plans now, and our support inbox has never been quieter.', 'Lena Okafor', 'Customer Success, Orbit Fitness'],
]

function Quotes() {
  const [index, setIndex] = useState(0)
  useEffect(() => {
    if (calm()) return undefined
    const timer = setInterval(() => setIndex((i) => (i + 1) % QUOTES.length), 6000)
    return () => clearInterval(timer)
  }, [])
  const [text, name, role] = QUOTES[index]
  return (
    <section className="quotes">
      <figure key={index}>
        <blockquote>{text}</blockquote>
        <figcaption><b>{name}</b><span>{role}</span></figcaption>
      </figure>
      <div className="quote-dots">
        {QUOTES.map(([, who], i) => <button key={who} aria-label={`Show the quote from ${who}`} aria-pressed={i === index} className={i === index ? 'on' : ''} onClick={() => setIndex(i)} />)}
      </div>
    </section>
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
          {plan.id === featured && <span className="ribbon">Most popular</span>}
          <h3>{plan.name}</h3>
          <p className="price">{money(plan.price)}<small> / {label(plan.billing_period).toLowerCase().replace('ly', '').replace('dai', 'day')}</small></p>
          <ul>
            <li>{plan.trial_days ? `${plan.trial_days} days free before the first invoice` : 'Billed from the day you start'}</li>
            <li>Customer portal and online payment</li>
            <li>{plan.pausable ? 'Pause whenever you need to' : 'Switch add-ons on and off'}</li>
            {plan.min_quantity > 1 && <li>From {plan.min_quantity} seats</li>}
          </ul>
          <Link className="cta" to="/signup?next=plans">{plan.self_serve ? (plan.trial_days ? 'Start free trial' : 'Get started') : 'Talk to sales'}</Link>
        </article>
      ))}
    </div>
  )
}

const TRUST = [
  ['Role-based access', 'Admin, general staff, customer care, sales and customers each see only their part, checked on the server.'],
  ['Protected sign-in', 'Strong password rules, hashed passwords, Google sign-in and limits on repeated attempts.'],
  ['Safe payments', 'Card details go straight to Stripe and never touch Brightloop. Webhooks are verified by signature.'],
  ['A clear record', 'Every subscription keeps a timeline of what happened, who did it and when.'],
]

const GUIDES = [
  {
    tag: 'Benchmark', title: 'Five numbers every subscription business should know',
    intro: 'If you only look at five figures each month, make it these.',
    body: [
      ['Monthly recurring revenue', 'What active subscriptions bring in each month, leaving out anyone still on a free trial.'],
      ['Churn', 'The share of subscribers who left. Look at the reasons as well as the rate.'],
      ['Deferred revenue', 'Money billed but not earned yet. A yearly invoice is earned day by day, not all at once.'],
      ['Overdue by age', 'A 10-day-old invoice is a reminder. A 90-day-old one is a phone call.'],
      ['Revenue per customer', 'Tells you whether growth comes from more customers or better ones.'],
    ],
  },
  {
    tag: 'Guide', title: 'Why customers cancel, and how to keep more of them',
    intro: 'Cancelling is rarely a sudden decision, so give people a better option at that moment.',
    body: [
      ['Offer a pause', 'Someone who is busy this quarter may be happy again next quarter.'],
      ['Ask why', 'One short question tells you more than a survey nobody answers.'],
      ['Chase kindly', 'Many overdue invoices are simply forgotten. Spaced reminders fix most of them.'],
      ['Make upgrades easy', 'A customer who can change plan alone is less likely to leave for one that fits.'],
    ],
  },
  {
    tag: 'Playbook', title: 'Moving your subscribers out of a spreadsheet',
    intro: 'You can switch in an afternoon without billing anyone twice.',
    body: [
      ['Set up your catalog', 'Add products, plans, taxes and payment terms first.'],
      ['Export what you have', 'One row per subscriber, with email, plan and start date, is enough.'],
      ['Preview, then import', 'Brightloop checks every row and shows problems before anything is saved.'],
      ['Let billing take over', 'Past periods are left alone, and invoices begin from each next due date.'],
    ],
  },
]

const QUESTIONS = [
  ['Can an invoice be billed twice?', 'No. Each billing period has a unique key in the database, so a repeat run or a second server cannot create the same invoice again.'],
  ['What happens if I change plan mid-month?', 'The change applies straight away. An upgrade charges the difference for the days left, and a downgrade leaves a credit for your next invoices once this period is paid.'],
  ['Do subscriptions renew automatically?', 'Yes. They renew at the end of their term unless the customer turns renewal off, and then they end on that date.'],
  ['Can I bring my existing subscribers?', 'Yes. Import a CSV of what they bought, preview it, and billing continues from their next due date.'],
  ['Who can see my data?', 'Customers see only their own subscriptions and invoices, and your team sees what its role allows. Access is checked on the server for every request.'],
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

function HealthCard() {
  const rows = [['Pricing and plans', 92], ['Billing accuracy', 88], ['Payment recovery', 64], ['Churn prevention', 58], ['Self-service', 81], ['Revenue insight', 73]]
  return (
    <div className="health" role="img" aria-label="Sample subscription health check with six scores">
      <div className="health-head"><b>Subscription health check</b><span>Sample</span></div>
      {rows.map(([name, score]) => (
        <div className="health-row" key={name}><span>{name}</span><i><u style={{ width: `${score}%` }} className={score < 70 ? 'low' : ''} /></i><b>{score}</b></div>
      ))}
    </div>
  )
}

export function Landing({ user }) {
  const root = useReveal()
  const bar = useRef(null)
  const [scrolled, setScrolled] = useState(false)
  const [guide, setGuide] = useState(null)

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

  const start = user ? <Link className="cta" to="/">Open the app</Link> : <Link className="cta" to="/signup">Get started</Link>
  return (
    <div className="landing" ref={root}>
      <div className="scroll-bar" ref={bar} aria-hidden="true" />
      <header className={`top ${scrolled ? 'scrolled' : ''}`}>
        <a className="brand" href="#start">Brightloop</a>
        <nav aria-label="Page sections">
          <a href="#platform">Products</a>
          <a href="#pricing">Pricing</a>
          <a href="#customers">Customers</a>
          <a href="#resources">Resources</a>
        </nav>
        <div className="top-actions">
          {!user && <Link className="quiet" to="/login">Log in</Link>}
          {start}
        </div>
      </header>

      <main>
        <section className="hero" id="start">
          <div className="aurora" aria-hidden="true"><i /><i /><i /></div>
          <div className="hero-copy">
            <p className="eyebrow rise">Subscription management platform</p>
            <h1 className="rise r2">Run the whole subscriber lifecycle in <span>one place.</span></h1>
            <p className="lead rise r3">Launch plans, bill on time, collect every payment and keep the customers you win. Brightloop is the backbone for businesses that earn every month.</p>
            <div className="hero-actions rise r4">
              {start}
              <a className="ghost" href="#platform">Take a tour</a>
            </div>
          </div>
          <div className="rise r3 hero-visual"><HeroMock /></div>
        </section>

        <section className="logos" id="customers" aria-label="Businesses using Brightloop">
          <p>Subscription businesses of every size run on Brightloop</p>
          <div className="logo-track" aria-hidden="true">
            <div>{[...CUSTOMERS, ...CUSTOMERS].map((name, i) => <span key={i}>{name}</span>)}</div>
          </div>
        </section>

        <section className="promo">
          <div className="promo-copy reveal">
            <p className="eyebrow">Free for new accounts</p>
            <h2>How healthy is your subscription business?</h2>
            <p>Get a health check across six growth areas, from pricing to churn, and see where the next rupee of revenue is hiding.</p>
            <Link className="text-link" to={user ? '/' : '/signup'}>Get my health check <span aria-hidden="true">→</span></Link>
          </div>
          <div className="reveal"><HealthCard /></div>
        </section>

        <section className="pillars">
          <div className="heading reveal">
            <p className="eyebrow">Built for action</p>
            <h2>Subscription insight you can act on today.</h2>
          </div>
          <div className="pillar-grid">
            {PILLARS.map(([icon, title, text], i) => (
              <article className="pillar reveal" style={{ '--delay': `${i * 80}ms` }} key={title}>
                <span className="icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={icon} /></svg></span>
                <h3>{title}</h3>
                <p>{text}</p>
              </article>
            ))}
          </div>
        </section>

        <Lifecycle />
        <Quotes />

        <section className="band tint" id="pricing">
          <div className="heading reveal"><p className="eyebrow">Pricing</p><h2>Simple plans, live and ready to start.</h2><p className="soft">Prices before tax.</p></div>
          <Pricing />
        </section>

        <section className="trust">
          <div className="heading reveal"><p className="eyebrow">Security</p><h2>Built on trust from the first login.</h2></div>
          <div className="trust-grid">
            {TRUST.map(([title, text], i) => <article className="reveal" style={{ '--delay': `${i * 60}ms` }} key={title}><h3>{title}</h3><p>{text}</p></article>)}
          </div>
        </section>

        <section className="band" id="resources">
          <div className="heading reveal"><p className="eyebrow">Resources</p><h2>Ideas for growing recurring revenue.</h2></div>
          <div className="guides">
            {GUIDES.map((item, i) => (
              <button className={`guide reveal g${i}`} style={{ '--delay': `${i * 70}ms` }} key={item.title} onClick={() => setGuide(item)}>
                <span className="guide-art" aria-hidden="true" />
                <small>{item.tag}</small>
                <b>{item.title}</b>
                <span className="text-link">Read it <span aria-hidden="true">→</span></span>
              </button>
            ))}
          </div>
        </section>

        <section className="band tint" id="faq">
          <div className="heading reveal"><p className="eyebrow">Questions</p><h2>Good to know.</h2></div>
          <Faq />
        </section>

        <section className="closing">
          <div className="aurora" aria-hidden="true"><i /><i /></div>
          <div className="reveal">
            <h2>Launch faster. Recover more. Grow on your own terms.</h2>
            {start}
          </div>
        </section>
      </main>

      <footer className="site-foot">
        <div className="foot-top">
          <div><span className="brand">Brightloop</span><p>The subscription backbone for businesses that earn every month.</p></div>
          <nav aria-label="Products"><h3>Products</h3><a href="#launch">Launch</a><a href="#scale">Scale</a><a href="#retain">Retain</a><a href="#acquire">Acquire</a><a href="#pricing">Pricing</a></nav>
          <nav aria-label="Resources"><h3>Resources</h3><a href="#resources">Guides</a><a href="#faq">Questions</a><a href="#customers">Customers</a></nav>
          <div><h3>Works with</h3><p>Stripe</p><p>Twilio</p><p>Google sign-in</p></div>
          <nav aria-label="Account"><h3>Account</h3>{user ? <Link to="/">Open the app</Link> : <><Link to="/login">Log in</Link><Link to="/signup">Create an account</Link><Link to="/forgot-password">Reset password</Link></>}</nav>
        </div>
        <p className="foot-note">© {new Date().getFullYear()} Brightloop Software. Brightloop is a fictional company created for a hackathon demo. Customer names, quotes and marketing figures on this page are illustrative. Stripe, Twilio and Google are trademarks of their owners.</p>
      </footer>

      {guide && (
        <Modal title={guide.title} onClose={() => setGuide(null)}>
          <div className="guide-body">
            <p>{guide.intro}</p>
            {guide.body.map(([title, text]) => <div key={title}><h3>{title}</h3><p>{text}</p></div>)}
            {!user && <Link className="cta" to="/signup">Try it in Brightloop</Link>}
          </div>
        </Modal>
      )}
    </div>
  )
}
