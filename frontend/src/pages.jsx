import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, query } from './api'
import { useAuth } from './main'
import {
  Badge, DataTable, ErrorBox, Field, LineEditor, Modal, Pager, SearchPicker, label, money, useDebounced, useLoad, useOptions, useToast,
} from './ui'

const isoToday = () => new Date().toISOString().slice(0, 10)
const inTrial = (sub) => sub.state === 'active' && sub.trial_ends && sub.trial_ends > isoToday()
const customerName = (c) => `${c.name}${c.company && c.company !== c.name ? ` · ${c.company}` : ''}`

/* ------------------------------------------------------------ dashboard */

function Tile({ title, value, note, to, tone }) {
  const body = <><span>{title}</span><strong className={tone || ''}>{value}</strong>{note && <small>{note}</small>}</>
  return to ? <Link className="tile" to={to}>{body}</Link> : <div className="tile">{body}</div>
}

function RevenueChart({ rows }) {
  const months = [...rows].reverse()
  const peak = Math.max(...months.map((m) => Number(m.amount)), 1)
  const total = months.reduce((sum, m) => sum + Number(m.amount), 0)
  return (
    <div className="card flush">
      <div className="chart-head"><h2>Revenue collected by month</h2><strong>{money(total)}</strong></div>
      {!months.length ? <p className="muted pad">No revenue in this period.</p> : (
        <div className="chart">
          <div className="plot" role="img" aria-label={`Revenue by month. Highest month ${money(peak)}.`}>
            {months.map((m) => (
              <div className="bar-slot" key={m.month} tabIndex={0}>
                <div className="bar-tip" style={{ bottom: `${(Number(m.amount) / peak) * 100}%` }}><span className="tip">{m.month}: {money(m.amount)}</span></div>
                <div className="bar" style={{ height: `${(Number(m.amount) / peak) * 100}%` }} />
              </div>
            ))}
          </div>
          <div className="axis">{months.map((m) => <span key={m.month}>{m.month}</span>)}</div>
          <details>
            <summary>Show as table</summary>
            <table>
              <thead><tr><th>Month</th><th className="right">Collected</th></tr></thead>
              <tbody>{months.map((m) => <tr key={m.month}><td>{m.month}</td><td className="right">{money(m.amount)}</td></tr>)}</tbody>
            </table>
          </details>
        </div>
      )}
    </div>
  )
}

