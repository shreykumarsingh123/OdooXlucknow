import { useState } from 'react'
import { api, query } from './api'
import { useAuth } from './main'
import { DataTable, ErrorBox, Field, LineEditor, Modal, Pager, SearchPicker, useDebounced, useLoad, useOptions, useToast } from './ui'

function FormField({ field, value, onChange, error, values, sources }) {
  if (field.when && !field.when(values)) return null
  const common = { value: value ?? '', onChange: (e) => onChange(e.target.value), required: field.required }
  let input
  if (field.type === 'checkbox') {
    return (
      <label className="check">
        <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        <span>{field.label}{field.help && <small>{field.help}</small>}</span>
      </label>
    )
  }
  if (field.type === 'select-optional') {
    input = <select {...common}>{field.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select>
  } else if (field.type === 'select') {
    input = (
      <select {...common}>
        <option value="">Choose</option>
        {(field.options || sources[field.name] || []).map((o) => <option key={o.value ?? o.id} value={o.value ?? o.id}>{o.label ?? o.name}</option>)}
      </select>
    )
  } else if (field.type === 'multi') {
    const selected = (value || []).map(Number)
    input = (
      <div className="checks">
        {(sources[field.name] || []).map((o) => (
          <label className="check" key={o.id}>
            <input type="checkbox" checked={selected.includes(o.id)} onChange={(e) => onChange(e.target.checked ? [...selected, o.id] : selected.filter((id) => id !== o.id))} />
            <span>{o.name}</span>
          </label>
        ))}
      </div>
    )
  } else if (field.type === 'search-multi') {
    input = <SearchPicker multi path={field.path} display={field.display} value={value} onChange={onChange} />
  } else if (field.type === 'lines') {
    return <Field label={field.label} error={typeof error === 'string' ? error : null}><LineEditor value={value} onChange={onChange} products={sources[field.name] || []} error={error} /></Field>
  } else if (field.type === 'variants') {
    const rows = value || []
    const set = (i, patch) => onChange(rows.map((r, n) => (n === i ? { ...r, ...patch } : r)))
    input = (
      <div className="lines">
        {rows.map((row, i) => (
          <div className="line-row three" key={i}>
            <input aria-label="Attribute" placeholder="Attribute, such as Brand" value={row.attribute} onChange={(e) => set(i, { attribute: e.target.value })} />
            <input aria-label="Value" placeholder="Value, such as Odoo" value={row.value} onChange={(e) => set(i, { value: e.target.value })} />
            <input aria-label="Extra price" type="number" min="0" step="0.01" placeholder="Extra price" value={row.extra_price} onChange={(e) => set(i, { extra_price: e.target.value })} />
            <button type="button" className="link danger" onClick={() => onChange(rows.filter((_, n) => n !== i))}>Remove</button>
          </div>
        ))}
        <button type="button" onClick={() => onChange([...rows, { attribute: 'Brand', value: '', extra_price: '0' }])}>Add variant</button>
      </div>
    )
  } else if (field.type === 'textarea') {
    input = <textarea rows="3" {...common} />
  } else {
    input = <input type={field.type || 'text'} step={field.type === 'number' ? 'any' : undefined} min={field.type === 'number' ? 0 : undefined} {...common} />
  }
  return <Field label={field.label} error={error} help={field.help}>{input}</Field>
}

function useSources(fields) {
  const sources = {}
  // The field list is fixed for each page, so hook order stays stable.
  for (const field of fields) {
    // eslint-disable-next-line react-hooks/rules-of-hooks
    sources[field.name] = useOptions(field.source)
  }
  return sources
}

function RecordForm({ config, record, onClose, onSaved }) {
  const blank = Object.fromEntries(config.fields.map((f) => [f.name, f.default ?? (['multi', 'lines', 'variants', 'search-multi'].includes(f.type) ? [] : f.type === 'checkbox' ? false : '')]))
  const [values, setValues] = useState(record ? { ...blank, ...record } : blank)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const sources = useSources(config.fields)
  const toast = useToast()

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    const body = {}
    for (const field of config.fields) {
      const value = values[field.name]
      body[field.name] = value === '' && !['text', 'textarea', 'select-optional', undefined].includes(field.type) ? null : value
    }
    try {
      if (record) await api.put(`${config.path}${record.id}/`, body)
      else await api.post(config.path, body)
      toast(`${config.singular} saved.`)
      onSaved()
    } catch (err) {
      setError(err)
      setBusy(false)
    }
  }
  return (
    <Modal title={`${record ? 'Edit' : 'New'} ${config.singular.toLowerCase()}`} onClose={onClose}>
      <form onSubmit={submit} className="form">
        <ErrorBox error={error} />
        {config.fields.map((field) => (
          <FormField
            key={field.name}
            field={field}
            values={values}
            sources={sources}
            value={values[field.name]}
            error={error?.fields?.[field.name]}
            onChange={(value) => setValues((v) => ({ ...v, [field.name]: value }))}
          />
        ))}
        {config.note && <p className="muted">{config.note}</p>}
        <footer><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button></footer>
      </form>
    </Modal>
  )
}

export function CrudPage({ config }) {
  const { user } = useAuth()
  const canWrite = config.canWrite ? config.canWrite(user) : user.role === 'admin'
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState(null)
  const debounced = useDebounced(search)
  const { data, loading, error, reload } = useLoad(`${config.path}${query({ ...config.filter, page, search: debounced })}`)
  const toast = useToast()

  const remove = async (row) => {
    if (!window.confirm(`Delete ${row.name || row.salesperson_name}? This cannot be undone.`)) return
    try {
      await api.del(`${config.path}${row.id}/`)
      toast(`${config.singular} deleted.`)
      reload()
    } catch (err) {
      toast(err.message, 'bad')
    }
  }
  const columns = [...config.columns]
  if (canWrite) {
    columns.push({
      key: '_actions',
      label: '',
      right: true,
      render: (row) => (
        <>
          <button className="link" onClick={() => setEditing(row)}>Edit</button>
          {config.deletable !== false && <button className="link danger" onClick={() => remove(row)}>Delete</button>}
        </>
      ),
    })
  }
  return (
    <section>
      <header className="page-head">
        <div><h1>{config.title}</h1>{config.intro && <p className="muted">{config.intro}</p>}</div>
        {canWrite && <button className="primary" onClick={() => setEditing({})}>New {config.singular.toLowerCase()}</button>}
      </header>
      <div className="toolbar">
        <input type="search" aria-label="Search" placeholder="Search" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }} />
      </div>
      <ErrorBox error={error} onRetry={reload} />
      <div className="card flush">
        <DataTable columns={columns} rows={data?.results} loading={loading} empty={search ? 'No matches.' : `No ${config.title.toLowerCase()} yet.`} />
        {data && <Pager page={page} count={data.count} onPage={setPage} />}
      </div>
      {editing && (
        <RecordForm
          config={config}
          record={editing.id ? editing : null}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); reload() }}
        />
      )}
    </section>
  )
}
