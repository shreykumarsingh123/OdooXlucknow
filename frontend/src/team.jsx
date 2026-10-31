import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, query } from './api'
import { useAuth } from './main'
import { Badge, DataTable, ErrorBox, Field, Modal, Pager, label, money, useDebounced, useLoad, useOptions, useToast } from './ui'

const when = (iso) => new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
const shortMonth = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { month: 'short', year: '2-digit' })

/* ------------------------------------------------------------ tickets */

const STATUS_TABS = [['', 'All'], ['open', 'Open'], ['in_progress', 'In progress'], ['resolved', 'Resolved']]

function NewTicket({ onClose }) {
  const navigate = useNavigate()
  const { data } = useLoad('/subscriptions/?page_size=50')
  const [form, setForm] = useState({ subject: '', body: '', subscription: '' })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const set = (name) => (e) => setForm((f) => ({ ...f, [name]: e.target.value }))
  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const ticket = await api.post('/tickets/', { ...form, subscription: form.subscription || null })
      navigate(`/tickets/${ticket.id}`)
    } catch (err) {
      setError(err)
      setBusy(false)
    }
  }
  return (
    <Modal title="Ask for help" onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <ErrorBox error={error} />
        <Field label="Subject" error={error?.fields?.subject}><input required maxLength="200" value={form.subject} onChange={set('subject')} /></Field>
        <Field label="About a subscription (optional)" error={error?.fields?.subscription}>
          <select value={form.subscription} onChange={set('subscription')}>
            <option value="">Not about one subscription</option>
            {data?.results.map((s) => <option key={s.id} value={s.id}>{s.number}, {s.plan_name}</option>)}
          </select>
        </Field>
        <Field label="How can we help?" error={error?.fields?.body}><textarea required rows="5" maxLength="5000" value={form.body} onChange={set('body')} /></Field>
        <footer><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy ? 'Sending…' : 'Send'}</button></footer>
      </form>
    </Modal>
  )
}

export function Tickets() {
  const { user } = useAuth()
  const team = user.role !== 'customer'
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [asking, setAsking] = useState(false)
  const debounced = useDebounced(search)
  const status = params.get('status') || ''
  const escalated = params.get('escalated') || ''
  const { data, loading, error, reload } = useLoad(`/tickets/${query({ page, search: debounced, status, escalated })}`)
  const columns = [
    { key: 'number', label: 'Ticket' },
    ...(team ? [{ key: 'customer_name', label: 'Customer' }] : []),
    { key: 'subject', label: 'Subject' },
    ...(team ? [
      { key: 'priority', label: 'Priority', render: (r) => <Badge value={r.priority} /> },
      { key: 'assigned_name', label: 'Assigned to', render: (r) => r.assigned_name || '—' },
    ] : []),
    { key: 'updated_at', label: 'Updated', render: (r) => when(r.updated_at) },
    { key: 'status', label: 'Status', render: (r) => <><Badge value={r.status} />{r.escalated && team && <small className="trial-tag warm-tag">Escalated</small>}</> },
  ]
  return (
    <section>
      <header className="page-head">
        <div><h1>{team ? 'Tickets' : 'Help'}</h1><p className="muted">{team ? 'Every request raised by customers.' : 'Ask a question, and follow our replies here.'}</p></div>
        {!team && <button className="primary" onClick={() => setAsking(true)}>Ask for help</button>}
      </header>
      <div className="tabs" role="tablist">
        {STATUS_TABS.map(([value, text]) => (
          <button key={value} role="tab" aria-selected={status === value && !escalated} className={status === value && !escalated ? 'on' : ''} onClick={() => { setPage(1); setParams(value ? { status: value } : {}) }}>{text}</button>
        ))}
        {team && <button role="tab" aria-selected={!!escalated} className={escalated ? 'on' : ''} onClick={() => { setPage(1); setParams({ escalated: 'true' }) }}>Escalated</button>}
      </div>
      {team && <div className="toolbar"><input type="search" aria-label="Search" placeholder="Search ticket, subject or customer" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }} /></div>}
      <ErrorBox error={error} onRetry={reload} />
      <div className="card flush">
        <DataTable columns={columns} rows={data?.results} loading={loading} empty="No tickets found." onRow={(r) => navigate(`/tickets/${r.id}`)} />
        {data && <Pager page={page} count={data.count} onPage={setPage} />}
      </div>
      {asking && <NewTicket onClose={() => setAsking(false)} />}
    </section>
  )
}