function BarList({ title, rows, name, value, format, empty, note }) {
  const peak = Math.max(...rows.map((r) => Number(r[value])), 1)
  const live = rows.filter((r) => Number(r[value]) > 0)
  return (
    <div className="card">
      <h2>{title}</h2>
      {note && <p className="muted small-note">{note}</p>}
      {!live.length ? <p className="muted">{empty}</p> : (
        <ul className="barlist">
          {live.map((r) => (
            <li key={r[name]}>
              <span>{r[name]}</span><b>{format(r[value])}</b>
              <i aria-hidden="true"><u style={{ width: `${(Number(r[value]) / peak) * 100}%` }} /></i>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function Dashboard() {
  const { user } = useAuth()
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const { data, error, loading, reload } = useLoad(`/reports/summary/${query({ from, to })}`)
  const toast = useToast()
  const [running, setRunning] = useState(false)

  const runBilling = async () => {
    setRunning(true)
    try {
      const result = await api.post('/billing/run/')
      toast(`${result.invoices_created} invoice(s) created, ${result.subscriptions_closed} subscription(s) closed${result.failed.length ? `, ${result.failed.length} failed` : ''}.`, result.failed.length ? 'bad' : 'good')
      reload()
    } catch (err) {
      toast(err.message, 'bad')
    }
    setRunning(false)
  }

  const chase = async () => {
    try {
      const result = await api.post('/billing/reminders/')
      toast(`${result.reminded} reminder(s) sent, ${result.sms_sent} by SMS${result.failed ? `, ${result.failed} failed` : ''}.`, result.failed ? 'bad' : 'good')
    } catch (err) {
      toast(err.message, 'bad')
    }
  }

  const exportCsv = async (kind) => {
    try {
      await api.download(`/reports/export/${kind}/${query({ from, to })}`, `brightloop-${kind}.csv`)
    } catch (err) {
      toast(err.message, 'bad')
    }
  }

  return (
    <section>
      <header className="page-head">
        <div><h1>Finance summary</h1><p className="muted">Revenue, payments and invoice figures follow the dates you choose.</p></div>
        <div className="toolbar">
          <Field label="From"><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
          <Field label="To"><input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
        </div>
      </header>
      <div className="row export-row">
        <span className="muted">Export CSV:</span>
        {['subscriptions', 'invoices', 'payments'].map((kind) => <button key={kind} onClick={() => exportCsv(kind)}>{label(kind)}</button>)}
      </div>
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data && <p className="muted">Loading…</p>}
      {data && (
        <>
          {data.payment_requests_pending > 0 && user.role === 'admin' && (
            <div className="banner">
              <span><b>{data.payment_requests_pending} payment(s) waiting for your approval.</b></span>
              <Link className="button primary" to="/payment-approvals">Review</Link>
            </div>
          )}
          {(data.due_for_billing > 0 || data.drafts_to_confirm > 0) && (
            <div className="banner">
              <span>
                {data.due_for_billing > 0 && <b>{data.due_for_billing} subscription(s) due for billing. </b>}
                {data.drafts_to_confirm > 0 && <Link to="/invoices?state=draft">{data.drafts_to_confirm} draft invoice(s) to confirm. </Link>}
              </span>
              {data.due_for_billing > 0 && <button className="primary" disabled={running} onClick={runBilling}>{running ? 'Billing…' : 'Run billing'}</button>}
            </div>
          )}
          <div className="tiles">
            <Tile title="Active subscriptions" value={data.active_subscriptions.toLocaleString('en-IN')} note={`${data.expiring_soon} expire within 30 days`} to="/subscriptions?state=active" />
            <Tile title="Monthly recurring revenue" value={money(data.monthly_recurring_revenue)} note="Active subscriptions, before tax" />
            <Tile title="Revenue collected" value={money(data.revenue_collected)} note={`${data.payments_count.toLocaleString('en-IN')} payments`} to="/payments" />
            <Tile title="Still owed" value={money(data.outstanding_amount)} note={`${data.outstanding_count.toLocaleString('en-IN')} invoices outstanding`} to="/invoices?payment_status=outstanding" />
            <Tile title="Overdue" tone="bad-text" value={money(data.overdue_amount)} note={`${data.overdue_count.toLocaleString('en-IN')} invoices past due`} to="/invoices?payment_status=overdue" />
            <Tile title="Invoiced" value={money(data.invoiced)} note="Confirmed and paid invoices" />
            <Tile title="Annual recurring revenue" value={money(data.annual_recurring_revenue)} note="Monthly recurring revenue × 12" />
            <Tile title="Churn" value={`${data.churn_rate}%`} note={`${data.churned_subscriptions} closed ${from || to ? 'in these dates' : 'in the last 30 days'}`} />
            <Tile title="Revenue per customer" value={money(data.average_revenue_per_customer)} note="Monthly, across paying customers" />
            <Tile title="In free trial" value={data.in_trial.toLocaleString('en-IN')} note="Not yet counted as recurring revenue" />
          </div>
          <RevenueChart rows={data.revenue_by_month} />
          {data.overdue_count > 0 && <div className="row"><button onClick={chase}>Send overdue reminders</button></div>}
          <div className="grid-3">
            <BarList title="Recurring revenue by plan" note="Monthly value, largest first" rows={data.mrr_by_plan} name="plan" value="mrr" format={money} empty="No paying subscriptions yet." />
            <BarList title="Overdue by age" note="Amount still owed, by days past due" rows={data.overdue_aging} name="bucket" value="amount" format={money} empty="Nothing overdue." />
            <BarList title="Why customers left" note={from || to ? 'In these dates' : 'In the last 30 days'} rows={data.churn_reasons} name="reason" value="count" format={(v) => v.toLocaleString('en-IN')} empty="No cancellations in this period." />
          </div>
          <div className="grid-2">
            <div className="card flush">
              <h2>Oldest overdue invoices</h2>
              <DataTable
                rows={data.oldest_overdue}
                empty="Nothing overdue."
                columns={[
                  { key: 'number', label: 'Invoice', render: (r) => <Link to={`/invoices/${r.id}`}>{r.number}</Link> },
                  { key: 'customer_name', label: 'Customer' },
                  { key: 'due_date', label: 'Due' },
                  { key: 'amount_due', label: 'Amount due', right: true, render: (r) => money(r.amount_due) },
                ]}
              />
            </div>
            <div className="stack">
              <div className="card flush">
                <h2>Subscriptions by stage</h2>
                <DataTable
                  rowKey="state"
                  rows={Object.entries(data.subscriptions_by_state).map(([state, count]) => ({ state, count }))}
                  columns={[
                    { key: 'state', label: 'Stage', render: (r) => <Link to={`/subscriptions?state=${r.state}`}><Badge value={r.state} /></Link> },
                    { key: 'count', label: 'Count', right: true, render: (r) => r.count.toLocaleString('en-IN') },
                  ]}
                />
              </div>
              <div className="card flush">
                <h2>Payments by method</h2>
                <DataTable
                  rowKey="method"
                  rows={data.payments_by_method}
                  empty="No payments in this period."
                  columns={[
                    { key: 'method', label: 'Method' },
                    { key: 'count', label: 'Payments', right: true, render: (r) => r.count.toLocaleString('en-IN') },
                    { key: 'amount', label: 'Amount', right: true, render: (r) => money(r.amount) },
                  ]}
                />
              </div>
            </div>
          </div>
        </>
      )}
    </section>
  )
}

/* ------------------------------------------------------------ revenue */

const shortMonth = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { month: 'short', year: '2-digit' })
const longMonth = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })

function RecognitionChart({ rows }) {
  const value = (r) => Number(r.recognized) + Number(r.scheduled)
  const peak = Math.max(...rows.map(value), 1)
  return (
    <div className="card flush">
      <div className="chart-head">
        <h2>Revenue earned by month</h2>
        <div className="legend"><span><i className="swatch" />Recognized</span><span><i className="swatch later" />Scheduled</span></div>
      </div>
      <div className="chart">
        <div className="plot" role="img" aria-label="Revenue earned by month. Every value is in the table below.">
          {rows.map((r) => (
            <div className="bar-slot" key={r.month} tabIndex={0}>
              <div className="bar-tip" style={{ bottom: `${(value(r) / peak) * 100}%` }}><span className="tip">{longMonth(r.month)}: {money(r.recognized)} recognized{Number(r.scheduled) > 0 ? `, ${money(r.scheduled)} scheduled` : ''}</span></div>
              <div className="bar-stack">
                {Number(r.scheduled) > 0 && <div className="bar later" style={{ height: `${(Number(r.scheduled) / peak) * 100}%` }} />}
                {Number(r.recognized) > 0 && <div className="bar" style={{ height: `${(Number(r.recognized) / peak) * 100}%` }} />}
              </div>
            </div>
          ))}
        </div>
        <div className="axis">{rows.map((r) => <span key={r.month}>{shortMonth(r.month)}</span>)}</div>
      </div>
    </div>
  )
}

function ShareTable({ title, rows, name, empty }) {
  return (
    <div className="card flush share">
      <h2>{title}</h2>
      <DataTable
        rowKey="name"
        rows={rows}
        empty={empty}
        columns={[
          { key: 'name', label: name, render: (r) => label(r.name) },
          { key: 'amount', label: 'Recognized', right: true, render: (r) => money(r.amount) },
          { key: 'share', label: 'Share', right: true, render: (r) => `${r.share}%` },
        ]}
      />
    </div>
  )
}

export function Revenue() {
  const toast = useToast()
  const plans = useOptions('/plans/')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [plan, setPlan] = useState('')
  const [period, setPeriod] = useState('')
  const params = query({ from: from && `${from}-01`, to: to && `${to}-01`, plan, period })
  const { data, error, loading, reload } = useLoad(`/reports/revenue/${params}`)
  const exportCsv = async () => {
    try {
      await api.download(`/reports/export/revenue/${params}`, 'brightloop-revenue.csv')
    } catch (err) {
      toast(err.message, 'bad')
    }
  }
  const s = data?.summary
  // Future months with nothing scheduled only add empty rows.
  const history = data?.history.filter((r) => r.status !== 'scheduled' || Number(r.scheduled) > 0) || []
  return (
    <section>
      <header className="page-head">
        <div><h1>Revenue</h1><p className="muted">Each invoice is earned evenly per day over the period it covers. Figures are before tax.</p></div>
        <button onClick={exportCsv}>Export CSV</button>
      </header>
      <div className="toolbar">
        <Field label="From month"><input type="month" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
        <Field label="To month"><input type="month" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
        <Field label="Plan">
          <select value={plan} onChange={(e) => setPlan(e.target.value)}>
            <option value="">All plans</option>
            {plans.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </Field>
        <Field label="Billing period">
          <select value={period} onChange={(e) => setPeriod(e.target.value)}>
            <option value="">All periods</option>
            {['daily', 'weekly', 'monthly', 'yearly'].map((p) => <option key={p} value={p}>{label(p)}</option>)}
          </select>
        </Field>
      </div>
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data && <p className="muted">Loading…</p>}
      {data && (
        <>
          <div className="tiles">
            <Tile title="Recognized to date" value={money(s.recognized_to_date)} note={`Earned up to ${data.as_of}`} />
            <Tile title="Deferred revenue" value={money(s.deferred)} note="Billed, but not earned yet" />
            <Tile title="Recognized this month" value={money(s.recognized_this_month)} note={`${money(s.scheduled_this_month)} more scheduled this month`} />
            <Tile title="Recognized last month" value={money(s.recognized_last_month)} note="A full month" />
            <Tile title="Billed to date" value={money(s.billed_to_date)} note="Confirmed and paid invoices" />
          </div>
          <RecognitionChart rows={history} />
          <div className="card flush">
            <h2>Revenue history</h2>
            <DataTable
              rowKey="month"
              rows={[...history].reverse()}
              columns={[
                { key: 'month', label: 'Month', render: (r) => longMonth(r.month) },
                { key: 'status', label: 'Status', render: (r) => <Badge value={r.status} /> },
                { key: 'recognized', label: 'Recognized', right: true, render: (r) => money(r.recognized) },
                { key: 'scheduled', label: 'Scheduled', right: true, render: (r) => (Number(r.scheduled) ? money(r.scheduled) : '—') },
                { key: 'change', label: 'On prior month', right: true, render: (r) => (r.change === null ? '—' : `${r.change > 0 ? '+' : ''}${r.change}%`) },
                { key: 'billed', label: 'Billed', right: true, render: (r) => money(r.billed) },
                { key: 'collected', label: 'Collected, with tax', right: true, render: (r) => money(r.collected) },
                { key: 'deferred_end', label: 'Deferred at month end', right: true, render: (r) => money(r.deferred_end) },
              ]}
            />
          </div>
          <div className="grid-3">
            <ShareTable title="By plan" name="Plan" rows={data.by_plan} empty="No revenue in this period." />
            <ShareTable title="Monthly and yearly customers" name="Billing period" rows={data.by_period} empty="No revenue in this period." />
            <ShareTable title="Top customers" name="Customer" rows={data.top_customers} empty="No revenue in this period." />
          </div>
        </>
      )}
    </section>
  )
}

/* ------------------------------------------------------------ subscriptions */

const SUB_STATES = ['draft', 'quotation', 'confirmed', 'active', 'paused', 'closed']

export function Subscriptions() {
  const { user } = useAuth()
  const team = user.role !== 'customer'
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [picking, setPicking] = useState(false)
  const debounced = useDebounced(search)
  const state = params.get('state') || ''
  const { data, loading, error, reload } = useLoad(`/subscriptions/${query({ page, search: debounced, state })}`)
  const columns = [
    { key: 'number', label: 'Number' },
    ...(team ? [{ key: 'customer_name', label: 'Customer' }] : []),
    { key: 'plan_name', label: 'Plan' },
    { key: 'start_date', label: 'Start' },
    { key: 'expiry_date', label: 'Expiry' },
    { key: 'recurring_total', label: 'Per period', right: true, render: (r) => money(r.recurring_total) },
    { key: 'state', label: 'Stage', render: (r) => <><Badge value={r.state} />{inTrial(r) && <small className="trial-tag">Trial</small>}</> },
  ]
  return (
    <section>
      <header className="page-head">
        <div><h1>{team ? 'Subscriptions' : 'My subscriptions'}</h1></div>
        {!team && <Link className="button primary" to="/browse-plans">Browse plans</Link>}
        {team && (
          <div className="row">
            <button onClick={() => setPicking(true)}>From template</button>
            <Link className="button primary" to="/subscriptions/new">New subscription</Link>
          </div>
        )}
      </header>
      <div className="toolbar">
        <input type="search" aria-label="Search" placeholder="Search number, customer or plan" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }} />
        <select aria-label="Stage" value={state} onChange={(e) => { setPage(1); setParams(e.target.value ? { state: e.target.value } : {}) }}>
          <option value="">All stages</option>
          {SUB_STATES.filter((s) => team || s !== 'draft').map((s) => <option key={s} value={s}>{label(s)}</option>)}
        </select>
      </div>
      <ErrorBox error={error} onRetry={reload} />
      <div className="card flush">
        <DataTable columns={columns} rows={data?.results} loading={loading} empty="No subscriptions found." onRow={(r) => navigate(`/subscriptions/${r.id}`)} />
        {data && <Pager page={page} count={data.count} onPage={setPage} />}
      </div>
      {picking && <FromTemplate onClose={() => setPicking(false)} />}
    </section>
  )
}

function FromTemplate({ onClose }) {
  const templates = useOptions('/templates/')
  const terms = useOptions('/payment-terms/')
  const navigate = useNavigate()
  const [form, setForm] = useState({ template: '', customer: null, payment_term: '', start_date: isoToday(), expiry_date: '' })
  const [error, setError] = useState(null)
  const set = (patch) => setForm((f) => ({ ...f, ...patch }))
  const submit = async (event) => {
    event.preventDefault()
    setError(null)
    try {
      const sub = await api.post('/subscriptions/from_template/', form)
      navigate(`/subscriptions/${sub.id}`)
    } catch (err) {
      setError(err)
    }
  }
  return (
    <Modal title="Start from a quotation template" onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <ErrorBox error={error} />
        <Field label="Template" error={error?.fields?.template}>
          <select required value={form.template} onChange={(e) => set({ template: e.target.value })}>
            <option value="">Choose</option>
            {templates.map((t) => <option key={t.id} value={t.id}>{t.name} ({t.validity_days} days)</option>)}
          </select>
        </Field>
        <Field label="Customer" error={error?.fields?.customer}>
          <SearchPicker path="/customers/" display={customerName} value={form.customer} onChange={(customer) => set({ customer })} />
        </Field>
        <Field label="Payment terms" error={error?.fields?.payment_term}>
          <select required value={form.payment_term} onChange={(e) => set({ payment_term: e.target.value })}>
            <option value="">Choose</option>
            {terms.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </Field>
        <Field label="Start date" error={error?.fields?.start_date}><input type="date" required value={form.start_date} onChange={(e) => set({ start_date: e.target.value })} /></Field>
        <Field label="Expiry date" error={error?.fields?.expiry_date}><input type="date" required value={form.expiry_date} onChange={(e) => set({ expiry_date: e.target.value })} /></Field>
        <footer><button type="button" onClick={onClose}>Cancel</button><button className="primary">Create quotation</button></footer>
      </form>
    </Modal>
  )
}

export function SubscriptionForm() {
  const { id } = useParams()
  return id ? <EditLoader id={id} /> : <SubscriptionEditor />
}

function EditLoader({ id }) {
  const { data, error, reload } = useLoad(`/subscriptions/${id}/`)
  if (error) return <ErrorBox error={error} onRetry={reload} />
  return data ? <SubscriptionEditor record={data} /> : <p className="muted">Loading…</p>
}

function SubscriptionEditor({ record }) {
  const navigate = useNavigate()
  const plans = useOptions('/plans/')
  const terms = useOptions('/payment-terms/')
  const products = useOptions('/products/')
  const { user } = useAuth()
  const sellers = useOptions(user.role === 'admin' ? '/staff/?department=sales' : null)
  const [form, setForm] = useState(record ? {
    customer: record.customer, plan: record.plan, payment_term: record.payment_term, start_date: record.start_date, expiry_date: record.expiry_date, salesperson: record.salesperson,
    lines: record.lines.filter((l) => !l.is_plan_fee).map((l) => ({ product: l.product, variant: l.variant, quantity: l.quantity, unit_price: l.unit_price, taxes: l.tax_ids })),
  } : { customer: null, plan: '', payment_term: '', start_date: isoToday(), expiry_date: '', lines: [{ product: '', variant: null, quantity: 1 }] })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const set = (patch) => setForm((f) => ({ ...f, ...patch }))
  const plan = plans.find((p) => p.id === Number(form.plan))

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const saved = record ? await api.put(`/subscriptions/${record.id}/`, form) : await api.post('/subscriptions/', form)
      navigate(`/subscriptions/${saved.id}`)
    } catch (err) {
      setError(err)
      setBusy(false)
    }
  }
  return (
    <section>
      <header className="page-head"><h1>{record ? `Edit ${record.number}` : 'New subscription'}</h1></header>
      <form className="card form" onSubmit={submit}>
        <ErrorBox error={error} />
        <div className="grid-2">
          <Field label="Customer" error={error?.fields?.customer}>
            <SearchPicker path="/customers/" display={customerName} value={form.customer} onChange={(customer) => set({ customer })} />
          </Field>
          <Field label="Plan" error={error?.fields?.plan} help={plan ? `${money(plan.price)} ${plan.billing_period}, minimum quantity ${plan.min_quantity}` : null}>
            <select required value={form.plan} onChange={(e) => set({ plan: Number(e.target.value) })}>
              <option value="">Choose</option>
              {plans.filter((p) => p.is_active).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </Field>
          {user.role === 'admin' && (
            <Field label="Sold by" error={error?.fields?.salesperson}>
              <select value={form.salesperson || ''} onChange={(e) => set({ salesperson: e.target.value ? Number(e.target.value) : null })}>
                <option value="">Nobody</option>
                {sellers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </Field>
          )}
          <Field label="Start date" error={error?.fields?.start_date}><input type="date" required value={form.start_date} onChange={(e) => set({ start_date: e.target.value })} /></Field>
          <Field label="Expiry date" error={error?.fields?.expiry_date}><input type="date" required value={form.expiry_date} onChange={(e) => set({ expiry_date: e.target.value })} /></Field>
          <Field label="Payment terms" error={error?.fields?.payment_term}>
            <select required value={form.payment_term} onChange={(e) => set({ payment_term: Number(e.target.value) })}>
              <option value="">Choose</option>
              {terms.filter((t) => t.is_active).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </Field>
        </div>
        <h2>Product lines</h2>
        <p className="muted">Unit price starts from the product and variant. Taxes come from the product, and are calculated on saving.{plan?.price > 0 ? ` The ${money(plan.price)} plan fee is added as its own line.` : ''}</p>
        <LineEditor value={form.lines} onChange={(lines) => set({ lines })} products={products.filter((p) => p.is_active)} showPrice error={error?.fields?.lines} />
        <footer><button type="button" onClick={() => navigate(-1)}>Cancel</button><button className="primary" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button></footer>
      </form>
    </section>
  )
}

const STAGES = ['draft', 'quotation', 'confirmed', 'active', 'closed']
const SUB_ACTIONS = {
  quote: 'Send quotation', confirm: 'Confirm', activate: 'Activate', pause: 'Pause', resume: 'Resume', renew: 'Renew now',
}
const CLOSE_REASONS = [['too_expensive', 'Too expensive'], ['missing_features', 'Missing features'], ['not_using', 'Not using it enough'], ['switched', 'Switched to another product'], ['other', 'Something else']]

function ActionModal({ title, submitText, danger, onClose, onSubmit, children, extra }) {
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await onSubmit()
    } catch (err) {
      setError(err)
      setBusy(false)
    }
  }
  return (
    <Modal title={title} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <ErrorBox error={error} />
        {typeof children === 'function' ? children(error) : children}
        <footer><button type="button" onClick={onClose}>Keep as it is</button>{extra}<button className={danger ? 'danger' : 'primary'} disabled={busy}>{submitText}</button></footer>
      </form>
    </Modal>
  )
}

function CloseModal({ sub, canPause, onClose, send }) {
  const [reason, setReason] = useState('')
  const [note, setNote] = useState('')
  return (
    <ActionModal
      title={`Close ${sub.number}?`} submitText="Close subscription" danger onClose={onClose}
      onSubmit={() => send('close', { reason, note }, 'Subscription closed.')}
      extra={canPause && <button type="button" className="primary" onClick={() => send('pause', {}, 'Subscription paused. Resume it any time.')}>Pause instead</button>}
    >
      <p>Billing stops, and this cannot be undone.{canPause && ' You can pause instead. You are not billed while paused, and you can resume at any time.'}</p>
      <Field label="Why are you leaving?">
        <select value={reason} onChange={(e) => setReason(e.target.value)}>
          <option value="">Prefer not to say</option>
          {CLOSE_REASONS.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
        </select>
      </Field>
      <Field label="Anything else?"><input maxLength="255" value={note} onChange={(e) => setNote(e.target.value)} /></Field>
    </ActionModal>
  )
}

function ChangePlanModal({ sub, team, onClose, send }) {
  const { data } = useLoad(team ? '/plans/?page_size=100' : '/public/plans/')
  const all = data?.results || data || []
  const options = all.filter((p) => p.billing_period === sub.billing_period && p.id !== sub.plan && p.is_active !== false)
  const [plan, setPlan] = useState('')
  const chosen = options.find((p) => p.id === Number(plan))
  return (
    <ActionModal title="Change plan" submitText="Change plan" onClose={onClose} onSubmit={() => send('change_plan', { plan: Number(plan) }, 'Plan changed.')}>
      {(error) => (
        <>
          <p className="muted">You are on {sub.plan_name}. The change applies now. A higher price is charged for the days left in this period, and a lower price leaves a credit for your next invoices.</p>
          <Field label={`New ${sub.billing_period} plan`} error={error?.fields?.plan} help={chosen ? `${money(chosen.price)} ${chosen.billing_period}, before tax` : null}>
            <select required value={plan} onChange={(e) => setPlan(e.target.value)}>
              <option value="">{data && !options.length ? 'No other plans available' : 'Choose'}</option>
              {options.map((p) => <option key={p.id} value={p.id}>{p.name}, {money(p.price)}</option>)}
            </select>
          </Field>
        </>
      )}
    </ActionModal>
  )
}

function RedeemModal({ onClose, send }) {
  const [code, setCode] = useState('')
  return (
    <ActionModal title="Add a promo code" submitText="Apply code" onClose={onClose} onSubmit={() => send('redeem', { code }, 'Code added. It applies from your next invoice.')}>
      {(error) => <Field label="Promo code" error={error?.fields?.code}><input required autoComplete="off" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} /></Field>}
    </ActionModal>
  )
}

function AdjustModal({ onClose, send }) {
  const [form, setForm] = useState({ kind: 'credit', amount: '', note: '' })
  const set = (patch) => setForm((f) => ({ ...f, ...patch }))
  return (
    <ActionModal title="Charge or credit" submitText="Save" onClose={onClose} onSubmit={() => send('adjust', form, form.kind === 'credit' ? 'Credit added.' : 'Charge invoiced.')}>
      {(error) => (
        <>
          <Field label="Type" error={error?.fields?.kind}>
            <select value={form.kind} onChange={(e) => set({ kind: e.target.value })}>
              <option value="credit">Credit: taken off the next invoices</option>
              <option value="charge">One-off charge: invoiced now</option>
            </select>
          </Field>
          <Field label="Amount" error={error?.fields?.amount}><input type="number" min="0.01" step="0.01" required value={form.amount} onChange={(e) => set({ amount: e.target.value })} /></Field>
          <Field label="Reason" error={error?.fields?.note} help="The customer can see this."><input required maxLength="200" value={form.note} onChange={(e) => set({ note: e.target.value })} /></Field>
        </>
      )}
    </ActionModal>
  )
}

function Timeline({ events }) {
  return (
    <div className="card">
      <h2>Activity</h2>
      {!events.length ? <p className="muted">Nothing recorded yet.</p> : (
        <ol className="timeline">
          {events.map((e) => (
            <li key={e.id}><b>{e.message}</b><small>{e.actor_name}, {new Date(e.created_at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })}</small></li>
          ))}
        </ol>
      )}
    </div>
  )
}

