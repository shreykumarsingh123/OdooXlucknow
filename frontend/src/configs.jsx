import { Badge, label, money } from './ui'

const active = { key: 'is_active', label: 'Status', render: (r) => <Badge value={r.is_active ? 'active' : 'closed'} /> }
const activeField = { name: 'is_active', label: 'Active', type: 'checkbox', default: true }
const today = new Date().toISOString().slice(0, 10)

const personColumns = [
  { key: 'name', label: 'Name' },
  { key: 'email', label: 'Email' },
  { key: 'company', label: 'Company' },
  { key: 'phone', label: 'Phone' },
  { key: 'is_active', label: 'Status', render: (r) => <Badge value={r.is_active ? 'active' : 'closed'} /> },
]
const personFields = [
  { name: 'email', label: 'Email', type: 'email', required: true },
  { name: 'first_name', label: 'First name' },
  { name: 'last_name', label: 'Last name' },
  { name: 'company', label: 'Company' },
  { name: 'phone', label: 'Phone' },
  { name: 'address', label: 'Address', type: 'textarea' },
  activeField,
]

export const customers = {
  title: 'Customers', singular: 'Customer', path: '/customers/', columns: personColumns, fields: personFields, deletable: false,
  canWrite: (user) => user.role === 'admin' || user.role === 'staff',
  note: 'New customers receive an email link to choose their password.',
}

export const staff = {
  title: 'Staff', singular: 'Staff member', path: '/staff/', columns: personColumns, fields: personFields, deletable: false,
  intro: 'Only the admin can add staff.',
  note: 'New staff receive an email link to choose their password.',
}

export const taxes = {
  title: 'Taxes', singular: 'Tax', path: '/taxes/',
  intro: 'Rules that calculate tax automatically. Attach them to products and plans.',
  columns: [
    { key: 'name', label: 'Name' },
    { key: 'computation', label: 'Calculation', render: (r) => (r.computation === 'percent' ? 'Percentage' : 'Fixed per unit') },
    { key: 'rate', label: 'Rate', right: true, render: (r) => (r.computation === 'percent' ? `${Number(r.rate)}%` : money(r.rate)) },
    active,
  ],
  fields: [
    { name: 'name', label: 'Name', required: true },
    { name: 'computation', label: 'Calculation', type: 'select', default: 'percent', required: true, options: [{ value: 'percent', label: 'Percentage' }, { value: 'fixed', label: 'Fixed per unit' }] },
    { name: 'rate', label: 'Rate', type: 'number', required: true },
    activeField,
  ],
}

export const terms = {
  title: 'Payment terms', singular: 'Payment term', path: '/payment-terms/',
  columns: [{ key: 'name', label: 'Name' }, { key: 'due_days', label: 'Days until due', right: true }, active],
  fields: [
    { name: 'name', label: 'Name', required: true },
    { name: 'due_days', label: 'Days until due', type: 'number', default: 0, required: true },
    activeField,
  ],
}

export const products = {
  title: 'Products', singular: 'Product', path: '/products/',
  columns: [
    { key: 'name', label: 'Name' },
    { key: 'type', label: 'Type', render: (r) => label(r.type === 'addon' ? 'Add-on' : r.type) },
    { key: 'sales_price', label: 'Sales price', right: true, render: (r) => money(r.sales_price) },
    { key: 'cost_price', label: 'Cost price', right: true, render: (r) => money(r.cost_price) },
    { key: 'variants', label: 'Variants', render: (r) => r.variants.map((v) => `${v.value} (+${Number(v.extra_price)})`).join(', ') || '—' },
    active,
  ],
  fields: [
    { name: 'name', label: 'Name', required: true },
    { name: 'type', label: 'Type', type: 'select', default: 'software', required: true, options: [{ value: 'software', label: 'Software' }, { value: 'addon', label: 'Add-on (customers can switch it on and off)' }, { value: 'service', label: 'Service' }] },
    { name: 'sales_price', label: 'Sales price', type: 'number', required: true },
    { name: 'cost_price', label: 'Cost price', type: 'number', default: 0 },
    { name: 'taxes', label: 'Taxes', type: 'multi', source: '/taxes/' },
    { name: 'variants', label: 'Variants', type: 'variants' },
    { name: 'notes', label: 'Notes', type: 'textarea' },
    activeField,
  ],
}

const yesNo = (value) => (value ? 'Yes' : 'No')

