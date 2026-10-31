import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, query } from './api'
import { useAuth } from './main'
import { Badge, DataTable, ErrorBox, Field, Pager, label, money, useDebounced, useLoad, useToast } from './ui'

const when = (iso) => new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
const count = (n) => Number(n).toLocaleString('en-IN')

/* ------------------------------------------------------------ recovery email */

export function RecoveryGate() {
  const { user, refreshUser, logout } = useAuth()
  const [email, setEmail] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.patch('/auth/me/', { recovery_email: email })
      await refreshUser()
    } catch (err) {
      setError(err)
      setBusy(false)
    }
  }
  return (
    <main className="gate">
      <form className="card form gate-card" onSubmit={submit}>
        <h1>Add a recovery email</h1>
        <p className="muted">You need this before continuing. If you forget your password, we send a one-time code here.</p>
        <p className="muted">Signed in as <b>{user.email}</b></p>
        <ErrorBox error={error} />
        <Field label="Your real email address" error={error?.fields?.recovery_email}>
          <input type="email" required autoComplete="email" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <button className="primary wide" disabled={busy}>{busy ? 'Saving…' : 'Save and continue'}</button>
        <button type="button" className="link" onClick={logout}>Sign out</button>
      </form>
    </main>
  )
}

/* ------------------------------------------------------------ brightloop console */

export function PlatformOverview() {
  const toast = useToast()
  const { data, error, reload } = useLoad('/platform/overview/')
  const toggle = async (row) => {
    if (row.is_active && !window.confirm(`Suspend ${row.name}? Everyone in it is locked out until you turn it back on.`)) return
    try {
      await api.post(`/platform/businesses/${row.id}/active/`, { is_active: !row.is_active })
      toast(row.is_active ? `${row.name} suspended.` : `${row.name} is active again.`)
      reload()
    } catch (err) {
      toast(err.message, 'bad')
    }
  }
  if (error) return <ErrorBox error={error} onRetry={reload} />
  if (!data) return <p className="muted">Loading…</p>
  const t = data.totals
  return (
    <section>
      <header className="page-head"><div><h1>Brightloop overview</h1><p className="muted">Every business on the platform, and the subscriptions tracked for them.</p></div></header>
      <div className="tiles">
        <div className="tile"><span>Businesses</span><strong>{count(t.businesses)}</strong><small>{count(t.active_businesses)} active</small></div>
        <div className="tile"><span>People on the platform</span><strong>{count(t.users)}</strong></div>
        <div className="tile"><span>Subscriptions tracked</span><strong>{count(t.active_subscriptions)}</strong><small>Active, across all businesses</small></div>
        <div className="tile"><span>Monthly recurring tracked</span><strong>{money(t.tracked_mrr)}</strong><small>Earned by the businesses, before tax</small></div>
        <div className="tile"><span>Collected by businesses</span><strong>{money(t.collected)}</strong></div>
        <div className="tile"><span>Still owed to them</span><strong>{money(t.owed)}</strong><small>{money(t.overdue)} overdue</small></div>
      </div>
      <div className="card flush">
        <h2>Businesses</h2>
        <DataTable
          rows={data.businesses}
          empty="No businesses yet."
          columns={[
            { key: 'name', label: 'Business' },
            { key: 'code', label: 'Business ID', render: (r) => <Link to={`/shop/${r.code}`}>{r.code}</Link> },
            { key: 'active', label: 'Active subs', right: true, render: (r) => count(r.active) },
            { key: 'customers', label: 'Customers', right: true, render: (r) => count(r.customers) },
            { key: 'team', label: 'Staff', right: true, render: (r) => count(r.team) },
            { key: 'mrr', label: 'Monthly', right: true, render: (r) => money(r.mrr) },
            { key: 'collected', label: 'Collected', right: true, render: (r) => money(r.collected) },
            { key: 'overdue', label: 'Overdue', right: true, render: (r) => money(r.overdue) },
            { key: 'is_active', label: 'Status', render: (r) => <Badge value={r.is_active ? 'active' : 'inactive'} /> },
            { key: 'act', label: '', right: true, render: (r) => <button className={r.is_active ? 'link danger' : 'link'} onClick={() => toggle(r)}>{r.is_active ? 'Suspend' : 'Turn on'}</button> },
          ]}
        />
      </div>
    </section>
  )
}