export function BrowsePlans() {
  const navigate = useNavigate()
  const { data, error, reload } = useLoad('/public/plans/')
  const [problem, setProblem] = useState(null)
  const [busy, setBusy] = useState(null)
  const start = async (plan) => {
    setBusy(plan.id)
    setProblem(null)
    try {
      navigate(`/subscriptions/${(await api.post('/subscriptions/start/', { plan: plan.id })).id}`)
    } catch (err) {
      setProblem(err)
      setBusy(null)
    }
  }
  return (
    <section>
      <header className="page-head"><div><h1>Browse plans</h1><p className="muted">Start a plan yourself. Prices are before tax.</p></div></header>
      <ErrorBox error={error || problem} onRetry={error ? reload : undefined} />
      {!data && !error && <p className="muted">Loading…</p>}
      {data && !data.length && <p className="muted">No plans are open right now.</p>}
      <div className="tiles plan-tiles">
        {data?.map((plan) => (
          <div className="tile" key={plan.id}>
            <span>{label(plan.billing_period)}</span>
            <h2>{plan.name}</h2>
            <strong>{money(plan.price)}</strong>
            <small>{plan.trial_days ? `${plan.trial_days} days free, for first-time customers on this plan` : 'Billed from today'}</small>
            {plan.self_serve
              ? <button className="primary" disabled={busy !== null} onClick={() => start(plan)}>{busy === plan.id ? 'Starting…' : plan.trial_days ? 'Start free trial' : 'Start plan'}</button>
              : <small>From {plan.min_quantity} seats. Our team sets this one up with you.</small>}
          </div>
        ))}
      </div>
    </section>
  )
}

