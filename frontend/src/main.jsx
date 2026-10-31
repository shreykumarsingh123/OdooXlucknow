import { createContext, StrictMode, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Link, Navigate, NavLink, Outlet, Route, Routes, useLocation, useSearchParams } from 'react-router-dom'
import { api, tokens } from './api'
import { CrudPage } from './CrudPage'
import * as configs from './configs'
import { Landing } from './landing'
import { BrowsePlans, Dashboard, InvoiceDetail, Invoices, Payments, Profile, Revenue, SubscriptionDetail, SubscriptionForm, Subscriptions } from './pages'
import './styles.css'
import { AdminChat, MyPlan, PlatformOverview, PlatformUsers, RecoveryGate, Shop } from './platform'
import { CustomerDetail, ImportSubscribers, PaymentApprovals, Sales, TeamChat, TicketDetail, Tickets } from './team'
import { ErrorBox, Field, ToastProvider } from './ui'

const AuthContext = createContext(null)
export const useAuth = () => useContext(AuthContext)

function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [ready, setReady] = useState(!tokens.get())
  const [offline, setOffline] = useState(false)

  const restore = useCallback(() => {
    setOffline(false)
    if (!tokens.get()) return
    api.get('/auth/me/')
      .then((me) => { setUser(me); setReady(true) })
      .catch((err) => {
        // Only the server saying no ends a session. A failed connection must not log anyone out.
        if (err.status === 401) { tokens.clear(); setReady(true) } else setOffline(true)
      })
  }, [])
  useEffect(restore, [restore])

  const login = useCallback(async (email, password) => {
    const pair = await api.post('/auth/login/', { email: email.trim().toLowerCase(), password })
    tokens.set(pair.access, pair.refresh)
    setUser(await api.get('/auth/me/'))
  }, [])
  const loginWithGoogle = useCallback(async (credential) => {
    const pair = await api.post('/auth/google/', { credential })
    tokens.set(pair.access, pair.refresh)
    setUser(await api.get('/auth/me/'))
  }, [])
  const logout = useCallback(() => {
    tokens.clear()
    setUser(null)
  }, [])
  const refreshUser = useCallback(async () => setUser(await api.get('/auth/me/')), [])
  const value = useMemo(() => ({ user, login, loginWithGoogle, logout, refreshUser }), [user, login, loginWithGoogle, logout, refreshUser])
  if (offline) return <div className="pad"><p>We cannot reach the server right now. You are still signed in.</p><button onClick={restore}>Try again</button></div>
  if (!ready) return <p className="muted pad">Loading…</p>
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

function AuthCard({ title, children, footer }) {
  return (
    <main className="auth">
      <aside className="auth-hero">
        <Link className="brand" to="/">Brightloop</Link>
        <h2>Run plans, subscriptions and recurring billing in one place.</h2>
        <ul>
          <li>Invoices created from every subscription, on time</li>
          <li>Taxes and discounts applied automatically</li>
          <li>Paid, outstanding and overdue at a glance</li>
        </ul>
      </aside>
      <div className="auth-panel">
        <div className="inner">
          <h1>{title}</h1>
          {children}
          <p className="muted foot">{footer}</p>
        </div>
      </div>
    </main>
  )
}

function GoogleButton() {
  const { loginWithGoogle } = useAuth()
  const holder = useRef(null)
  const [enabled, setEnabled] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let live = true
    api.get('/auth/config/').then((config) => {
      if (!live || !config.google_client_id) return
      setEnabled(true)
      const render = () => {
        if (!live || !holder.current) return
        window.google.accounts.id.initialize({
          client_id: config.google_client_id,
          callback: ({ credential }) => loginWithGoogle(credential).catch(setError),
        })
        window.google.accounts.id.renderButton(holder.current, { theme: 'outline', size: 'large', width: 320, text: 'continue_with' })
      }
      if (window.google) return render()
      const script = document.createElement('script')
      script.src = 'https://accounts.google.com/gsi/client'
      script.async = true
      script.onload = render
      document.head.appendChild(script)
    }).catch(() => {})
    return () => { live = false }
  }, [loginWithGoogle])

  if (!enabled) return null
  return (
    <div className="google">
      <ErrorBox error={error} />
      <div className="or">or</div>
      <div ref={holder} />
    </div>
  )
}

function useSubmit(action) {
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(err)
    }
    setBusy(false)
  }
  return { error, busy, submit }
}