export const plans = {
  title: 'Plans', singular: 'Plan', path: '/plans/',
  columns: [
    { key: 'name', label: 'Name' },
    { key: 'price', label: 'Price', right: true, render: (r) => money(r.price) },
    { key: 'billing_period', label: 'Bills', render: (r) => label(r.billing_period) },
    { key: 'min_quantity', label: 'Min qty', right: true },
    { key: 'dates', label: 'Available', render: (r) => `${r.start_date} to ${r.end_date || 'open'}` },
    { key: 'opts', label: 'Auto-close / Close / Pause / Renew', render: (r) => [r.auto_close, r.closable, r.pausable, r.renewable].map(yesNo).join(' / ') },
    active,
  ],
  fields: [
    { name: 'name', label: 'Name', required: true },
    { name: 'price', label: 'Price', type: 'number', default: 0, required: true },
    { name: 'billing_period', label: 'Bills every', type: 'select', default: 'monthly', required: true, options: ['daily', 'weekly', 'monthly', 'yearly'].map((p) => ({ value: p, label: label(p) })) },
    { name: 'min_quantity', label: 'Minimum quantity', type: 'number', default: 1, required: true },
    { name: 'start_date', label: 'Available from', type: 'date', default: today, required: true },
    { name: 'end_date', label: 'Available until', type: 'date', help: 'Leave empty for no end date.' },
    { name: 'taxes', label: 'Taxes on the plan price', type: 'multi', source: '/taxes/' },
    { name: 'auto_close', label: 'Close on its own when it ends', type: 'checkbox' },
    { name: 'closable', label: 'Can be closed early', type: 'checkbox', default: true },
    { name: 'pausable', label: 'Can be paused', type: 'checkbox' },
    { name: 'renewable', label: 'Can be renewed', type: 'checkbox', default: true },
    activeField,
  ],
}

export const templates = {
  title: 'Quotation templates', singular: 'Template', path: '/templates/',
  intro: 'Ready-made offers. Start a quotation from one on the Subscriptions page.',
  columns: [
    { key: 'name', label: 'Name' },
    { key: 'validity_days', label: 'Valid for (days)', right: true },
    { key: 'lines', label: 'Lines', right: true, render: (r) => r.lines.length },
    active,
  ],
  fields: [
    { name: 'name', label: 'Name', required: true },
    { name: 'plan', label: 'Plan', type: 'select', source: '/plans/', required: true },
    { name: 'validity_days', label: 'Valid for (days)', type: 'number', default: 30, required: true },
    { name: 'lines', label: 'Product lines', type: 'lines', source: '/products/' },
    activeField,
  ],
}

export const discounts = {
  title: 'Discounts', singular: 'Discount', path: '/discounts/',
  intro: 'Live discounts appear on the next invoice automatically, and stop when they expire or run out.',
  columns: [
    { key: 'name', label: 'Name' },
    { key: 'value', label: 'Value', right: true, render: (r) => (r.kind === 'percent' ? `${Number(r.value)}%` : money(r.value)) },
    { key: 'scope', label: 'Applies to', render: (r) => (r.scope === 'products' ? 'Specific products' : 'Whole subscriptions') },
    { key: 'dates', label: 'Dates', render: (r) => `${r.start_date} to ${r.end_date || 'open'}` },
    { key: 'used', label: 'Used', right: true, render: (r) => `${r.times_used}${r.usage_limit ? ` of ${r.usage_limit}` : ''}` },
    active,
  ],
  fields: [
    { name: 'name', label: 'Name', required: true },
    { name: 'kind', label: 'Type', type: 'select', default: 'percent', required: true, options: [{ value: 'percent', label: 'Percentage' }, { value: 'fixed', label: 'Fixed amount' }] },
    { name: 'value', label: 'Value', type: 'number', required: true },
    { name: 'scope', label: 'Applies to', type: 'select', default: 'products', required: true, options: [{ value: 'products', label: 'Specific products' }, { value: 'subscriptions', label: 'Whole subscriptions' }] },
    { name: 'products', label: 'Products', type: 'multi', source: '/products/', when: (v) => v.scope === 'products' },
    { name: 'subscriptions', label: 'Subscriptions', type: 'search-multi', path: '/subscriptions/', display: (s) => `${s.number} · ${s.customer_name}`, when: (v) => v.scope === 'subscriptions' },
    { name: 'min_purchase', label: 'Minimum purchase', type: 'number', default: 0 },
    { name: 'min_quantity', label: 'Minimum quantity', type: 'number', default: 0 },
    { name: 'start_date', label: 'Start date', type: 'date', default: today, required: true },
    { name: 'end_date', label: 'End date', type: 'date' },
    { name: 'usage_limit', label: 'Usage limit', type: 'number', help: 'Leave empty for no limit.' },
    activeField,
  ],
}
