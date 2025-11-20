# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import json

CRM_MATERIAL_LINE_FIELDS = [
    'product_template_id',
    'attributes_description',
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
    product_category_id = fields.Many2one("product.category",string="Product Category",store=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    raw_spreadsheet_data = fields.Text("Raw Spreadsheet Data")

    # -------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------
    def get_formview_action(self, access_uid=None):
        print("DEBUG: get_formview_action called for spreadsheet id(s):", self.ids)
        return self.action_open_spreadsheet()

    def action_open_spreadsheet(self):
        self.ensure_one()
        print(f"DEBUG: action_open_spreadsheet -> id: {self.id}, name: {self.name}")
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
        print("DEBUG: create() called with vals_list:", vals_list)
        records = super().create(vals_list)

        for rec in records:
            print(f"DEBUG: post-create for record id={rec.id} - product_category_id:",
                rec.product_category_id.id if rec.product_category_id else False)

            try:
                # ✔️ correct field used: product_category_id
                category = rec.product_category_id

                if category and category.spreadsheet_data:
                    rec.raw_spreadsheet_data = category.spreadsheet_data
                    print(f"DEBUG: 🎉 Template applied for spreadsheet {rec.id} from category {category.id}")
                else:
                    print(f"DEBUG: No template available for rec {rec.id} (product_category_id={category.id if category else False})")

            except Exception as e:
                print("DEBUG: Exception while applying spreadsheet template for rec", rec.id, "error:", e)

        return records

    # -------------------------------------------------------------
    # SESSION JOIN
    # -------------------------------------------------------------
    def join_spreadsheet_session(self, access_token=None):
        """Ensure spreadsheet stays in sync with CRM material lines (add/remove only)."""
        self.ensure_one()
        print(f"\nDEBUG: join_spreadsheet_session start for spreadsheet id={self.id}, lead_id={self.lead_id.id if self.lead_id else False}")

        try:
            self._sync_sheets_with_material_lines()
        except Exception as e:
            print("DEBUG: _sync_sheets_with_material_lines raised:", e)

        data = super().join_spreadsheet_session(access_token)
        print("DEBUG: Raw data from super().join_spreadsheet_session keys:", list(data.keys()))
        data.update({
            'lead_id': self.lead_id.id if self.lead_id else False,
            'lead_display_name': self.lead_id.display_name if self.lead_id else False,
            'sheet_id': self.id
        })

        spreadsheet_json = data.get('data') or {}
        print("DEBUG: spreadsheet_json keys before manipulation:", list(spreadsheet_json.keys()))
        lists = spreadsheet_json.get('lists') or {}
        sheets = spreadsheet_json.get('sheets') or []

        current_line_ids = set(self.lead_id.material_line_ids.ids) if self.lead_id else set()
        existing_list_ids = {int(list_id) for list_id in lists.keys() if list_id.isdigit()}

        print("DEBUG: current_line_ids:", current_line_ids)
        print("DEBUG: existing_list_ids:", existing_list_ids)

        missing_ids = current_line_ids - existing_list_ids
        removed_ids = existing_list_ids - current_line_ids

        print("DEBUG: missing_ids (to ADD):", missing_ids)
        print("DEBUG: removed_ids (to REMOVE):", removed_ids)

        # --- ADD NEW SHEETS ---
        for line_id in missing_ids:
            try:
                # ✅ IMPROVEMENT: Check if sheet already exists in category template
                sheet_id = f"sheet_{line_id}"
                existing_sheet = next((s for s in sheets if s.get('id') == sheet_id), None)
                
                if existing_sheet:
                    print(f"DEBUG: ✅ Sheet already exists in template for line {line_id}, only adding list")
                    # Sheet already exists in category template, just add list
                    list_data = self._create_list_for_material_line(line_id)
                    lists[str(line_id)] = list_data
                else:
                    # Sheet doesn't exist, create both sheet and list
                    new_sheet_data = self._create_sheet_for_material_line(line_id)
                    lists[str(line_id)] = new_sheet_data['list']
                    sheets.append(new_sheet_data['sheet'])
                    print(f"DEBUG: Added sheet/list for material_line {line_id}")
                    
            except Exception as e:
                print("DEBUG: Error adding sheet for line_id", line_id, "error:", e)

        # --- REMOVE DELETED SHEETS ---
        if removed_ids:
            for rid in removed_ids:
                if str(rid) in lists:
                    del lists[str(rid)]
                    print(f"DEBUG: Removed list entry for {rid}")
                # ✅ IMPROVEMENT: Don't remove sheets from category template
                # Only remove sheets that were specifically created for material lines
            
            # ✅ IMPROVEMENT: Only remove sheet objects that were created for material lines
            sheets_before = len(sheets)
            sheets_to_remove = []
            for s in sheets:
                sheet_id = s.get('id', '')
                if sheet_id.startswith('sheet_'):
                    try:
                        line_id = int(sheet_id.replace('sheet_', ''))
                        if line_id in removed_ids:
                            sheets_to_remove.append(s)
                    except ValueError:
                        continue
            
            for sheet in sheets_to_remove:
                sheets.remove(sheet)
                
            print(f"DEBUG: Removed {len(sheets_to_remove)} sheets from sheets array")

        # Save back
        spreadsheet_json['lists'] = lists
        spreadsheet_json['sheets'] = sheets
        data['data'] = spreadsheet_json
        try:
            self.raw_spreadsheet_data = json.dumps(spreadsheet_json)
            print("DEBUG: raw_spreadsheet_data updated (length):", len(self.raw_spreadsheet_data or ""))
        except Exception as e:
            print("DEBUG: Error saving raw_spreadsheet_data:", e)

        print(f"DEBUG: join_spreadsheet_session end for spreadsheet id={self.id}\n")
        return data
    # -------------------------------------------------------------
    # EMPTY DATA
    # -------------------------------------------------------------
    def _empty_spreadsheet_data(self):
        """Return a base spreadsheet JSON structure with one sheet per material line."""
        print("DEBUG: _empty_spreadsheet_data called for id(s):", self.ids)
        data = super()._empty_spreadsheet_data() or {}
        data.setdefault('lists', {})
        data['sheets'] = []

        if not self.lead_id or not self.lead_id.material_line_ids:
            print("DEBUG: No lead or material lines, returning base empty data")
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
            print(f"DEBUG: _empty_spreadsheet_data -> added sheet/list for line.id={line.id}, product='{product_name}'")

        print("DEBUG: _empty_spreadsheet_data completed, sheets count:", len(data['sheets']))
        return data

    # -------------------------------------------------------------
    # INSERT LIST REVISION
    # -------------------------------------------------------------
    def _dispatch_insert_list_revision(self):
        self.ensure_one()
        line_id = self._context.get('material_line_id')
        print("DEBUG: _dispatch_insert_list_revision context material_line_id:", line_id)
        if not line_id:
            print("DEBUG: No material_line_id in context, returning")
            return

        line = self.env['crm.material.line'].browse(line_id)
        if not line.exists():
            print("DEBUG: Line not exists for id:", line_id)
            return

        sheet_id = f"sheet_{line.id}"
        list_id = str(line.id)
        product_name = (line.product_template_id.display_name or "Item")[:31]

        columns = [
            {'name': f, 'type': self.env['crm.material.line']._fields.get(f).type if self.env['crm.material.line']._fields.get(f) else 'unknown'}
            for f in CRM_MATERIAL_LINE_FIELDS
        ]
        print("DEBUG: _dispatch_insert_list_revision -> building commands for line:", line_id, "columns:", columns)

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
        try:
            self._dispatch_commands(commands)
            print(f"DEBUG: _dispatch_insert_list_revision dispatched commands for line {line_id}")
        except Exception as e:
            print("DEBUG: Error dispatching commands for line", line_id, "error:", e)

    # -------------------------------------------------------------
    # SYNC METHODS
    # -------------------------------------------------------------
    def _sync_sheets_with_material_lines(self):
        self.ensure_one()
        print("DEBUG: _sync_sheets_with_material_lines called for spreadsheet id:", self.id)
        if not self.lead_id:
            print("DEBUG: No lead_id set on spreadsheet, returning")
            return

        try:
            current_data = json.loads(self.raw_spreadsheet_data) if self.raw_spreadsheet_data else {}
        except Exception as e:
            print("DEBUG: raw_spreadsheet_data JSON load failed:", e)
            current_data = {}

        current_sheets = current_data.get('sheets', [])
        current_lists = current_data.get('lists', {})
        current_line_ids = set(self.lead_id.material_line_ids.ids)

        print("DEBUG: current_sheets count:", len(current_sheets))
        print("DEBUG: current_lists keys:", list(current_lists.keys()))
        print("DEBUG: current_line_ids:", current_line_ids)

        # ✅ IMPROVEMENT: Only delete material line sheets that are specifically created for removed lines
        for sheet in list(current_sheets):
            sheet_id = sheet.get('id', '')
            if sheet_id.startswith('sheet_'):
                try:
                    line_id = int(sheet_id.replace('sheet_', ''))
                    if line_id not in current_line_ids:
                        print("DEBUG: Deleting sheet for line_id not present:", line_id)
                        self._delete_sheet_for_material_line(line_id)
                except ValueError:
                    print("DEBUG: Skipping non-numeric sheet id:", sheet_id)
                    continue
                    
        # ✅ IMPROVEMENT: Only delete lists for removed material lines
        for list_id in list(current_lists.keys()):
            try:
                line_id = int(list_id)
                if line_id not in current_line_ids:
                    print("DEBUG: Deleting list for line_id not present:", line_id)
                    self._delete_sheet_for_material_line(line_id)
            except ValueError:
                print("DEBUG: Skipping non-numeric list id:", list_id)
                continue

        existing_sheet_ids = {int(sheet['id'].replace('sheet_', '')) for sheet in current_sheets
                            if sheet.get('id', '').startswith('sheet_')}
        print("DEBUG: existing_sheet_ids extracted:", existing_sheet_ids)
        
        # ✅ IMPROVEMENT: Check if sheet exists before creating
        for line in self.lead_id.material_line_ids:
            if line.id not in existing_sheet_ids:
                print("DEBUG: Missing sheet for line.id=", line.id, "-> will dispatch insert")
                self.with_context(material_line_id=line.id)._dispatch_insert_list_revision()
            else:
                print(f"DEBUG: ✅ Sheet already exists for line.id={line.id} in category template")

    def _create_sheet_for_material_line(self, material_line_id):
        self.ensure_one()
        print("DEBUG: _create_sheet_for_material_line called for id:", material_line_id)
        line = self.env['crm.material.line'].browse(material_line_id)
        if not line.exists():
            print("DEBUG: _create_sheet_for_material_line: line does not exist:", material_line_id)
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
        print("DEBUG: _create_sheet_for_material_line -> returning sheet/list for line:", material_line_id)
        return {'sheet': sheet_data, 'list': list_data}

    def _delete_sheet_for_material_line(self, material_line_id):
        self.ensure_one()
        sheet_id = f"sheet_{material_line_id}"
        list_id = str(material_line_id)
        print("DEBUG: _delete_sheet_for_material_line called for id:", material_line_id, " -> sheet_id:", sheet_id)

        commands = [
            {'type': 'DELETE_SHEET', 'sheetId': sheet_id},
            {'type': 'UNREGISTER_ODOO_LIST', 'listId': list_id},
        ]

        try:
            self._dispatch_commands(commands)
            print("DEBUG: _delete_sheet_for_material_line dispatched delete commands for", material_line_id)
        except Exception as e:
            print("DEBUG: _delete_sheet_for_material_line dispatch failed, falling back to cleanup. error:", e)
            self._cleanup_deleted_sheets_from_data(material_line_id)

    def _cleanup_deleted_sheets_from_data(self, material_line_id):
        self.ensure_one()
        print("DEBUG: _cleanup_deleted_sheets_from_data for id:", material_line_id)
        if not self.raw_spreadsheet_data:
            print("DEBUG: No raw_spreadsheet_data to cleanup")
            return
        try:
            data = json.loads(self.raw_spreadsheet_data)
            sheet_id = f"sheet_{material_line_id}"
            list_id = str(material_line_id)
            if 'sheets' in data:
                before = len(data['sheets'])
                data['sheets'] = [s for s in data['sheets'] if s.get('id') != sheet_id]
                after = len(data['sheets'])
                print(f"DEBUG: cleaned sheets: removed {before - after} entries")
            if 'lists' in data and list_id in data['lists']:
                del data['lists'][list_id]
                print("DEBUG: removed list entry", list_id)
            self.raw_spreadsheet_data = json.dumps(data)
            print("DEBUG: raw_spreadsheet_data updated after cleanup (length):", len(self.raw_spreadsheet_data))
        except Exception as e:
            print("DEBUG: Exception during cleanup:", e)

    # -------------------------------------------------------------
    # MANUAL SYNC ACTION
    # -------------------------------------------------------------
    def action_sync_sheets(self):
        print("DEBUG: action_sync_sheets called for ids:", self.ids)
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
        print("DEBUG: _get_spreadsheet_selector called for model:", self._name)
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
        # NOTE: this method is called from client side via rpc - ensure it logs properly
        print("DEBUG: get_crm_material_lines called - self:", getattr(self, 'id', None))
        self.ensure_one()
        if not self.lead_id:
            print("DEBUG: get_crm_material_lines -> no lead_id, returning []")
            return []
        
        result = []
        for line in self.lead_id.material_line_ids:
            # Build proper attribute description with all selected attributes
            attribute_description = ""
            if line.product_template_attribute_value_ids:
                # Combine all attribute values into a formatted string
                attribute_parts = []
                for attr_value in line.product_template_attribute_value_ids:
                    attribute_parts.append(f"{attr_value.attribute_id.name}: {attr_value.name}")
                
                attribute_description = ", ".join(attribute_parts)
            
            item = {
                'id': line.id,
                'name': line.product_template_id.display_name if line.product_template_id else '',
                'quantity': line.quantity,
                'width': line.width,
                'height': line.height,
                'length': line.length,
                'thickness': line.thickness,
                'description': attribute_description,
                'attributes_description': attribute_description,
            }
            print("DEBUG: get_crm_material_lines -> prepared item:", item)
            result.append(item)
        
        print("DEBUG: get_crm_material_lines -> returning", len(result), "items")
        return result

    def getMainCrmMaterialLineLists(self):
        print("DEBUG: getMainCrmMaterialLineLists called for id:", getattr(self, 'id', None))
        self.ensure_one()
        if not self.lead_id or not self.lead_id.material_line_ids:
            print("DEBUG: getMainCrmMaterialLineLists -> no material lines")
            return []
        lists = [
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
        print("DEBUG: getMainCrmMaterialLineLists -> built lists for", len(lists), "lines")
        return lists
    
    def _create_list_for_material_line(self, material_line_id):
        """Create only list data for material line when sheet already exists in template."""
        self.ensure_one()
        print("DEBUG: _create_list_for_material_line called for id:", material_line_id)
        line = self.env['crm.material.line'].browse(material_line_id)
        if not line.exists():
            print("DEBUG: _create_list_for_material_line: line does not exist:", material_line_id)
            return {}

        sheet_id = f"sheet_{line.id}"
        list_id = str(line.id)
        product_name = (line.product_template_id.display_name or "Item")[:31]

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
        print("DEBUG: _create_list_for_material_line -> returning list for line:", material_line_id)
        return list_data