const PASSWORD_HELP = 'More than eight characters, with an uppercase letter, a lowercase letter and a special character.'

function Login() {
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const { error, busy, submit } = useSubmit(() => login(email, password))
  return (
    <AuthCard title="Sign in" footer={<>New here? <Link to="/signup">Create an account</Link></>}>
      <form className="form" onSubmit={submit}>
        <ErrorBox error={error} />
        <Field label="Email"><input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Password"><input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
        <button className="primary wide" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
        <Link to="/forgot-password">Forgot your password?</Link>
        <a href={import.meta.env.VITE_ADMIN_URL || 'http://localhost:8000/admin/'}>Open the database admin</a>
      </form>
      <GoogleButton />
    </AuthCard>
  )
}

function accountType(email) {
  const value = email.trim().toLowerCase()
  if (value.endsWith('@gmail.com')) return 'user'
  if (value.endsWith('@sale.com') || value.endsWith('@support.com')) return 'team'
  return value.includes('@') && value.split('@')[1].includes('.') ? 'other' : ''
}

function Signup() {
  const { login } = useAuth()
  const [form, setForm] = useState({ email: '', password: '', first_name: '', last_name: '', company: '', phone: '', business_name: '', business_id: '' })
  const [waiting, setWaiting] = useState(false)
  const [joining, setJoining] = useState(false)
  const set = (name) => (e) => setForm((f) => ({ ...f, [name]: e.target.value }))
  const type = accountType(form.email)
  const { error, busy, submit } = useSubmit(async () => {
    const created = await api.post('/auth/signup/', form)
    if (created.pending) setWaiting(true)
    else await login(form.email, form.password)
  })
  if (waiting) {
    return (
      <AuthCard title="Waiting for approval" footer={<Link to="/login">Back to sign in</Link>}>
        <p role="status">Your account is created. The business owner needs to approve you under Staff, then you can sign in.</p>
      </AuthCard>
    )
  }
  return (
    <AuthCard title="Create your account" footer={<>Already registered? <Link to="/login">Sign in</Link></>}>
      <form className="form" onSubmit={submit}>
        <ErrorBox error={error} />
        <Field label="Email" error={error?.fields?.email} help="name@gmail.com for a business owner or customer. Team members: nameBUSINESSID@sale.com or name.BUSINESSID@support.com.">
          <input type="email" autoComplete="email" required value={form.email} onChange={set('email')} />
        </Field>
        <Field label="First name" error={error?.fields?.first_name}><input value={form.first_name} onChange={set('first_name')} /></Field>
        <Field label="Last name" error={error?.fields?.last_name}><input value={form.last_name} onChange={set('last_name')} /></Field>
        {type === 'user' && (
          <>
            <label className="check"><input type="checkbox" checked={joining} onChange={(e) => { setJoining(e.target.checked); setForm((f) => ({ ...f, business_id: '', business_name: '' })) }} /><span>I am a customer of a business on Brightloop</span></label>
            {joining
              ? <Field label="Business ID" error={error?.fields?.business_id} help="The business gives you this."><input required value={form.business_id} onChange={set('business_id')} /></Field>
              : <Field label="Your business name" error={error?.fields?.business_name} help="You get a Business ID to share with your team."><input required value={form.business_name} onChange={set('business_name')} /></Field>}
          </>
        )}
        {type === 'team' && <p className="muted">The business ID in your address joins you to that team. The owner approves you first.</p>}
        <Field label="Phone" error={error?.fields?.phone} help="Optional. With country code, for payment reminders by SMS."><input type="tel" autoComplete="tel" value={form.phone} onChange={set('phone')} /></Field>
        <Field label="Password" error={error?.fields?.password} help={PASSWORD_HELP}><input type="password" autoComplete="new-password" required value={form.password} onChange={set('password')} /></Field>
        <button className="primary wide" disabled={busy}>{busy ? 'Creating…' : 'Create account'}</button>
      </form>
      <GoogleButton />
    </AuthCard>
  )
}