export function PlatformUsers() {
  const toast = useToast()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const debounced = useDebounced(search)
  const { data, loading, error, reload } = useLoad(`/platform/users/${query({ page, search: debounced })}`)
  const toggle = async (row) => {
    try {
      await api.post(`/platform/users/${row.id}/active/`, { is_active: !row.is_active })
      toast(row.is_active ? `${row.email} turned off.` : `${row.email} turned on.`)
      reload()
    } catch (err) {
      toast(err.message, 'bad')
    }
  }
  return (
    <section>
      <header className="page-head"><div><h1>All users</h1><p className="muted">Everyone on the platform, in every business.</p></div></header>
      <div className="toolbar"><input type="search" aria-label="Search" placeholder="Search name, email or business" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }} /></div>
      <ErrorBox error={error} onRetry={reload} />
      <div className="card flush">
        <DataTable
          rows={data?.results}
          loading={loading}
          empty="No users found."
          columns={[
            { key: 'name', label: 'Name' },
            { key: 'email', label: 'Email' },
            { key: 'role_label', label: 'Type' },
            { key: 'business', label: 'Business', render: (r) => r.business || '—' },
            { key: 'is_active', label: 'Status', render: (r) => <Badge value={r.is_active ? 'active' : 'inactive'} /> },
            { key: 'act', label: '', right: true, render: (r) => (r.is_root ? '' : <button className={r.is_active ? 'link danger' : 'link'} onClick={() => toggle(r)}>{r.is_active ? 'Turn off' : 'Turn on'}</button>) },
          ]}
        />
        {data && <Pager page={page} count={data.count} onPage={setPage} />}
      </div>
    </section>
  )
}

/* ------------------------------------------------------------ admin chat */

function Conversation({ business }) {
  const { user } = useAuth()
  const suffix = business ? `?business=${business}&page_size=100` : '?page_size=100'
  const { data, error, reload } = useLoad(`/admin-chat/${suffix}`)
  const [body, setBody] = useState('')
  const [problem, setProblem] = useState(null)
  const end = useRef(null)
  const size = data?.results.length
  useEffect(() => {
    const timer = setInterval(reload, 10000)
    return () => clearInterval(timer)
  }, [reload])
  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest' }) }, [size])
  const send = async (event) => {
    event.preventDefault()
    setProblem(null)
    try {
      await api.post(`/admin-chat/${business ? `?business=${business}` : ''}`, { body })
      setBody('')
      reload()
    } catch (err) {
      setProblem(err)
    }
  }
  return (
    <>
      {!data && <ErrorBox error={error} onRetry={reload} />}
      <div className="card thread chat">
        {data && !data.results.length && <p className="muted">No messages yet.</p>}
        {data && [...data.results].reverse().map((m) => (
          <article key={m.id} className={`bubble ${m.author === user.id ? 'from-team' : ''}`}>
            <header><b>{m.author_name}</b><small>{m.author_role}, {when(m.created_at)}</small></header>
            <p>{m.body}</p>
          </article>
        ))}
        <div ref={end} />
      </div>
      <form className="card chat-form" onSubmit={send}>
        <input aria-label="Message" required maxLength="5000" placeholder="Write a message" value={body} onChange={(e) => setBody(e.target.value)} />
        <button className="primary">Send</button>
      </form>
      <ErrorBox error={problem} />
    </>
  )
}

export function AdminChat() {
  const { user } = useAuth()
  const platform = user.business?.is_platform
  const threads = useLoad(platform ? '/platform/overview/' : '/health/')
  const started = useLoad(platform ? '/admin-chat/threads/' : '/health/')
  const [business, setBusiness] = useState('')
  const counts = Object.fromEntries((Array.isArray(started.data) ? started.data : []).map((t) => [t.business, t.count]))
  return (
    <section>
      <header className="page-head">
        <div><h1>Admin chat</h1><p className="muted">{platform ? 'Answer the businesses using Brightloop.' : 'Talk to the Brightloop team about any problem.'}</p></div>
      </header>
      {platform && (
        <div className="toolbar">
          <Field label="Business">
            <select value={business} onChange={(e) => setBusiness(e.target.value)}>
              <option value="">Choose a business</option>
              {threads.data?.businesses?.map((b) => <option key={b.id} value={b.id}>{b.name}{counts[b.id] ? ` (${counts[b.id]})` : ''}</option>)}
            </select>
          </Field>
        </div>
      )}
      {(!platform || business) && <Conversation key={business} business={platform ? business : null} />}
    </section>
  )
}

/* ------------------------------------------------------------ the owner's own plan with brightloop */

