---
name: odoo-development
description: Guidance for building custom Odoo modules covering module structure, ORM models, views, security, workflows, reports and the development loop. Use only when the problem requires building on or integrating with Odoo, or when working with __manifest__.py, odoo-bin or XML-RPC.
---

# Odoo development

Use this only if `docs/PROBLEM.md` requires Odoo. It replaces the Django and React stack. Odoo runs on PostgreSQL only, so setup differs from the default stack: see `docs/SETUP.md`.

First confirm the target Odoo version, and check that version's developer documentation, because details such as view syntax change between releases.

## Prefer configuration, then extension

Reuse built-in apps such as Inventory, Sales, Purchase, HR or Maintenance if they fit the problem. Inherit their models rather than rebuilding them.

## Module structure

```
addons/my_module/
  __init__.py
  __manifest__.py       # name, version, depends, data files, application flag
  models/
  views/                # form, list, search, actions, menus
  security/
    security.xml        # groups and record rules
    ir.model.access.csv
  data/                 # sequences, cron jobs, defaults
  demo/                 # demo records
  report/               # QWeb PDF reports (needs wkhtmltopdf)
  tests/
```

List data files in `__manifest__.py` in load order, with security first.

## Models

```python
class Request(models.Model):
    _name = "my_module.request"
    _description = "Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]  # chatter and audit trail

    name = fields.Char(required=True, tracking=True)
    state = fields.Selection(
        [("draft", "Draft"), ("approved", "Approved")],
        default="draft", required=True, tracking=True,
    )

    @api.constrains("name")
    def _check_name(self):
        ...  # raise ValidationError

    def action_approve(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError("Only draft requests can be approved.")
            rec.state = "approved"
```

- Use `@api.depends` for computed fields, and add `store=True` if they need to be searched or grouped.
- Put workflow transitions in `action_*` methods, and restrict their buttons with `groups=`. Also check rights in the method if the rule is sensitive, since methods can be called over RPC.
- Avoid raw SQL.

## Security

Without an access rule, a model is not available to normal users. Every model needs a row in `ir.model.access.csv`. Use record rules for row-level access, such as "own records only".

## Views

- Form view with a header `statusbar` for `state`, and buttons per transition.
- List and search views with filters and group-by.
- Kanban, pivot and graph views give dashboards at low cost.
- Menus and window actions so that the module is reachable.

## Development loop

```powershell
python odoo-bin -d devdb -i my_module --dev=all
```

To upgrade after changing a model or XML:

```powershell
python odoo-bin -d devdb -u my_module --dev=all
```

Enable developer mode in the web UI to inspect fields and views. Restart after Python changes unless `--dev` reloading covers them.

## Check before finishing

- [ ] Installs cleanly on a fresh database.
- [ ] Tested as a non-admin user, since the superuser bypasses access rules.
- [ ] Demo data loads, and the workflow runs through from the UI.