function ForgotPassword() {
  const [step, setStep] = useState('email')
  const [form, setForm] = useState({ email: '', otp: '', password: '' })
  const [notice, setNotice] = useState('')
  const [devCode, setDevCode] = useState('')
  const set = (name) => (e) => setForm((f) => ({ ...f, [name]: e.target.value }))
  const ask = useSubmit(async () => {
    const result = await api.post('/auth/forgot-password/', { email: form.email })
    setNotice(result.message)
    setDevCode(result.dev_otp || '')
    setStep('code')
  })
  const reset = useSubmit(async () => {
    setNotice((await api.post('/auth/reset-password/', form)).message)
    setStep('done')
  })
  return (
    <AuthCard title="Forgot your password?" footer={<Link to="/login">Back to sign in</Link>}>
      {step === 'email' && (
        <form className="form" onSubmit={ask.submit}>
          <p className="muted">Enter the email you sign in with. We send a 6-digit code to your recovery email.</p>
          <ErrorBox error={ask.error} />
          <Field label="Sign-in email"><input type="email" autoComplete="email" required value={form.email} onChange={set('email')} /></Field>
          <button className="primary wide" disabled={ask.busy}>{ask.busy ? 'Sending…' : 'Send my code'}</button>
        </form>
      )}
      {step === 'code' && (
        <form className="form" onSubmit={reset.submit}>
          <p role="status">{notice}</p>
          {devCode && <div className="banner"><span><b>Email is not set up yet.</b> Your code for this test: <b>{devCode}</b></span></div>}
          <ErrorBox error={reset.error} />
          <Field label="6-digit code" error={reset.error?.fields?.otp}><input inputMode="numeric" autoComplete="one-time-code" maxLength="6" required value={form.otp} onChange={set('otp')} /></Field>
          <Field label="New password" error={reset.error?.fields?.password} help={PASSWORD_HELP}><input type="password" autoComplete="new-password" required value={form.password} onChange={set('password')} /></Field>
          <button className="primary wide" disabled={reset.busy}>Save new password</button>
          <button type="button" className="link" onClick={() => setStep('email')}>Send a new code</button>
        </form>
      )}
      {step === 'done' && <p role="status">{notice}</p>}
    </AuthCard>
  )
}

const ICONS = {
  '/': 'M3 13h7V3H3zM14 21h7V11h-7zM14 7h7V3h-7zM3 21h7v-4H3z',
  '/subscriptions': 'M17 2l4 4-4 4M3 11V9a3 3 0 0 1 3-3h15M7 22l-4-4 4-4M21 13v2a3 3 0 0 1-3 3H3',
  '/invoices': 'M6 2h9l5 5v15H6zM14 2v6h6M9 13h8M9 17h8',
  '/payments': 'M2 6h20v13H2zM2 10h20M6 15h4',
  '/revenue': 'M3 17l6-6 4 4 8-8M15 7h6v6',
  '/customers': 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8',
  '/products': 'M21 8l-9-5-9 5v8l9 5 9-5zM3 8l9 5 9-5M12 13v8',
  '/plans': 'M4 6h16M4 12h16M4 18h10',
  '/browse-plans': 'M21 8l-9-5-9 5v8l9 5 9-5zM3 8l9 5 9-5M12 13v8',
  '/templates': 'M4 3h16v18H4zM8 8h8M8 12h8M8 16h5',
  '/taxes': 'M19 5L5 19M7 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4M17 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4',
  '/discounts': 'M3 12V3h9l9 9-9 9zM8 8h.01',
  '/payment-terms': 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20M12 6v6l4 2',
  '/staff': 'M12 2l8 4v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6z',
  '/tickets': 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z',
  '/team-chat': 'M17 8h2a2 2 0 0 1 2 2v11l-4-4h-6a2 2 0 0 1-2-2v-1M15 3H5a2 2 0 0 0-2 2v10l4-4h8a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2',
  '/sales': 'M12 2v20M17 6H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6',
  '/sales-targets': 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8',
  '/promo-codes': 'M20 12v8H4v-8M2 7h20v5H2zM12 22V7M12 7H8a2.5 2.5 0 1 1 2-4zM12 7h4a2.5 2.5 0 1 0-2-4z',
  '/payment-approvals': 'M22 11v1a10 10 0 1 1-6-9.1M22 4L12 14l-3-3',
  '/import': 'M21 15v6H3v-6M7 10l5 5 5-5M12 15V3',
  '/platform': 'M12 2l10 6-10 6L2 8zM2 16l10 6 10-6',
  '/platform/users': 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8',
  '/admin-chat': 'M12 2l8 4v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6zM8 11h8',
  '/my-plan': 'M2 6h20v13H2zM7 12l3 3 6-6',
}

function NavIcon({ to }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={ICONS[to]} />
    </svg>
  )
}