export function TicketDetail() {
  const { id } = useParams()
  const { user } = useAuth()
  const team = user.role !== 'customer'
  const toast = useToast()
  const { data: ticket, error, reload } = useLoad(`/tickets/${id}/`)
  const [body, setBody] = useState('')
  const [internal, setInternal] = useState(false)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState(null)

  const send = async (event) => {
    event.preventDefault()
    setBusy(true)
    setProblem(null)
    try {
      await api.post(`/tickets/${id}/reply/`, { body, internal })
      setBody('')
      setInternal(false)
      reload()
    } catch (err) {
      setProblem(err)
    }
    setBusy(false)
  }
  const manage = async (patch, message) => {
    try {
      await api.post(`/tickets/${id}/manage/`, patch)
      if (message) toast(message)
      reload()
    } catch (err) {
      toast(err.message, 'bad')
    }
  }
  if (error) return <ErrorBox error={error} onRetry={reload} />
  if (!ticket) return <p className="muted">Loading…</p>
  return (
    <section>
      <header className="page-head">
        <div>
          <h1>{ticket.subject} <Badge value={ticket.status} /></h1>
          <p className="muted">
            {ticket.number}
            {team && <>, <Link to={`/customers/${ticket.customer}`}>{ticket.customer_name}</Link></>}
            {ticket.subscription && <>, <Link to={`/subscriptions/${ticket.subscription}`}>{ticket.subscription_number}</Link></>}
          </p>
        </div>
        {team && (
          <div className="row">
            <button onClick={() => manage({ assigned_to: user.id }, 'Assigned to you.')}>Assign to me</button>
            <button onClick={() => manage({ escalated: !ticket.escalated }, ticket.escalated ? 'Escalation removed.' : 'Escalated to the admin.')}>{ticket.escalated ? 'Remove escalation' : 'Escalate to admin'}</button>
            {ticket.status !== 'resolved' && <button className="primary" onClick={() => manage({ status: 'resolved' }, 'Ticket resolved.')}>Mark resolved</button>}
          </div>
        )}
      </header>
      {team && (
        <div className="toolbar">
          <Field label="Status"><select value={ticket.status} onChange={(e) => manage({ status: e.target.value })}>{STATUS_TABS.slice(1).map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select></Field>
          <Field label="Priority"><select value={ticket.priority} onChange={(e) => manage({ priority: e.target.value })}>{['low', 'normal', 'high'].map((v) => <option key={v} value={v}>{label(v)}</option>)}</select></Field>
          <div className="field"><span>Assigned to</span><p className="assigned">{ticket.assigned_name || 'Nobody yet'}</p></div>
        </div>
      )}
      <div className="card thread">
        {ticket.messages.map((m) => (
          <article key={m.id} className={`bubble ${m.from_team ? 'from-team' : ''} ${m.is_internal ? 'internal' : ''}`}>
            <header><b>{m.author_name}</b>{m.is_internal && <small className="trial-tag warm-tag">Internal note</small>}<small>{when(m.created_at)}</small></header>
            <p>{m.body}</p>
          </article>
        ))}
      </div>
      <form className="card form" onSubmit={send}>
        <ErrorBox error={problem} />
        <Field label={internal ? 'Internal note, seen by the team only' : 'Your reply'} error={problem?.fields?.body}>
          <textarea required rows="3" maxLength="5000" value={body} onChange={(e) => setBody(e.target.value)} />
        </Field>
        <footer className="reply-foot">
          {team && <label className="check"><input type="checkbox" checked={internal} onChange={(e) => setInternal(e.target.checked)} /><span>Internal note</span></label>}
          <button className="primary" disabled={busy}>{busy ? 'Sending…' : internal ? 'Save note' : 'Send reply'}</button>
        </footer>
      </form>
    </section>
  )
}

/* ------------------------------------------------------------ team chat */

export function TeamChat() {
  const { user } = useAuth()
  const { data, error, reload } = useLoad('/team-chat/?page_size=100')
  const [body, setBody] = useState('')
  const [problem, setProblem] = useState(null)
  const end = useRef(null)
  const count = data?.results.length
  useEffect(() => {
    const timer = setInterval(reload, 10000)
    return () => clearInterval(timer)
  }, [reload])
  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest' }) }, [count])
  const send = async (event) => {
    event.preventDefault()
    setProblem(null)
    try {
      await api.post('/team-chat/', { body })
      setBody('')
      reload()
    } catch (err) {
      setProblem(err)
    }
  }
  return (
    <section>
      <header className="page-head"><div><h1>Team chat</h1><p className="muted">For the admin and staff. Customers cannot see this.</p></div></header>
      {!data && <ErrorBox error={error} onRetry={reload} />}
      <div className="card thread chat">
        {data && !data.results.length && <p className="muted">No messages yet. Say hello.</p>}
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
    </section>
  )
}

/* ------------------------------------------------------------ sales */

function TargetChart({ rows }) {
  const peak = Math.max(...rows.flatMap((r) => [Number(r.sold), Number(r.target)]), 1)
  return (
    <div className="card flush">
      <div className="chart-head">
        <h2>Sold against target, last 6 months</h2>
        <div className="legend"><span><i className="swatch" />Sold</span><span><i className="target-mark" />Target</span></div>
      </div>
      <div className="chart">
        <div className="plot" role="img" aria-label="New monthly revenue sold each month, compared with the target.">
          {rows.map((r) => (
            <div className="bar-slot" key={r.month} tabIndex={0}>
              <div className="bar-tip" style={{ bottom: `${(Math.max(Number(r.sold), Number(r.target)) / peak) * 100}%` }}><span className="tip">{shortMonth(r.month)}: {money(r.sold)} of {money(r.target)}</span></div>
              {Number(r.target) > 0 && <i className="target-line" style={{ bottom: `${(Number(r.target) / peak) * 100}%` }} />}
              <div className="bar" style={{ height: `${(Number(r.sold) / peak) * 100}%` }} />
            </div>
          ))}
        </div>
        <div className="axis">{rows.map((r) => <span key={r.month}>{shortMonth(r.month)}</span>)}</div>
      </div>
    </div>
  )
}

function SalesPerson({ data }) {
  const navigate = useNavigate()
  const percent = Math.min(data.progress ?? 0, 100)
  return (
    <>
      <div className="card target-card">
        <div className="chart-head flat">
          <h2>This month's target</h2>
          <strong>{money(data.sold)} of {Number(data.target) ? money(data.target) : 'no target set'}</strong>
        </div>
        <div className="meter" role="progressbar" aria-valuenow={Math.round(percent)} aria-valuemin="0" aria-valuemax="100" aria-label="Progress against target"><i style={{ width: `${percent}%` }} /></div>
        <p className="muted">{data.progress === null ? 'The admin has not set a target for this month.' : `${data.progress}% of target. Counts new monthly recurring revenue, before tax.`}</p>
      </div>
      <div className="tiles">
        <div className="tile"><span>New this month</span><strong>{data.new_subscriptions}</strong><small>Subscriptions activated</small></div>
        <div className="tile"><span>Active customers' value</span><strong>{money(data.active_value)}</strong><small>{data.active} active subscriptions, per month</small></div>
        <div className="tile"><span>Open quotes</span><strong>{data.open_quotes}</strong><small>Waiting to be won</small></div>
        <div className="tile"><span>Won</span><strong>{data.conversion === null ? '—' : `${data.conversion}%`}</strong><small>{data.total_won} won, against open quotes</small></div>
        <div className="tile"><span>Lost later</span><strong>{data.lost}</strong><small>Closed after being sold</small></div>
      </div>
      <TargetChart rows={data.history} />
      <div className="card flush">
        <h2>Who you sold to</h2>
        <DataTable
          rows={data.customers}
          empty="Nothing sold yet. Start a quotation from Subscriptions."
          onRow={(r) => navigate(`/subscriptions/${r.id}`)}
          columns={[
            { key: 'customer_name', label: 'Customer' },
            { key: 'number', label: 'Subscription' },
            { key: 'plan_name', label: 'Plan' },
            { key: 'activated_on', label: 'Sold on', render: (r) => r.activated_on || '—' },
            { key: 'recurring_total', label: 'Per period', right: true, render: (r) => `${money(r.recurring_total)} ${r.billing_period}` },
            { key: 'state', label: 'Stage', render: (r) => <Badge value={r.state} /> },
          ]}
        />
      </div>
    </>
  )
}

export function Sales() {
  const { user } = useAuth()
  const [person, setPerson] = useState('')
  const own = user.department === 'sales'
  const { data, error, reload } = useLoad(`/reports/sales/${query({ salesperson: person })}`)
  return (
    <section>
      <header className="page-head">
        <div><h1>{own ? 'My sales' : 'Sales team'}</h1><p className="muted">{own ? 'Your customers, your target and how the month is going.' : 'How each salesperson is doing this month.'}</p></div>
        {person && <button onClick={() => setPerson('')}>Back to the team</button>}
      </header>
      <ErrorBox error={error} onRetry={reload} />
      {!data && !error && <p className="muted">Loading…</p>}
      {data?.team && (
        <div className="card flush">
          <DataTable
            rows={data.team}
            empty="No salespeople yet. Add a staff member with the Sales department."
            onRow={(r) => setPerson(String(r.id))}
            columns={[
              { key: 'name', label: 'Salesperson' },
              { key: 'sold', label: 'Sold this month', right: true, render: (r) => money(r.sold) },
              { key: 'target', label: 'Target', right: true, render: (r) => (Number(r.target) ? money(r.target) : '—') },
              { key: 'progress', label: 'Progress', right: true, render: (r) => (r.progress === null ? '—' : `${r.progress}%`) },
              { key: 'active', label: 'Active', right: true },
              { key: 'open_quotes', label: 'Open quotes', right: true },
            ]}
          />
        </div>
      )}
      {data && !data.team && <SalesPerson data={data} />}
    </section>
  )
}

/* ------------------------------------------------------------ payment approvals */

const REQUEST_TABS = [['pending', 'Waiting'], ['approved', 'Approved'], ['rejected', 'Rejected']]

export function PaymentApprovals() {
  const toast = useToast()
  const [status, setStatus] = useState('pending')
  const [page, setPage] = useState(1)
  const [rejecting, setRejecting] = useState(null)
  const [note, setNote] = useState('')
  const { data, loading, error, reload } = useLoad(`/payment-requests/${query({ status, page })}`)
  const decide = async (row, action, body = {}) => {
    try {
      await api.post(`/payment-requests/${row.id}/${action}/`, body)
      toast(action === 'approve' ? `Payment recorded on ${row.invoice_number}.` : 'Request rejected. No payment was recorded.')
      setRejecting(null)
      setNote('')
      reload()
    } catch (err) {
      toast(err.message, 'bad')
    }
  }
  return (
    <section>
      <header className="page-head"><div><h1>Payment approvals</h1><p className="muted">Customers who paid outside Stripe ask for approval here. Check that the money arrived, then approve. Only then is the payment recorded.</p></div></header>
      <div className="tabs" role="tablist">
        {REQUEST_TABS.map(([value, text]) => <button key={value} role="tab" aria-selected={status === value} className={status === value ? 'on' : ''} onClick={() => { setStatus(value); setPage(1) }}>{text}</button>)}
      </div>
      <ErrorBox error={error} onRetry={reload} />
      <div className="card flush">
        <DataTable
          rows={data?.results}
          loading={loading}
          empty="Nothing here."
          columns={[
            { key: 'created_at', label: 'Asked on', render: (r) => when(r.created_at) },
            { key: 'customer_name', label: 'Customer' },
            { key: 'invoice_number', label: 'Invoice', render: (r) => <Link to={`/invoices/${r.invoice}`}>{r.invoice_number}</Link> },
            { key: 'method_label', label: 'Method' },
            { key: 'reference', label: 'Reference', render: (r) => r.reference || '—' },
            { key: 'amount', label: 'Amount', right: true, render: (r) => money(r.amount) },
            status === 'pending'
              ? { key: 'act', label: '', right: true, render: (r) => <span className="row end"><button className="primary" onClick={() => decide(r, 'approve')}>Approve</button><button className="danger" onClick={() => setRejecting(r)}>Reject</button></span> }
              : { key: 'decision_note', label: 'Note', render: (r) => r.decision_note || '—' },
          ]}
        />
        {data && <Pager page={page} count={data.count} onPage={setPage} />}
      </div>
      {rejecting && (
        <Modal title={`Reject ${money(rejecting.amount)} from ${rejecting.customer_name}?`} onClose={() => setRejecting(null)}>
          <form className="form" onSubmit={(e) => { e.preventDefault(); decide(rejecting, 'reject', { note }) }}>
            <Field label="Reason"><input maxLength="255" value={note} onChange={(e) => setNote(e.target.value)} /></Field>
            <footer><button type="button" onClick={() => setRejecting(null)}>Cancel</button><button className="danger">Reject</button></footer>
          </form>
        </Modal>
      )}
    </section>
  )
}

/* ------------------------------------------------------------ customer account */

function AssignPlan({ customer, onClose, onDone }) {
  const plans = useOptions('/plans/')
  const [plan, setPlan] = useState('')
  const running = customer.subscriptions.filter((s) => ['active', 'paused'].includes(s.state))
  const [replace, setReplace] = useState('')
  const [error, setError] = useState(null)
  const chosen = plans.find((p) => p.id === Number(plan))
  const submit = async (event) => {
    event.preventDefault()
    setError(null)
    try {
      onDone(await api.post(`/customers/${customer.id}/assign_plan/`, { plan: Number(plan), replace: replace || null }))
    } catch (err) {
      setError(err)
    }
  }
  return (
    <Modal title={`Assign a plan to ${customer.name}`} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <ErrorBox error={error} />
        <Field label="Plan" error={error?.fields?.plan} help={chosen ? `${money(chosen.price)} ${chosen.billing_period}, before tax${chosen.trial_days ? `, ${chosen.trial_days} days free if this is their first time on it` : '. The first invoice is created now.'}` : null}>
          <select required value={plan} onChange={(e) => setPlan(e.target.value)}>
            <option value="">Choose</option>
            {plans.filter((p) => p.is_active).map((p) => <option key={p.id} value={p.id}>{p.name}, {money(p.price)} {p.billing_period}</option>)}
          </select>
        </Field>
        {running.length > 0 && (
          <Field label="Replace a current subscription" error={error?.fields?.replace} help="The one you pick closes now, with no refund. To charge the difference instead, use Change plan on the subscription.">
            <select value={replace} onChange={(e) => setReplace(e.target.value)}>
              <option value="">No, keep it as well</option>
              {running.map((s) => <option key={s.id} value={s.id}>{s.number}, {s.plan_name}</option>)}
            </select>
          </Field>
        )}
        <footer><button type="button" onClick={onClose}>Cancel</button><button className="primary">Assign plan</button></footer>
      </form>
    </Modal>
  )
}

export function CustomerDetail() {
  const { id } = useParams()
  const { user } = useAuth()
  const navigate = useNavigate()
  const toast = useToast()
  const { data: c, error, reload } = useLoad(`/customers/${id}/overview/`)
  const [assigning, setAssigning] = useState(false)
  if (error) return <ErrorBox error={error} onRetry={reload} />
  if (!c) return <p className="muted">Loading…</p>
  return (
    <section>
      <header className="page-head">
        <div><h1>{c.name} <Badge value={c.status} /></h1><p className="muted">{c.email}{c.phone && `, ${c.phone}`}</p></div>
        {user.role === 'admin' && <button className="primary" onClick={() => setAssigning(true)}>Assign a plan</button>}
      </header>
      <div className="tiles">
        <div className="tile"><span>Billed</span><strong>{money(c.billed)}</strong><small>Confirmed and paid invoices</small></div>
        <div className="tile"><span>Paid</span><strong>{money(c.paid)}</strong></div>
        <div className="tile"><span>Still owed</span><strong className={c.overdue_invoices ? 'bad-text' : ''}>{money(c.owed)}</strong><small>{c.overdue_invoices} overdue invoice(s)</small></div>
        <div className="tile"><span>Credit</span><strong>{money(c.credit)}</strong><small>For next invoices</small></div>
      </div>
      <div className="card flush">
        <h2>Plans and subscriptions</h2>
        <DataTable
          rows={c.subscriptions}
          empty="No subscriptions yet."
          onRow={(r) => navigate(`/subscriptions/${r.id}`)}
          columns={[
            { key: 'number', label: 'Number' },
            { key: 'plan_name', label: 'Plan' },
            { key: 'billing_period', label: 'Bills', render: (r) => label(r.billing_period) },
            { key: 'recurring_total', label: 'Per period', right: true, render: (r) => money(r.recurring_total) },
            { key: 'expiry_date', label: 'Runs until' },
            { key: 'auto_renew', label: 'Renews', render: (r) => (r.auto_renew ? 'Automatically' : 'No, ends then') },
            { key: 'state', label: 'Stage', render: (r) => <Badge value={r.state} /> },
          ]}
        />
      </div>
      <div className="card flush">
        <h2>Open tickets</h2>
        <DataTable
          rows={c.open_tickets}
          empty="No open tickets."
          onRow={(r) => navigate(`/tickets/${r.id}`)}
          columns={[{ key: 'number', label: 'Ticket' }, { key: 'subject', label: 'Subject' }, { key: 'status', label: 'Status', render: (r) => <Badge value={r.status} /> }]}
        />
      </div>
      {assigning && <AssignPlan customer={c} onClose={() => setAssigning(false)} onDone={(sub) => { setAssigning(false); toast(`${sub.number} created.`); reload() }} />}
    </section>
  )
}

/* ------------------------------------------------------------ import */

export function ImportSubscribers() {
  const toast = useToast()
  const [text, setText] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const run = async (commit, source = text) => {
    setBusy(true)
    setError(null)
    try {
      const data = await api.post('/imports/subscribers/', { csv: source, commit })
      setResult(data)
      if (commit) toast(`${data.imported} subscriber(s) imported.`)
    } catch (err) {
      setError(err)
      setResult(null)
    }
    setBusy(false)
  }
  const loadSample = async () => {
    try {
      const sample = (await api.get('/imports/sample/')).csv
      setText(sample)
      run(false, sample)
    } catch (err) {
      setError(err)
    }
  }
  const readFile = async (event) => {
    const file = event.target.files[0]
    if (!file) return
    const content = await file.text()
    setText(content)
    run(false, content)
  }
  return (
    <section>
      <header className="page-head">
        <div><h1>Import subscribers</h1><p className="muted">Bring in what your customers already buy from you, from a spreadsheet or another store's export.</p></div>
        <button className="primary" onClick={loadSample}>Load sample data</button>
      </header>
      <div className="card form">
        <ErrorBox error={error} />
        <Field label="CSV data" error={error?.fields?.csv} help="Needs email and plan. Optional: first_name, last_name, company, phone, product, quantity, start_date, expiry_date. Plan and product names must match your catalog.">
          <textarea className="mono" rows="9" spellCheck="false" value={text} onChange={(e) => { setText(e.target.value); setResult(null) }} placeholder="email,plan,start_date&#10;someone@example.com,Business Monthly,2026-01-15" />
        </Field>
        <footer className="reply-foot">
          <label className="file-pick">Upload a CSV file<input type="file" accept=".csv,text/csv" onChange={readFile} /></label>
          <button disabled={busy || !text.trim()} onClick={() => run(false)}>Preview</button>
        </footer>
      </div>
      {result && (
        <>
          <div className="banner">
            <span><b>{result.imported ? `${result.imported} imported. ` : `${result.ready} ready to import. `}</b>{result.skipped} already here, {result.errors} with problems. Past periods are not billed again, and nobody is emailed. New customers sign in with Forgot password.</span>
            {result.ready > 0 && <button className="primary" disabled={busy} onClick={() => run(true)}>Import {result.ready} subscriber(s)</button>}
          </div>
          <div className="card flush">
            <DataTable
              rowKey="line"
              rows={result.rows}
              columns={[
                { key: 'line', label: 'Line', right: true },
                { key: 'customer', label: 'Customer', render: (r) => r.customer || r.email },
                { key: 'email', label: 'Email' },
                { key: 'plan', label: 'Plan' },
                { key: 'product', label: 'Bought', render: (r) => (r.product ? `${r.quantity} × ${r.product}` : '—') },
                { key: 'start_date', label: 'Since' },
                { key: 'status', label: 'Result', render: (r) => (r.errors.length ? <span className="bad-text">{r.errors.join(' ')}</span> : <Badge value={r.status} />) },
              ]}
            />
          </div>
        </>
      )}
    </section>
  )
}