export function Profile() {
  const toast = useToast()
  const { data, error, reload } = useLoad('/auth/me/')
  const [form, setForm] = useState(null)
  const [problem, setProblem] = useState(null)
  useEffect(() => { if (data) setForm(data) }, [data])
  const set = (name) => (e) => setForm((f) => ({ ...f, [name]: e.target.value }))
  const submit = async (event) => {
    event.preventDefault()
    setProblem(null)
    try {
      const { first_name, last_name, company, phone, address } = form
      await api.patch('/auth/me/', { first_name, last_name, company, phone, address })
      toast('Profile saved.')
    } catch (err) {
      setProblem(err)
    }
  }
  if (error) return <ErrorBox error={error} onRetry={reload} />
  if (!form) return <p className="muted">Loading…</p>
  const field = (name, text, help) => <Field label={text} help={help} error={problem?.fields?.[name]}><input value={form[name] || ''} onChange={set(name)} /></Field>
  return (
    <section>
      <header className="page-head"><div><h1>Profile</h1><p className="muted">{form.email}</p></div></header>
      <form className="card form narrow" onSubmit={submit}>
        <ErrorBox error={problem} />
        {field('first_name', 'First name')}
        {field('last_name', 'Last name')}
        {field('company', 'Company')}
        {field('phone', 'Phone', 'With country code, for payment reminders by SMS.')}
        <Field label="Billing address" error={problem?.fields?.address}><textarea rows="3" value={form.address || ''} onChange={set('address')} /></Field>
        <footer><button className="primary">Save</button></footer>
      </form>
    </section>
  )
}