const BILLING = [['/', 'Dashboard'], ['/subscriptions', 'Subscriptions'], ['/invoices', 'Invoices'], ['/payments', 'Payments'], ['/revenue', 'Revenue'], ['/customers', 'Customers']]
const CATALOG = [['/products', 'Products'], ['/plans', 'Plans'], ['/templates', 'Quotation templates'], ['/taxes', 'Taxes'], ['/discounts', 'Discounts'], ['/payment-terms', 'Payment terms']]
const CONSOLE = [['/platform', 'Brightloop overview'], ['/platform/users', 'All users']]
const CHATS = [['/team-chat', 'Team chat'], ['/admin-chat', 'Admin chat']]
const SETUP = [...CATALOG, ['/promo-codes', 'Promo codes'], ['/sales-targets', 'Sales targets'], ['/import', 'Import subscribers'], ['/staff', 'Staff']]
const CARE = [['/tickets', 'Tickets'], ...CHATS, ['/customers', 'Customers'], ['/subscriptions', 'Subscriptions'], ['/invoices', 'Invoices']]
const SELLING = [['/sales', 'My sales'], ['/subscriptions', 'My subscriptions'], ['/invoices', 'Their invoices'], ['/customers', 'Customers'], ...CHATS]

function navFor(user) {
  const platform = user.business?.is_platform
  const brightloop = platform ? [['Brightloop', CONSOLE]] : []
  if (user.role === 'customer') return [['My account', [['/subscriptions', 'My subscriptions'], ['/invoices', 'My invoices'], ['/browse-plans', 'Browse plans'], ['/tickets', 'Help']]]]
  if (user.department === 'support') return [...brightloop, ['Customer care', CARE], ['Reference', CATALOG]]
  if (user.department === 'sales') return [...brightloop, ['Sales', SELLING], ['Reference', CATALOG]]
  if (user.role === 'staff') return [...brightloop, ['Billing', BILLING], ['People', [['/tickets', 'Tickets'], ...CHATS, ['/sales', 'Sales team']]], ['Setup', [['/import', 'Import subscribers']]], ['Reference', CATALOG]]
  return [
    ...brightloop,
    ['Billing', [...BILLING, ['/payment-approvals', 'Payment approvals']]],
    ['People', [['/tickets', 'Tickets'], ...CHATS, ['/sales', 'Sales team']]],
    ['Setup', platform ? SETUP : [...SETUP, ['/my-plan', 'My Brightloop plan']]],
  ]
}

function BusinessId({ business }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(business.code)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch { /* the code is on screen to copy by hand */ }
  }
  return (
    <div className="biz-id">
      <small>{business.name}</small>
      <button className="link" title="Copy your Business ID" onClick={copy}>ID: <b>{business.code}</b> {copied ? 'Copied' : 'Copy'}</button>
      {!business.is_platform && <Link to={`/shop/${business.code}`}>Open our site</Link>}
    </div>
  )
}

function Shell() {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const { pathname } = useLocation()
  if (!user) return pathname === '/' ? <Landing /> : <Navigate to="/login" replace />
  if (!user.recovery_email) return <RecoveryGate />
  return (
    <div className="shell">
      <aside className={`side no-print ${open ? 'open' : ''}`}>
        <div className="side-top">
          <p className="brand">Brightloop</p>
          <button className="menu-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>Menu</button>
        </div>
        <nav onClick={() => setOpen(false)}>
          {navFor(user).map(([group, links]) => (
            <div key={group}>
              <h3>{group}</h3>
              {links.map(([to, text]) => <NavLink key={to} to={to} end={to === '/'}><NavIcon to={to} />{text}</NavLink>)}
            </div>
          ))}
        </nav>
        {user.role !== 'customer' && user.business && <BusinessId business={user.business} />}
        <div className="who"><span className="avatar" aria-hidden="true">{user.name[0].toUpperCase()}</span><b>{user.name}</b><small>{user.role_label}</small><span className="who-links"><Link to="/profile">Profile</Link><button className="link" onClick={logout}>Sign out</button></span></div>
      </aside>
      <main className="content"><div className="page-in" key={pathname}><Outlet /></div></main>
    </div>
  )
}

function Require({ roles, children }) {
  const { user } = useAuth()
  return roles.includes(user?.role) ? children : <Navigate to="/" replace />
}