export function MyPlan() {
  const toast = useToast()
  const { user } = useAuth()
  const { data, error, reload } = useLoad('/my-plan/')
  const plans = useLoad('/public/plans/')
  const start = async (plan) => {
    try {
      await api.post('/my-plan/', { plan: plan.id })
      toast(`You are on ${plan.name}.`)
      reload()
    } catch (err) {
      toast(err.message, 'bad')
    }
  }
  const running = data?.subscriptions.filter((s) => ['active', 'paused'].includes(s.state)) || []
  return (
    <section>
      <header className="page-head"><div><h1>My Brightloop plan</h1><p className="muted">What {user.business.name} pays Brightloop. Your customers cannot see this.</p></div></header>
      <ErrorBox error={error} onRetry={reload} />
      <div className="card flush">
        <h2>Current plan</h2>
        <DataTable
          rows={data?.subscriptions}
          empty="You are not on a plan yet."
          columns={[
            { key: 'number', label: 'Number' },
            { key: 'plan_name', label: 'Plan' },
            { key: 'recurring_total', label: 'Price', right: true, render: (r) => `${money(r.recurring_total)} ${r.billing_period}` },
            { key: 'expiry_date', label: 'Runs until' },
            { key: 'state', label: 'Stage', render: (r) => <Badge value={r.state} /> },
          ]}
        />
      </div>
      <div className="card flush">
        <h2>Invoices from Brightloop</h2>
        <DataTable
          rows={data?.invoices}
          empty="No invoices yet."
          columns={[
            { key: 'number', label: 'Invoice' },
            { key: 'due_date', label: 'Due' },
            { key: 'total', label: 'Total', right: true, render: (r) => money(r.total) },
            { key: 'amount_due', label: 'Still due', right: true, render: (r) => money(r.amount_due) },
            { key: 'state', label: 'Status', render: (r) => <Badge value={r.state} /> },
          ]}
        />
      </div>
      {!running.length && (
        <div className="tiles plan-tiles">
          {plans.data?.map((plan) => (
            <div className="tile" key={plan.id}>
              <span>{label(plan.billing_period)}</span>
              <h2>{plan.name}</h2>
              <strong>{money(plan.price)}</strong>
              <small>{plan.trial_days ? `${plan.trial_days} days free` : 'Billed from today'}</small>
              <button className="primary" onClick={() => start(plan)}>Choose {plan.name}</button>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

/* ------------------------------------------------------------ a business's own public site */

export function Shop() {
  const { code } = useParams()
  const { data, error } = useLoad(`/public/sites/${code}/`)
  const [chosen, setChosen] = useState(null)
  const [form, setForm] = useState({ name: '', email: '' })
  const [problem, setProblem] = useState(null)
  const [done, setDone] = useState(null)
  const [busy, setBusy] = useState(false)
  const set = (name) => (e) => setForm((f) => ({ ...f, [name]: e.target.value }))
  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setProblem(null)
    try {
      setDone(await api.post(`/public/sites/${code}/subscribe/`, { ...form, plan: chosen.id }))
    } catch (err) {
      setProblem(err)
    }
    setBusy(false)
  }
  if (error) return <main className="shop"><div className="shop-empty"><h1>This site was not found</h1><p className="muted">Check the address and try again.</p></div></main>
  if (!data) return <main className="shop"><p className="muted pad">Loading…</p></main>
  return (
    <main className="shop">
      <header className="shop-hero">
        <p className="shop-tag">Test site</p>
        <h1>{data.name}</h1>
        <p>Choose a plan and subscribe. Your subscription is tracked by Brightloop.</p>
      </header>
      <div className="shop-body">
        {done ? (
          <div className="card shop-done" role="status">
            <h2>You are subscribed</h2>
            <p>{done.plan}, subscription {done.number}.{done.trial_ends ? ` Your free trial runs until ${done.trial_ends}.` : ' Your first invoice is ready.'}</p>
            <p className="muted">To see it, sign in using Forgot password with the email you gave. {data.name} can see it in their panel now.</p>
            <Link className="button primary" to="/forgot-password">Set my password</Link>
          </div>
        ) : (
          <>
            <div className="tiles plan-tiles">
              {data.plans.map((plan) => (
                <div className={`tile ${chosen?.id === plan.id ? 'picked' : ''}`} key={plan.id}>
                  <span>{label(plan.billing_period)}</span>
                  <h2>{plan.name}</h2>
                  <strong>{money(plan.price)}</strong>
                  <small>{plan.trial_days ? `${plan.trial_days} days free` : 'Starts today'}</small>
                  {plan.self_serve ? <button className={chosen?.id === plan.id ? 'primary' : ''} onClick={() => setChosen(plan)}>{chosen?.id === plan.id ? 'Selected' : 'Choose'}</button> : <small>From {plan.min_quantity} seats, by quote</small>}
                </div>
              ))}
            </div>
            {!data.plans.length && <p className="muted">No plans are open right now.</p>}
            {chosen && (
              <form className="card form narrow" onSubmit={submit}>
                <h2>Subscribe to {chosen.name}</h2>
                <ErrorBox error={problem} />
                <Field label="Your name" error={problem?.fields?.name}><input required value={form.name} onChange={set('name')} /></Field>
                <Field label="Your Gmail address" error={problem?.fields?.email}><input type="email" required placeholder="name@gmail.com" value={form.email} onChange={set('email')} /></Field>
                <button className="primary wide" disabled={busy}>{busy ? 'Subscribing…' : 'Subscribe'}</button>
              </form>
            )}
          </>
        )}
      </div>
      <footer className="shop-foot">Subscriptions powered by <Link to="/welcome">Brightloop</Link></footer>
    </main>
  )
}