function Stepper({ state, stages = STAGES }) {
  const current = stages.indexOf(state === 'paused' ? 'active' : state)
  return (
    <ol className="stepper" aria-label="Progress">
      {stages.map((stage, index) => (
        <li key={stage} className={index < current ? 'done' : index === current ? 'now' : ''} aria-current={index === current ? 'step' : undefined}>
          {state === 'paused' && stage === 'active' ? 'Paused' : label(stage)}
        </li>
      ))}
    </ol>
  )
}

export function SubscriptionDetail() {
  const { id } = useParams()
  const { user } = useAuth()
  const team = user.role !== 'customer'
  const navigate = useNavigate()
  const toast = useToast()
  const { data: sub, error, reload } = useLoad(`/subscriptions/${id}/`)
  const invoices = useLoad(`/invoices/${query({ subscription: id, page_size: 50 })}`)
  const [modal, setModal] = useState(null)
  // Used by the dialogs, which show the error themselves.
  const send = async (path, body, message) => {
    await api.post(`/subscriptions/${id}/${path}/`, body)
    toast(message)
    setModal(null)
    reload()
    invoices.reload()
  }

  const act = async (path, body, message) => {
    try {
      await api.post(`/subscriptions/${id}/${path}/`, body)
      if (message) toast(message)
      reload()
      invoices.reload()
    } catch (err) {
      toast(err.message, 'bad')
    }
  }
  const billNow = async () => {
    try {
      const result = await api.post(`/subscriptions/${id}/generate_invoice/`)
      toast(result.invoices_created ? `${result.invoices_created} invoice(s) created.` : 'Nothing is due yet.')
      reload()
      invoices.reload()
    } catch (err) {
      toast(err.message, 'bad')
    }
  }
  const remove = async () => {
    if (!window.confirm('Delete this draft? This cannot be undone.')) return
    try {
      await api.del(`/subscriptions/${id}/`)
      navigate('/subscriptions')
    } catch (err) {
      toast(err.message, 'bad')
    }
  }
  if (error) return <ErrorBox error={error} onRetry={reload} />
  if (!sub) return <p className="muted">Loading…</p>
  const can = (name) => sub.allowed_actions.includes(name)
  const confirmFirst = { pause: 'Pause this subscription? It will not be billed while paused.' }
  return (
    <section>
      <header className="page-head">
        <div><h1>{sub.number} <Badge value={sub.state} /></h1><p className="muted">{sub.customer_name}</p></div>
        <div className="row">
          {can('edit') && <Link className="button" to={`/subscriptions/${id}/edit`}>Edit</Link>}
          {can('delete') && <button className="danger" onClick={remove}>Delete</button>}
          {team && sub.state === 'active' && <button onClick={billNow}>Generate invoice</button>}
          {Object.entries(SUB_ACTIONS).filter(([name]) => can(name)).map(([name, text]) => (
            <button key={name} className={['quote', 'confirm', 'activate'].includes(name) ? 'primary' : ''} onClick={() => (!confirmFirst[name] || window.confirm(confirmFirst[name])) && act(name, {}, `${text}: done.`)}>{text}</button>
          ))}
          {can('change_plan') && <button onClick={() => setModal('plan')}>Change plan</button>}
          {can('redeem') && <button onClick={() => setModal('code')}>Promo code</button>}
          {can('adjust') && <button onClick={() => setModal('adjust')}>Charge or credit</button>}
          {can('auto_renew') && (
            sub.auto_renew
              ? <button onClick={() => window.confirm(`Turn off automatic renewal? This subscription will end on ${sub.expiry_date}.`) && act('auto_renew', { enabled: false }, `Automatic renewal is off. It ends on ${sub.expiry_date}.`)}>Turn off renewal</button>
              : <button className="primary" onClick={() => act('auto_renew', { enabled: true }, 'Automatic renewal is on.')}>Turn on renewal</button>
          )}
          {can('close') && <button className="danger" onClick={() => setModal('close')}>{team ? 'Close' : 'Cancel now'}</button>}
        </div>
      </header>
      {team && <Stepper state={sub.state} />}
      <div className="card">
        <dl className="facts">
          <div><dt>Plan</dt><dd>{sub.plan_name} ({sub.billing_period})</dd></div>
          <div><dt>Start date</dt><dd>{sub.start_date}</dd></div>
          <div><dt>{sub.renews ? 'Renews on' : 'Ends on'}</dt><dd>{sub.expiry_date}{sub.renews && <small className="fact-note">Automatically, unless you turn it off</small>}</dd></div>
          {team && sub.salesperson_name && <div><dt>Sold by</dt><dd>{sub.salesperson_name}</dd></div>}
          <div><dt>Payment terms</dt><dd>{sub.payment_term_name}</dd></div>
          {inTrial(sub) && <div><dt>Free trial until</dt><dd>{sub.trial_ends}</dd></div>}
          {sub.next_invoice_date && sub.state === 'active' && <div><dt>Next invoice</dt><dd>{sub.next_invoice_date}</dd></div>}
          {Number(sub.credit_balance) > 0 && <div><dt>Credit for next invoices</dt><dd>{money(sub.credit_balance)}</dd></div>}
          {sub.promotions.length > 0 && <div><dt>Offers</dt><dd>{sub.promotions.join(', ')}</dd></div>}
          {sub.quotation_valid_until && sub.state === 'quotation' && <div><dt>Quotation valid until</dt><dd>{sub.quotation_valid_until}</dd></div>}
          <div><dt>Per billing period</dt><dd>{money(sub.recurring_total)} + tax</dd></div>
        </dl>
      </div>
      <div className="card flush">
        <h2>Lines</h2>
        <DataTable
          rows={sub.lines}
          columns={[
            { key: 'description', label: 'Product', render: (l) => <span className={l.is_enabled ? '' : 'off'}>{l.description}</span> },
            { key: 'quantity', label: 'Quantity', right: true },
            { key: 'unit_price', label: 'Unit price', right: true, render: (l) => money(l.unit_price) },
            { key: 'taxes', label: 'Taxes', render: (l) => l.taxes.join(', ') || '—' },
            { key: 'amount', label: 'Amount', right: true, render: (l) => money(l.amount) },
            ...(['active', 'paused'].includes(sub.state) ? [{
              key: 'toggle', label: 'Add-on', right: true,
              render: (l) => (l.is_addon ? <button onClick={() => act('toggle_addon', { line: l.id, enabled: !l.is_enabled }, `Add-on switched ${l.is_enabled ? 'off' : 'on'}.`)}>{l.is_enabled ? 'Switch off' : 'Switch on'}</button> : ''),
            }] : []),
          ]}
        />
      </div>
      <div className="card flush">
        <h2>Invoices</h2>
        <InvoiceTable rows={invoices.data?.results} loading={invoices.loading} />
      </div>
      <Timeline events={sub.events} />
      {modal === 'close' && <CloseModal sub={sub} canPause={can('pause')} onClose={() => setModal(null)} send={send} />}
      {modal === 'plan' && <ChangePlanModal sub={sub} team={team} onClose={() => setModal(null)} send={send} />}
      {modal === 'code' && <RedeemModal onClose={() => setModal(null)} send={send} />}
      {modal === 'adjust' && <AdjustModal onClose={() => setModal(null)} send={send} />}
    </section>
  )
}

