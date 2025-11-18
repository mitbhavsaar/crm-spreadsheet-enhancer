# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import json

CRM_MATERIAL_LINE_FIELDS = [
    'product_template_id',
    'quantity',
    'width',
    'height',
    'length',
    'thickness',
]


class CrmLeadSpreadsheet(models.Model):
    _name = 'crm.lead.spreadsheet'
    _inherit = 'spreadsheet.mixin'
    _description = 'CRM Quotation Spreadsheet'

    name = fields.Char(required=True)
    lead_id = fields.Many2one('crm.lead', string="Opportunity", ondelete='cascade')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    raw_spreadsheet_data = fields.Text("Raw Spreadsheet Data")

    # -------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------
    def get_formview_action(self, access_uid=None):
        return self.action_open_spreadsheet()

    def action_open_spreadsheet(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'action_crm_lead_spreadsheet',
            'params': {
                'spreadsheet_id': self.id,
                'model': 'crm.lead.spreadsheet',
            },
        }

    # -------------------------------------------------------------
    # CREATE / INITIALIZE
    # -------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.lead_id and rec.lead_id.material_line_ids:
                for line in rec.lead_id.material_line_ids:
                    rec.with_context(material_line_id=line.id)._dispatch_insert_list_revision()
        return records

    # -------------------------------------------------------------
    # SESSION JOIN
    # -------------------------------------------------------------
    def join_spreadsheet_session(self, access_token=None):
        """Ensure spreadsheet stays in sync with CRM material lines (add/remove only)."""
        self.ensure_one()

        self._sync_sheets_with_material_lines()

        data = super().join_spreadsheet_session(access_token)
        data.update({
            'lead_id': self.lead_id.id if self.lead_id else False,
            'lead_display_name': self.lead_id.display_name if self.lead_id else False,
            'sheet_id': self.id
        })

        spreadsheet_json = data.get('data') or {}
        lists = spreadsheet_json.get('lists') or {}
        sheets = spreadsheet_json.get('sheets') or []

        current_line_ids = set(self.lead_id.material_line_ids.ids) if self.lead_id else set()
        existing_list_ids = {int(list_id) for list_id in lists.keys() if list_id.isdigit()}

        missing_ids = current_line_ids - existing_list_ids
        removed_ids = existing_list_ids - current_line_ids

        # --- ADD NEW SHEETS ---
        for line_id in missing_ids:
            new_sheet_data = self._create_sheet_for_material_line(line_id)
            lists[str(line_id)] = new_sheet_data['list']
            sheets.append(new_sheet_data['sheet'])

        # --- REMOVE DELETED SHEETS ---
        if removed_ids:
            for rid in removed_ids:
                if str(rid) in lists:
                    del lists[str(rid)]
            sheets = [s for s in sheets if not any(str(rid) in json.dumps(s) for rid in removed_ids)]

        # Save back
        spreadsheet_json['lists'] = lists
        spreadsheet_json['sheets'] = sheets
        data['data'] = spreadsheet_json
        self.raw_spreadsheet_data = json.dumps(spreadsheet_json)

        return data

    # -------------------------------------------------------------
    # EMPTY DATA
    # -------------------------------------------------------------
    def _empty_spreadsheet_data(self):
        """Return a base spreadsheet JSON structure with one sheet per material line."""
        data = super()._empty_spreadsheet_data() or {}
        data.setdefault('lists', {})
        data['sheets'] = []

        if not self.lead_id or not self.lead_id.material_line_ids:
            return data

        for line in self.lead_id.material_line_ids:
            sheet_id = f"sheet_{line.id}"
            list_id = str(line.id)
            product_name = (line.product_template_id.display_name or "Untitled")[:31]

            data['sheets'].append({
                'id': sheet_id,
                'name': product_name,
            })

            data['lists'][list_id] = {
                'id': list_id,
                'model': 'crm.material.line',
                'columns': CRM_MATERIAL_LINE_FIELDS,
                'domain': [['id', '=', line.id]],
                'sheetId': sheet_id,
                'name': product_name,
                'context': {},
                'orderBy': [],
                'fieldMatching': {
                    'material_line_ids': {'chain': 'lead_id', 'type': 'many2one'},
                },
            }
        return data

    # -------------------------------------------------------------
    # INSERT LIST REVISION
    # -------------------------------------------------------------
    def _dispatch_insert_list_revision(self):
        self.ensure_one()
        line_id = self._context.get('material_line_id')
        if not line_id:
            return

        line = self.env['crm.material.line'].browse(line_id)
        if not line.exists():
            return

        sheet_id = f"sheet_{line.id}"
        list_id = str(line.id)
        product_name = (line.product_template_id.display_name or "Item")[:31]

        columns = [
            {'name': f, 'type': self.env['crm.material.line']._fields.get(f).type}
            for f in CRM_MATERIAL_LINE_FIELDS
        ]

        commands = [
            {
                'type': 'CREATE_SHEET',
                'sheetId': sheet_id,
                'name': product_name,
            },
            {
                'type': 'REGISTER_ODOO_LIST',
                'listId': list_id,
                'model': 'crm.material.line',
                'columns': CRM_MATERIAL_LINE_FIELDS,
                'domain': [['id', '=', line.id]],
                'context': {},
                'orderBy': [],
            },
            {
                'type': 'RE_INSERT_ODOO_LIST',
                'sheetId': sheet_id,
                'col': 0,
                'row': 0,
                'id': list_id,
                'linesNumber': 1,
                'columns': columns,
            },
            {
                'type': 'CREATE_TABLE',
                'sheetId': sheet_id,
                'tableType': 'static',
                'ranges': [{
                    '_sheetId': sheet_id,
                    '_zone': {'top': 0, 'bottom': 1, 'left': 0, 'right': len(columns) - 1}
                }],
                'config': {
                    'firstColumn': False,
                    'hasFilters': True,
                    'totalRow': False,
                    'bandedRows': True,
                    'styleId': 'TableStyleMedium5',
                }
            },
            {
                'type': 'UPDATE_ODOO_LIST_DATA',
                'listId': list_id,
            }
        ]
        self._dispatch_commands(commands)

    # -------------------------------------------------------------
    # SYNC METHODS
    # -------------------------------------------------------------
    def _sync_sheets_with_material_lines(self):
        self.ensure_one()
        if not self.lead_id:
            return

        current_data = json.loads(self.raw_spreadsheet_data) if self.raw_spreadsheet_data else {}
        current_sheets = current_data.get('sheets', [])
        current_lists = current_data.get('lists', {})
        current_line_ids = set(self.lead_id.material_line_ids.ids)

        # Delete extra sheets
        for sheet in current_sheets:
            sheet_id = sheet.get('id', '')
            if sheet_id.startswith('sheet_'):
                try:
                    line_id = int(sheet_id.replace('sheet_', ''))
                    if line_id not in current_line_ids:
                        self._delete_sheet_for_material_line(line_id)
                except ValueError:
                    continue
        for list_id in list(current_lists.keys()):
            try:
                line_id = int(list_id)
                if line_id not in current_line_ids:
                    self._delete_sheet_for_material_line(line_id)
            except ValueError:
                continue

        existing_sheet_ids = {int(sheet['id'].replace('sheet_', '')) for sheet in current_sheets
                              if sheet['id'].startswith('sheet_')}
        for line in self.lead_id.material_line_ids:
            if line.id not in existing_sheet_ids:
                self.with_context(material_line_id=line.id)._dispatch_insert_list_revision()

    def _create_sheet_for_material_line(self, material_line_id):
        self.ensure_one()
        line = self.env['crm.material.line'].browse(material_line_id)
        if not line.exists():
            return {'sheet': {}, 'list': {}}

        sheet_id = f"sheet_{line.id}"
        list_id = str(line.id)
        product_name = (line.product_template_id.display_name or "Item")[:31]

        sheet_data = {'id': sheet_id, 'name': product_name}
        list_data = {
            'id': list_id,
            'model': 'crm.material.line',
            'columns': CRM_MATERIAL_LINE_FIELDS,
            'domain': [['id', '=', line.id]],
            'sheetId': sheet_id,
            'name': product_name,
            'context': {},
            'orderBy': [],
            'fieldMatching': {'material_line_ids': {'chain': 'lead_id', 'type': 'many2one'}},
        }
        return {'sheet': sheet_data, 'list': list_data}

    def _delete_sheet_for_material_line(self, material_line_id):
        self.ensure_one()
        sheet_id = f"sheet_{material_line_id}"
        list_id = str(material_line_id)

        commands = [
            {'type': 'DELETE_SHEET', 'sheetId': sheet_id},
            {'type': 'UNREGISTER_ODOO_LIST', 'listId': list_id},
        ]

        try:
            self._dispatch_commands(commands)
        except Exception:
            self._cleanup_deleted_sheets_from_data(material_line_id)

    def _cleanup_deleted_sheets_from_data(self, material_line_id):
        self.ensure_one()
        if not self.raw_spreadsheet_data:
            return
        try:
            data = json.loads(self.raw_spreadsheet_data)
            sheet_id = f"sheet_{material_line_id}"
            list_id = str(material_line_id)
            if 'sheets' in data:
                data['sheets'] = [s for s in data['sheets'] if s.get('id') != sheet_id]
            if 'lists' in data and list_id in data['lists']:
                del data['lists'][list_id]
            self.raw_spreadsheet_data = json.dumps(data)
        except Exception:
            pass

    # -------------------------------------------------------------
    # MANUAL SYNC ACTION
    # -------------------------------------------------------------
    def action_sync_sheets(self):
        for spreadsheet in self:
            spreadsheet._sync_sheets_with_material_lines()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _('Sheets synced successfully with material lines.'),
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    # -------------------------------------------------------------
    # SELECTOR
    # -------------------------------------------------------------
    @api.model
    def _get_spreadsheet_selector(self):
        return {
            'model': self._name,
            'display_name': _("CRM Quote Spreadsheets"),
            'sequence': 20,
            'allow_create': False,
        }

    # -------------------------------------------------------------
    # DATA PROVIDERS
    # -------------------------------------------------------------
    @api.model
    def get_crm_material_lines(self):
        self.ensure_one()
        if not self.lead_id:
            return []
        return [
            {
                'id': line.id,
                'name': line.product_template_id.display_name if line.product_template_id else '',
                'quantity': line.quantity,
                'width': line.width,
                'height': line.height,
                'length': line.length,
                'thickness': line.thickness,
            }
            for line in self.lead_id.material_line_ids
        ]

    def getMainCrmMaterialLineLists(self):
        self.ensure_one()
        if not self.lead_id or not self.lead_id.material_line_ids:
            return []
        return [
            {
                'id': str(line.id),
                'model': 'crm.material.line',
                'field_names': CRM_MATERIAL_LINE_FIELDS,
                'columns': CRM_MATERIAL_LINE_FIELDS,
                'name': line.product_template_id.display_name or f"Item {line.id}",
                'sheetId': f"sheet_{line.id}",
            }
            for line in self.lead_id.material_line_ids
        ]
