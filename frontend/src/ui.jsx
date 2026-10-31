import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { api, query } from './api'

const CURRENCY = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' })
export const money = (value) => CURRENCY.format(Number(value || 0))
export const label = (text) => String(text || '').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())

const TONES = {
  active: 'good', paid: 'good', confirmed: 'info', quotation: 'info', draft: 'muted',
  paused: 'warn', closed: 'muted', cancelled: 'muted', overdue: 'bad',
}
export function Badge({ value }) {
  return <span className={`badge ${TONES[value] || 'muted'}`}>{label(value)}</span>
}

const ToastContext = createContext(() => {})
export const useToast = () => useContext(ToastContext)
export function ToastProvider({ children }) {
  const [toast, setToast] = useState(null)
  const timer = useRef()
  const show = useCallback((message, tone = 'good') => {
    setToast({ message, tone })
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setToast(null), 4500)
  }, [])
  return (
    <ToastContext.Provider value={show}>
      {children}
      {toast && <div role="status" className={`toast ${toast.tone}`}>{toast.message}</div>}
    </ToastContext.Provider>
  )
}

export function ErrorBox({ error, onRetry }) {
  if (!error) return null
  return (
    <div className="alert" role="alert">
      {error.message}
      {onRetry && <button className="link" onClick={onRetry}>Retry</button>}
    </div>
  )
}

export function Modal({ title, onClose, children }) {
  useEffect(() => {
    const onKey = (event) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <header><h2>{title}</h2><button className="link" onClick={onClose} aria-label="Close">Close</button></header>
        {children}
      </div>
    </div>
  )
}

export function Field({ label: text, error, help, children }) {
  const message = Array.isArray(error) ? error.join(' ') : error
  return (
    <label className={`field ${message ? 'invalid' : ''}`}>
      <span>{text}</span>
      {children}
      {help && !message && <small>{help}</small>}
      {message && <small className="error">{message}</small>}
    </label>
  )
}

export function useLoad(path) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const latest = useRef(0)
  const reload = useCallback(async () => {
    const id = ++latest.current
    setState((s) => ({ ...s, loading: true, error: null }))
    try {
      const data = await api.get(path)
      if (id === latest.current) setState({ data, error: null, loading: false })
    } catch (error) {
      if (id === latest.current) setState({ data: null, error, loading: false })
    }
  }, [path])
  useEffect(() => { reload() }, [reload])
  return { ...state, reload }
}

export function useOptions(path) {
  const { data } = useLoad(path ? `${path}?page_size=200` : '/health/')
  return path ? data?.results || [] : []
}

export function Pager({ page, count, pageSize = 25, onPage }) {
  const pages = Math.max(Math.ceil(count / pageSize), 1)
  return (
    <div className="pager">
      <span>{count.toLocaleString('en-IN')} record{count === 1 ? '' : 's'}</span>
      <button disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
      <span>Page {page} of {pages}</span>
      <button disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</button>
    </div>
  )
}

export function useDebounced(value, delay = 300) {
  const [current, setCurrent] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setCurrent(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return current
}

export function DataTable({ columns, rows, loading, empty, rowKey = 'id', onRow }) {
  if (loading && !rows) return <p className="muted pad">Loading…</p>
  if (!rows?.length) return <p className="muted pad">{empty || 'Nothing here yet.'}</p>
  return (
    <div className="table-wrap">
      <table className={loading ? 'dim' : ''}>
        <thead><tr>{columns.map((c) => <th key={c.key} className={c.right ? 'right' : ''}>{c.label}</th>)}</tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row[rowKey]} className={onRow ? 'clickable' : ''} onClick={onRow ? () => onRow(row) : undefined}>
              {columns.map((c) => (
                <td key={c.key} className={c.right ? 'right' : ''}>{c.render ? c.render(row) : row[c.key]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Search-as-you-type picker, because customers and subscriptions can run to thousands. */
export function SearchPicker({ path, display, value, onChange, multi = false, placeholder = 'Type to search' }) {
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const [results, setResults] = useState([])
  const [known, setKnown] = useState({})
  const search = useDebounced(text)
  const picked = multi ? value || [] : value ? [value] : []

  useEffect(() => {
    if (!open) return undefined
    let live = true
    api.get(`${path}${query({ search, page_size: 10 })}`).then((data) => live && setResults(data.results)).catch(() => {})
    return () => { live = false }
  }, [open, search, path])

  const nameOf = (id) => (known[id] ? display(known[id]) : `#${id}`)
  const choose = (row) => {
    setKnown((k) => ({ ...k, [row.id]: row }))
    setText('')
    setOpen(false)
    if (!multi) onChange(row.id)
    else if (!picked.includes(row.id)) onChange([...picked, row.id])
  }
  const remove = (id) => onChange(multi ? picked.filter((p) => p !== id) : null)

  return (
    <div className="picker">
      {picked.map((id) => (
        <span className="chip" key={id}>
          {nameOf(id)} <button type="button" onClick={() => remove(id)} aria-label={`Remove ${nameOf(id)}`}>×</button>
        </span>
      ))}
      {(multi || !picked.length) && (
        <input
          value={text}
          placeholder={placeholder}
          onChange={(event) => setText(event.target.value)}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
        />
      )}
      {open && results.length > 0 && (
        <ul className="menu">
          {results.map((row) => <li key={row.id}><button type="button" onMouseDown={() => choose(row)}>{display(row)}</button></li>)}
        </ul>
      )}
    </div>
  )
}

/** Product lines shared by the subscription form and quotation templates. */
export function LineEditor({ value, onChange, products, showPrice = false, error }) {
  const rows = value || []
  const update = (index, patch) => onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)))
  return (
    <div className="lines">
      {rows.map((row, index) => {
        const product = products.find((p) => p.id === Number(row.product))
        const variant = product?.variants.find((v) => v.id === Number(row.variant))
        const price = product ? Number(product.sales_price) + Number(variant?.extra_price || 0) : 0
        return (
          <div className="line-row" key={index}>
            <select aria-label="Product" value={row.product || ''} onChange={(e) => update(index, { product: Number(e.target.value), variant: null })}>
              <option value="">Choose product</option>
              {products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <select aria-label="Variant" value={row.variant || ''} disabled={!product?.variants.length} onChange={(e) => update(index, { variant: e.target.value ? Number(e.target.value) : null })}>
              <option value="">No variant</option>
              {product?.variants.map((v) => <option key={v.id} value={v.id}>{v.value} (+{money(v.extra_price)})</option>)}
            </select>
            <input aria-label="Quantity" type="number" min="1" value={row.quantity} onChange={(e) => update(index, { quantity: Number(e.target.value) })} />
            {showPrice && <input aria-label="Unit price" type="number" min="0" step="0.01" placeholder={price.toFixed(2)} value={row.unit_price ?? ''} onChange={(e) => update(index, { unit_price: e.target.value === '' ? null : e.target.value })} />}
            {showPrice && <span className="right amount">{money((row.unit_price === null || row.unit_price === undefined || row.unit_price === '' ? price : Number(row.unit_price)) * (row.quantity || 0))}</span>}
            <button type="button" className="link danger" onClick={() => onChange(rows.filter((_, i) => i !== index))}>Remove</button>
          </div>
        )
      })}
      <button type="button" onClick={() => onChange([...rows, { product: '', variant: null, quantity: 1 }])}>Add line</button>
      {error && <small className="error">{typeof error === 'string' ? error : Array.isArray(error) && typeof error[0] === 'string' ? error.join(' ') : 'Check each line.'}</small>}
    </div>
  )
}