/* ------------------------------------------------------------ invoices */

function invoiceBadge(row) {
  return <Badge value={row.is_overdue ? 'overdue' : row.state} />
}

function InvoiceTable({ rows, loading, selected, onSelect }) {
  const navigate = useNavigate()
  const columns = [
    ...(onSelect ? [{
      key: 'pick', label: '',
      render: (r) => <input type="checkbox" aria-label={`Select ${r.number}`} checked={selected.includes(r.id)} onClick={(e) => e.stopPropagation()} onChange={(e) => onSelect(e.target.checked ? [...selected, r.id] : selected.filter((id) => id !== r.id))} />,
    }] : []),
    { key: 'number', label: 'Invoice' },
    { key: 'customer_name', label: 'Customer' },
    { key: 'invoice_date', label: 'Date' },
    { key: 'due_date', label: 'Due' },
    { key: 'total', label: 'Total', right: true, render: (r) => money(r.total) },
    { key: 'amount_due', label: 'Due amount', right: true, render: (r) => (r.state === 'cancelled' ? '—' : money(r.amount_due)) },
    { key: 'state', label: 'Status', render: invoiceBadge },
  ]
  return <DataTable columns={columns} rows={rows} loading={loading} empty="No invoices found." onRow={(r) => navigate(`/invoices/${r.id}`)} />
}

const PAYMENT_TABS = [['', 'All'], ['outstanding', 'Outstanding'], ['overdue', 'Overdue'], ['paid', 'Paid']]