function Home() {
  const { user } = useAuth()
  if (user.role === 'customer') return <Navigate to="/subscriptions" replace />
  if (user.department === 'sales') return <Navigate to="/sales" replace />
  if (user.department === 'support') return <Navigate to="/tickets" replace />
  if (user.business?.is_platform) return <Navigate to="/platform" replace />
  return <Dashboard />
}

const TEAM = ['admin', 'staff']
const team = (element) => <Require roles={TEAM}>{element}</Require>
const admin = (element) => <Require roles={['admin']}>{element}</Require>

function PlatformOnly({ children }) {
  const { user } = useAuth()
  return user.business?.is_platform ? children : <Navigate to="/" replace />
}

function BackOffice({ children }) {
  const { user } = useAuth()
  return user.role === 'customer' || user.department ? <Navigate to="/" replace /> : children
}

// A signed-in person who lands here, such as by pressing Back, goes to the app and is not shown a sign-in form.
function PublicOnly({ children }) {
  const { user } = useAuth()
  const [params] = useSearchParams()
  if (user) return <Navigate to={params.get('next') === 'plans' && user.role === 'customer' ? '/browse-plans' : '/'} replace />
  return children
}

function Welcome() {
  const { user } = useAuth()
  return <Landing user={user} />
}

function NotFound() {
  return <section><h1>Page not found</h1><p><Link to="/">Go to the start page</Link></p></section>
}

function App() {
  return (
    <Routes>
      <Route path="/welcome" element={<Welcome />} />
      <Route path="/login" element={<PublicOnly><Login /></PublicOnly>} />
      <Route path="/signup" element={<PublicOnly><Signup /></PublicOnly>} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/shop/:code" element={<Shop />} />
      <Route element={<Shell />}>
        <Route index element={<Home />} />
        <Route path="profile" element={<Profile />} />
        <Route path="browse-plans" element={<Require roles={['customer']}><BrowsePlans /></Require>} />
        <Route path="subscriptions" element={<Subscriptions />} />
        <Route path="subscriptions/new" element={team(<SubscriptionForm />)} />
        <Route path="subscriptions/:id" element={<SubscriptionDetail />} />
        <Route path="subscriptions/:id/edit" element={team(<SubscriptionForm />)} />
        <Route path="invoices" element={<Invoices />} />
        <Route path="invoices/:id" element={<InvoiceDetail />} />
        <Route path="payments" element={<BackOffice><Payments /></BackOffice>} />
        <Route path="revenue" element={<BackOffice><Revenue /></BackOffice>} />
        <Route path="customers" element={team(<CrudPage key="customers" config={configs.customers} />)} />
        <Route path="customers/:id" element={team(<CustomerDetail />)} />
        <Route path="tickets" element={<Tickets />} />
        <Route path="tickets/:id" element={<TicketDetail />} />
        <Route path="team-chat" element={team(<TeamChat />)} />
        <Route path="sales" element={team(<Sales />)} />
        <Route path="import" element={<BackOffice><ImportSubscribers /></BackOffice>} />
        <Route path="payment-approvals" element={admin(<PaymentApprovals />)} />
        <Route path="platform" element={team(<PlatformOnly><PlatformOverview /></PlatformOnly>)} />
        <Route path="platform/users" element={team(<PlatformOnly><PlatformUsers /></PlatformOnly>)} />
        <Route path="admin-chat" element={team(<AdminChat />)} />
        <Route path="my-plan" element={admin(<MyPlan />)} />
        <Route path="promo-codes" element={admin(<CrudPage key="promo" config={configs.promoCodes} />)} />
        <Route path="sales-targets" element={admin(<CrudPage key="targets" config={configs.salesTargets} />)} />
        <Route path="products" element={team(<CrudPage key="products" config={configs.products} />)} />
        <Route path="plans" element={team(<CrudPage key="plans" config={configs.plans} />)} />
        <Route path="templates" element={team(<CrudPage key="templates" config={configs.templates} />)} />
        <Route path="taxes" element={team(<CrudPage key="taxes" config={configs.taxes} />)} />
        <Route path="discounts" element={team(<CrudPage key="discounts" config={configs.discounts} />)} />
        <Route path="payment-terms" element={team(<CrudPage key="terms" config={configs.terms} />)} />
        <Route path="staff" element={<Require roles={['admin']}><CrudPage key="staff" config={configs.staff} /></Require>} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <ToastProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </ToastProvider>
    </BrowserRouter>
  </StrictMode>,
)