export function Invoices() {
  const { user } = useAuth()
  const team = user.role !== 'customer'
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [selected, setSelected] = useState([])
  const debounced = useDebounced(search)
  const status = params.get('payment_status') || ''
  const state = params.get('state') || ''
  const { data, loading, error, reload } = useLoad(`/invoices/${query({ page, search: debounced, payment_status: status, state, invoice_date_from: from, invoice_date_to: to })}`)

  const bulk = async (action) => {
    try {
      const result = await api.post('/invoices/bulk/', { action, ids: selected })
      toast(`${result.done} invoice(s) done${result.failed.length ? `, ${result.failed.length} skipped: ${result.failed[0].error}` : ''}.`, result.failed.length ? 'bad' : 'good')
      setSelected([])
      reload()
    } catch (err) {
      toast(err.message, 'bad')
    }
  }
  const runBilling = async () => {
    try {
      const result = await api.post('/billing/run/')
      toast(`${result.invoices_created} invoice(s) created.`)
      reload()
    } catch (err) {
      toast(err.message, 'bad')
    }
  }
  const pageIds = data?.results.map((r) => r.id) || []
  return (
    <section>
      <header className="page-head">
        <div><h1>{team ? 'Invoices' : 'My invoices'}</h1></div>
        {team && <button className="primary" onClick={runBilling}>Run billing</button>}
      </header>
      <div className="tabs" role="tablist">
        {PAYMENT_TABS.map(([value, text]) => (
          <button key={value} role="tab" aria-selected={status === value && !state} className={status === value && !state ? 'on' : ''} onClick={() => { setPage(1); setParams(value ? { payment_status: value } : {}) }}>{text}</button>
        ))}
        {team && <button role="tab" aria-selected={state === 'draft'} className={state === 'draft' ? 'on' : ''} onClick={() => { setPage(1); setParams({ state: 'draft' }) }}>Drafts</button>}
      </div>
      <div className="toolbar">
        <input type="search" aria-label="Search" placeholder="Search invoice, customer or subscription" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }} />
        <Field label="From"><input type="date" value={from} onChange={(e) => { setFrom(e.target.value); setPage(1) }} /></Field>
        <Field label="To"><input type="date" value={to} onChange={(e) => { setTo(e.target.value); setPage(1) }} /></Field>
      </div>
      {team && (
        <div className="toolbar">
          <button onClick={() => setSelected(selected.length ? [] : pageIds)}>{selected.length ? 'Clear selection' : 'Select this page'}</button>
          <button disabled={!selected.length} onClick={() => bulk('confirm')}>Confirm selected</button>
          <button disabled={!selected.length} onClick={() => bulk('send')}>Send selected</button>
        </div>
      )}
      <ErrorBox error={error} onRetry={reload} />
      <div className="card flush">
        <InvoiceTable rows={data?.results} loading={loading} selected={selected} onSelect={team ? setSelected : undefined} />
        {data && <Pager page={page} count={data.count} onPage={setPage} />}
      </div>
    </section>
  )
}

const METHODS = [['bank_transfer', 'Bank transfer'], ['card', 'Card'], ['upi', 'UPI'], ['cash', 'Cash'], ['cheque', 'Cheque']]

function PaymentModal({ invoice, onClose, onDone, request }) {
  const [form, setForm] = useState({ method: 'bank_transfer', amount: invoice.amount_due, date: isoToday(), note: '' })
  const [error, setError] = useState(null)
  const set = (patch) => setForm((f) => ({ ...f, ...patch }))
  const submit = async (event) => {
    event.preventDefault()
    setError(null)
    try {
      if (request) await api.post(`/invoices/${invoice.id}/request_payment/`, { method: form.method, amount: form.amount, reference: form.note })
      else await api.post('/payments/', { ...form, invoice: invoice.id })
      onDone()
    } catch (err) {
      setError(err)
    }
  }
  return (
    <Modal title={request ? `Tell us you paid ${invoice.number}` : `Record payment for ${invoice.number}`} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <ErrorBox error={error} />
        {request && <p className="muted">The admin checks that the money arrived, then approves it. Nothing changes on the invoice until then.</p>}
        <Field label="Method" error={error?.fields?.method}>
          <select value={form.method} onChange={(e) => set({ method: e.target.value })}>{METHODS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select>
        </Field>
        <Field label="Amount" error={error?.fields?.amount} help={`${money(invoice.amount_due)} still due`}><input type="number" min="0.01" step="0.01" required value={form.amount} onChange={(e) => set({ amount: e.target.value })} /></Field>
        {!request && <Field label="Date" error={error?.fields?.date}><input type="date" required value={form.date} onChange={(e) => set({ date: e.target.value })} /></Field>}
        <Field label={request ? 'Payment reference' : 'Note'} error={error?.fields?.note || error?.fields?.reference} help={request ? 'For example, the UPI or bank reference.' : null}><input maxLength="255" value={form.note} onChange={(e) => set({ note: e.target.value })} /></Field>
        <footer><button type="button" onClick={onClose}>Cancel</button><button className="primary">{request ? 'Send for approval' : 'Record payment'}</button></footer>
      </form>
    </Modal>
  )
}

function CancelModal({ invoice, onClose, onDone }) {
  const [rebill, setRebill] = useState(false)
  const [error, setError] = useState(null)
  const submit = async (event) => {
    event.preventDefault()
    try {
      await api.post(`/invoices/${invoice.id}/cancel/`, { rebill })
      onDone()
    } catch (err) {
      setError(err)
    }
  }
  return (
    <Modal title={`Cancel ${invoice.number}?`} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <ErrorBox error={error} />
        <p>This cannot be undone. Any discount use on this invoice is returned.</p>
        <label className="check"><input type="checkbox" checked={rebill} onChange={(e) => setRebill(e.target.checked)} /><span>Bill this period again on the next billing run</span></label>
        <footer><button type="button" onClick={onClose}>Keep invoice</button><button className="danger">Cancel invoice</button></footer>
      </form>
    </Modal>
  )
}

function RecognitionCard({ id, state }) {
  const { data } = useLoad(`/invoices/${id}/recognition/?state=${state}`)
  if (!data?.length) return null
  return (
    <div className="card flush no-print">
      <h2>Revenue recognition</h2>
      <DataTable
        rowKey="month"
        rows={data}
        columns={[
          { key: 'month', label: 'Month', render: (r) => longMonth(r.month) },
          { key: 'recognized', label: 'Recognized', right: true, render: (r) => money(r.recognized) },
          { key: 'scheduled', label: 'Scheduled', right: true, render: (r) => (Number(r.scheduled) ? money(r.scheduled) : '—') },
        ]}
      />
    </div>
  )
}

export function InvoiceDetail() {
  const { id } = useParams()
  const toast = useToast()
  const { user } = useAuth()
  const { data: inv, error, reload } = useLoad(`/invoices/${id}/`)
  const [modal, setModal] = useState(null)
  const [params, setParams] = useSearchParams()
  const sessionId = params.get('session_id')

  useEffect(() => {
    if (!sessionId) return
    api.post(`/invoices/${id}/checkout_complete/`, { session_id: sessionId })
      .then((result) => toast(result.state === 'paid' ? 'Payment received. Thank you.' : 'Payment is still processing.'))
      .catch((err) => toast(err.message, 'bad'))
      .finally(() => { setParams({}, { replace: true }); reload() })
  }, [sessionId]) // eslint-disable-line react-hooks/exhaustive-deps

  const payOnline = async () => {
    try {
      location.assign((await api.post(`/invoices/${id}/checkout/`)).url)
    } catch (err) {
      toast(`${err.message} You can use "I paid another way" instead.`, 'bad')
    }
  }
  const act = async (path, message) => {
    try {
      await api.post(`/invoices/${id}/${path}/`)
      toast(message)
      reload()
    } catch (err) {
      toast(err.message, 'bad')
    }
  }
  if (error) return <ErrorBox error={error} onRetry={reload} />
  if (!inv) return <p className="muted">Loading…</p>
  const can = (name) => inv.allowed_actions.includes(name)
  const finish = (message) => () => { setModal(null); toast(message); reload() }
  return (
    <section className="invoice">
      <header className="page-head no-print">
        <div><h1>{inv.number} {invoiceBadge(inv)}</h1></div>
        <div className="row">
          {can('pay_online') && <button className="primary" onClick={payOnline}>Pay by card</button>}
          {can('request_payment') && !inv.pending_request && <button onClick={() => setModal('request')}>{can('pay_online') ? 'I paid another way' : 'Tell us you paid'}</button>}
          {can('confirm') && <button className="primary" onClick={() => act('confirm', 'Invoice confirmed.')}>Confirm</button>}
          {can('pay') && <button className="primary" onClick={() => setModal('pay')}>Record payment</button>}
          {can('send') && <button onClick={() => act('send', `Invoice sent to ${inv.customer_email}.`)}>{inv.sent_at ? 'Send again' : 'Send'}</button>}
          <button onClick={() => window.print()}>Print</button>
          {can('cancel') && <button className="danger" onClick={() => setModal('cancel')}>Cancel invoice</button>}
        </div>
      </header>
      {inv.pending_request && <div className="banner no-print"><span><b>Waiting for approval: </b>{money(inv.pending_request.amount)} by {inv.pending_request.method}. The invoice updates once the admin approves it.</span></div>}
      <div className="card paper">
        <div className="paper-head">
          <div><h2>Brightloop Software</h2><p className="muted">Invoice {inv.number}</p></div>
          <dl className="facts small">
            <div><dt>Date</dt><dd>{inv.invoice_date}</dd></div>
            <div><dt>Due</dt><dd>{inv.due_date}</dd></div>
            <div><dt>Period</dt><dd>{inv.period_start} to {inv.period_end}</dd></div>
            {inv.reminder_count > 0 && <div className="no-print"><dt>Reminders sent</dt><dd>{inv.reminder_count}, last on {inv.last_reminder_at}</dd></div>}
            <div><dt>Subscription</dt><dd className="no-print"><Link to={`/subscriptions/${inv.subscription}`}>{inv.subscription_number}</Link></dd><dd className="print-only">{inv.subscription_number}</dd></div>
          </dl>
        </div>
        <p><b>Bill to</b><br />{inv.customer_name}<br />{inv.customer_email}{inv.customer_address && <><br />{inv.customer_address}</>}</p>
        <DataTable
          rows={inv.lines}
          columns={[
            { key: 'description', label: 'Product' },
            { key: 'quantity', label: 'Qty', right: true },
            { key: 'unit_price', label: 'Unit price', right: true, render: (l) => money(l.unit_price) },
            { key: 'discount_amount', label: 'Discount', right: true, render: (l) => (Number(l.discount_amount) ? `−${money(l.discount_amount)}` : '—') },
            { key: 'tax_names', label: 'Tax', render: (l) => l.tax_names || '—' },
            { key: 'tax_amount', label: 'Tax amount', right: true, render: (l) => money(l.tax_amount) },
            { key: 'amount', label: 'Net amount', right: true, render: (l) => money(l.amount) },
          ]}
        />
        <dl className="totals">
          <div><dt>Subtotal</dt><dd>{money(inv.subtotal)}</dd></div>
          {inv.discounts.map((d) => <div key={d.name}><dt>Discount: {d.name}</dt><dd>−{money(d.amount)}</dd></div>)}
          <div><dt>Tax</dt><dd>{money(inv.tax_total)}</dd></div>
          {Number(inv.credit_applied) > 0 && <div><dt>Credit used</dt><dd>−{money(inv.credit_applied)}</dd></div>}
          <div className="grand"><dt>Total</dt><dd>{money(inv.total)}</dd></div>
          <div><dt>Paid</dt><dd>{money(inv.amount_paid)}</dd></div>
          <div className="grand"><dt>Amount due</dt><dd>{money(inv.amount_due)}</dd></div>
        </dl>
      </div>
      {user.role !== 'customer' && <RecognitionCard id={id} state={inv.state} />}
      <div className="card flush no-print">
        <h2>Payments</h2>
        <DataTable
          rows={inv.payments}
          empty="No payments recorded yet."
          columns={[
            { key: 'date', label: 'Date' },
            { key: 'method', label: 'Method', render: (p) => label(p.method) },
            { key: 'note', label: 'Note' },
            { key: 'amount', label: 'Amount', right: true, render: (p) => money(p.amount) },
          ]}
        />
      </div>
      {modal === 'pay' && <PaymentModal invoice={inv} onClose={() => setModal(null)} onDone={finish('Payment recorded.')} />}
      {modal === 'request' && <PaymentModal request invoice={inv} onClose={() => setModal(null)} onDone={finish('Sent to the admin for approval.')} />}
      {modal === 'cancel' && <CancelModal invoice={inv} onClose={() => setModal(null)} onDone={finish('Invoice cancelled.')} />}
    </section>
  )
}

/* ------------------------------------------------------------ payments */

export function Payments() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [method, setMethod] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const debounced = useDebounced(search)
  const { data, loading, error, reload } = useLoad(`/payments/${query({ page, search: debounced, method, date_from: from, date_to: to })}`)
  const reset = (setter) => (event) => { setter(event.target.value); setPage(1) }
  return (
    <section>
      <header className="page-head"><div><h1>Payments</h1><p className="muted">Record a payment from its invoice.</p></div></header>
      <div className="toolbar">
        <input type="search" aria-label="Search" placeholder="Search invoice, customer or note" value={search} onChange={reset(setSearch)} />
        <select aria-label="Method" value={method} onChange={reset(setMethod)}>
          <option value="">All methods</option>
          {METHODS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
        </select>
        <Field label="From"><input type="date" value={from} onChange={reset(setFrom)} /></Field>
        <Field label="To"><input type="date" value={to} onChange={reset(setTo)} /></Field>
      </div>
      <ErrorBox error={error} onRetry={reload} />
      <div className="card flush">
        <DataTable
          rows={data?.results}
          loading={loading}
          empty="No payments found."
          onRow={(p) => navigate(`/invoices/${p.invoice}`)}
          columns={[
            { key: 'date', label: 'Date' },
            { key: 'invoice_number', label: 'Invoice' },
            { key: 'customer_name', label: 'Customer' },
            { key: 'method', label: 'Method', render: (p) => label(p.method) },
            { key: 'note', label: 'Note' },
            { key: 'amount', label: 'Amount', right: true, render: (p) => money(p.amount) },
          ]}
        />
        {data && <Pager page={page} count={data.count} onPage={setPage} />}
      </div>
    </section>
  )
}
