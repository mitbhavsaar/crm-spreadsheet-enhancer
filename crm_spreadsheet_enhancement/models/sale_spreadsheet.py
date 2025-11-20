# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError
import json
import logging

_logger = logging.getLogger(__name__)

SALES_ORDER_LINE_FIELDS = [
    'product_id',
    'product_uom_qty', 
    'price_unit',
    'width',
    'height',
    'length',
    'thickness',
]

class SaleOrderSpreadsheet(models.Model):
    _name = 'sale.order.spreadsheet'
    _inherit = 'spreadsheet.mixin'
    _description = 'Sales Order Spreadsheet'

    name = fields.Char(required=True)
    order_id = fields.Many2one('sale.order', string="Sales Order", ondelete='cascade')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    raw_spreadsheet_data = fields.Text("Raw Spreadsheet Data")

    # -------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------
    def get_formview_action(self, access_uid=None):
        return self.action_open_spreadsheet()

    def action_open_spreadsheet(self):
        """Open sales spreadsheet"""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'action_sale_order_spreadsheet', 
            'params': {
                'spreadsheet_id': self.id,
                'model': 'sale.order.spreadsheet', 
            },
        }

    # -------------------------------------------------------------
    # AUTO-SYNC METHODS
    # -------------------------------------------------------------

    def _sync_order_lines_from_crm(self, crm_lead):
        """Sync order lines from CRM material lines"""
        try:
            order = self.order_id
            
            for material_line in crm_lead.material_line_ids:
                if material_line.product_id:
                    # Check if product already exists in order
                    existing_line = order.order_line.filtered(
                        lambda l: l.product_id == material_line.product_id
                    )
                    
                    if not existing_line:
                        # Create new order line
                        self.env['sale.order.line'].create({
                            'order_id': order.id,
                            'product_id': material_line.product_id.id,
                            'product_uom_qty': material_line.quantity or 1.0,
                            'price_unit': material_line.price or material_line.product_id.list_price,
                            'width': material_line.width or 0,
                            'height': material_line.height or 0,
                            'length': material_line.length or 0,
                            'thickness': material_line.thickness or 0,
                            'name': material_line.product_id.name,
                        })
                        
        except Exception as e:
            print(f"[ORDER_SYNC] Error: {str(e)}")

    # -------------------------------------------------------------
    # ENHANCED SESSION JOIN WITH AUTO-SYNC
    # -------------------------------------------------------------
    def join_spreadsheet_session(self, access_token=None):
        """Sales order spreadsheet session - CRM STYLE"""
        self.ensure_one()

        print("\n[SALES_SESSION_CRM] --- join_spreadsheet_session START ---")
        print(f"[SALES_SESSION_CRM] Spreadsheet: {self.name}")
        print(f"[SALES_SESSION_CRM] Has raw data: {bool(self.raw_spreadsheet_data)}")

        # Sync with current order lines
        self._sync_sheets_with_order_lines()

        # Get base data from super
        data = super().join_spreadsheet_session(access_token)
        
        # 🔥 CRITICAL: If we have converted CRM data, use it as base
        spreadsheet_json = {}
        if self.raw_spreadsheet_data:
            try:
                spreadsheet_json = json.loads(self.raw_spreadsheet_data)
                print(f"[SALES_SESSION_CRM] Using converted CRM data: {len(spreadsheet_json.get('lists', {}))} lists, {len(spreadsheet_json.get('sheets', []))} sheets")
            except Exception as e:
                print(f"[SALES_SESSION_CRM] Error loading converted data: {e}")
                spreadsheet_json = data.get('data') or {}
        else:
            spreadsheet_json = data.get('data') or {}
            print(f"[SALES_SESSION_CRM] Using empty/base data")

        # Get lists and sheets from the data
        lists = spreadsheet_json.get('lists') or {}
        sheets = spreadsheet_json.get('sheets') or []

        # Get current order line IDs
        current_line_ids = set(self.order_id.order_line.ids) if self.order_id else set()
        
        # Get existing list IDs from spreadsheet
        existing_list_ids = set()
        for list_id in lists.keys():
            try:
                # Extract numeric ID from list ID (e.g., "185" from "185" or "sales_185")
                if list_id.isdigit():
                    existing_list_ids.add(int(list_id))
                elif list_id.startswith('sales_'):
                    existing_list_ids.add(int(list_id.replace('sales_', '')))
            except ValueError:
                continue

        print(f"[SALES_SESSION_CRM] Current order line IDs: {current_line_ids}")
        print(f"[SALES_SESSION_CRM] Existing spreadsheet list IDs: {existing_list_ids}")

        # Find missing and removed lines
        missing_ids = current_line_ids - existing_list_ids
        removed_ids = existing_list_ids - current_line_ids

        print(f"[SALES_SESSION_CRM] Missing line IDs to add: {missing_ids}")
        print(f"[SALES_SESSION_CRM] Removed line IDs to delete: {removed_ids}")

        # --- ADD NEW SHEETS FOR NEW ORDER LINES ---
        for line_id in missing_ids:
            new_sheet_data = self._create_sheet_for_order_line(line_id)
            if new_sheet_data and new_sheet_data.get('list') and new_sheet_data.get('sheet'):
                # Use sales_ prefix for list IDs
                list_id = f"sales_{line_id}"
                lists[list_id] = new_sheet_data['list']
                sheets.append(new_sheet_data['sheet'])
                print(f"[SALES_SESSION_CRM] Added sheet for new order line {line_id}")

        # --- REMOVE DELETED ORDER LINES ---
        if removed_ids:
            # Remove lists
            lists_to_remove = []
            for list_key in list(lists.keys()):
                for rid in removed_ids:
                    if list_key == str(rid) or list_key == f"sales_{rid}":
                        lists_to_remove.append(list_key)
            
            for list_key in lists_to_remove:
                del lists[list_key]
                print(f"[SALES_SESSION_CRM] Removed list {list_key}")

            # Remove sheets related to deleted lines
            sheets_to_keep = []
            for sheet in sheets:
                sheet_id = sheet.get('id', '')
                should_keep = True
                for rid in removed_ids:
                    if sheet_id == f"sheet_sales_{rid}":
                        should_keep = False
                        break
                if should_keep:
                    sheets_to_keep.append(sheet)
            
            sheets = sheets_to_keep
            print(f"[SALES_SESSION_CRM] Removed sheets for deleted order lines {removed_ids}")

        # Save back to data
        spreadsheet_json['lists'] = lists
        spreadsheet_json['sheets'] = sheets
        data['data'] = spreadsheet_json
        
        # Also update raw_spreadsheet_data for persistence (only if we made changes)
        if missing_ids or removed_ids:
            self.raw_spreadsheet_data = json.dumps(spreadsheet_json)
            print(f"[SALES_SESSION_CRM] Updated raw_spreadsheet_data with changes")

        # Add sales order context
        data.update({
            'order_id': self.order_id.id if self.order_id else False,
            'order_display_name': self.order_id.display_name if self.order_id else False,
            'sale_order_id': self.order_id.id if self.order_id else False,
            'sheet_id': self.id
        })

        print(f"[SALES_SESSION_CRM] Final data: {len(lists)} lists, {len(sheets)} sheets")
        print("[SALES_SESSION_CRM] --- join_spreadsheet_session END ---\n")

        return data

    # -------------------------------------------------------------
    # EXISTING METHODS (UNCHANGED)
    # -------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            # Only create sheets if NO raw data (not from CRM)
            if rec.order_id and rec.order_id.order_line and not rec.raw_spreadsheet_data:
                for line in rec.order_id.order_line:
                    rec.with_context(order_line_id=line.id)._dispatch_insert_list_revision()
        return records

    def _empty_spreadsheet_data(self):
        """Return sales-specific spreadsheet structure"""
        data = super()._empty_spreadsheet_data() or {}
        data.setdefault('lists', {})
        data['sheets'] = []
        
        if not self.order_id or not self.order_id.order_line:
            return data

        for line in self.order_id.order_line:
            sheet_id = f"sheet_sales_{line.id}"
            list_id = f"sales_{line.id}"
            product_name = (line.product_id.display_name or "Untitled")[:31]

            data['sheets'].append({
                'id': sheet_id,
                'name': product_name,
            })

            data['lists'][list_id] = {
                'id': list_id,
                'model': 'sale.order.line',
                'columns': SALES_ORDER_LINE_FIELDS,
                'domain': [['id', '=', line.id]],
                'sheetId': sheet_id,
                'name': product_name,
                'context': {},
                'orderBy': [],
                'fieldMatching': {
                    'order_line': {'chain': 'order_id', 'type': 'many2one'},
                },
            }
        return data

    def _dispatch_insert_list_revision(self):
        """Create and register sheet + list for each sales order line"""
        self.ensure_one()
        line_id = self._context.get('order_line_id')
        if not line_id:
            return

        line = self.env['sale.order.line'].browse(line_id)
        if not line.exists():
            return

        sheet_id = f"sheet_sales_{line.id}"
        list_id = f"sales_{line.id}"
        product_name = (line.product_id.display_name or "Item")[:31]

        columns = [
            {'name': f, 'type': self.env['sale.order.line']._fields.get(f).type}
            for f in SALES_ORDER_LINE_FIELDS
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
                'model': 'sale.order.line',
                'columns': SALES_ORDER_LINE_FIELDS,
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

    def _sync_sheets_with_order_lines(self):
        """Sync sheets with current sales order lines"""
        self.ensure_one()
        
        if not self.order_id:
            return

        current_data = json.loads(self.raw_spreadsheet_data) if self.raw_spreadsheet_data else {}
        current_sheets = current_data.get('sheets', [])
        current_lists = current_data.get('lists', {})
        
        current_line_ids = set(self.order_id.order_line.ids)
        
        # Find and delete sheets for removed sales lines
        for sheet in current_sheets:
            sheet_id = sheet.get('id', '')
            if sheet_id.startswith('sheet_sales_'):
                try:
                    line_id = int(sheet_id.replace('sheet_sales_', ''))
                    if line_id not in current_line_ids:
                        self._delete_sheet_for_order_line(line_id)
                except ValueError:
                    continue
        
        for list_id in list(current_lists.keys()):
            if list_id.startswith('sales_'):
                try:
                    line_id = int(list_id.replace('sales_', ''))
                    if line_id not in current_line_ids:
                        self._delete_sheet_for_order_line(line_id)
                except ValueError:
                    continue

        # Create sheets for new sales lines
        existing_sheet_ids = {int(sheet['id'].replace('sheet_sales_', '')) for sheet in current_sheets 
                            if sheet['id'].startswith('sheet_sales_')}
        
        for line in self.order_id.order_line:
            if line.id not in existing_sheet_ids:
                self.with_context(order_line_id=line.id)._dispatch_insert_list_revision()
                
    def _create_sheet_for_order_line(self, order_line_id):
        """Return sheet + list data for sales order line - IMPROVED"""
        self.ensure_one()

        line = self.env['sale.order.line'].browse(order_line_id)
        if not line.exists():
            return None  # ✅ Return None instead of empty dict

        sheet_id = f"sheet_sales_{line.id}"
        list_id = f"sales_{line.id}"
        product_name = (line.product_id.display_name or f"Sales Item {line.id}")[:31]

        sheet_data = {
            'id': sheet_id,
            'name': product_name,
            'cells': {}, 
            'figures': [],
            'areGridLinesVisible': True,
            'rowCount': 1000,
            'colCount': 26,
        }

        list_data = {
            'id': list_id,
            'model': 'sale.order.line',
            'columns': SALES_ORDER_LINE_FIELDS,
            'domain': [['id', '=', line.id]],
            'sheetId': sheet_id,
            'name': product_name,
            'context': {},
            'orderBy': [],
            'fieldMatching': {
                'order_line': {'chain': 'order_id', 'type': 'many2one'},
            },
        }

        return {'sheet': sheet_data, 'list': list_data}

    def _delete_sheet_for_order_line(self, order_line_id):
        """Delete sheet for sales order line"""
        self.ensure_one()
        
        sheet_id = f"sheet_sales_{order_line_id}"
        list_id = f"sales_{order_line_id}"

        commands = [
            {
                'type': 'DELETE_SHEET',
                'sheetId': sheet_id,
            },
            {
                'type': 'UNREGISTER_ODOO_LIST',
                'listId': list_id,
            }
        ]
        
        try:
            self._dispatch_commands(commands)
        except Exception:
            self._cleanup_deleted_sales_sheets_from_data(order_line_id)

    def _cleanup_deleted_sales_sheets_from_data(self, order_line_id):
        """Clean up deleted sales sheets from data"""
        self.ensure_one()
        
        if not self.raw_spreadsheet_data:
            return
            
        try:
            data = json.loads(self.raw_spreadsheet_data)
            sheet_id = f"sheet_sales_{order_line_id}"
            list_id = f"sales_{order_line_id}"
            
            if 'sheets' in data:
                data['sheets'] = [s for s in data['sheets'] if s.get('id') != sheet_id]
            
            if 'lists' in data and list_id in data['lists']:
                del data['lists'][list_id]
            
            self.raw_spreadsheet_data = json.dumps(data)
        except Exception:
            pass

    @api.model
    def _get_spreadsheet_selector(self):
        return {
            'model': self._name,
            'display_name': _("Sales Order Spreadsheets"),
            'sequence': 30,
            'allow_create': False,
        }

    def getMainSalesOrderLineLists(self):
        """Return sales order line list definitions"""
        self.ensure_one()
        if not self.order_id or not self.order_id.order_line:
            return []

        return [
            {
                'id': f"sales_{line.id}",
                'model': 'sale.order.line',
                'field_names': SALES_ORDER_LINE_FIELDS,
                'columns': SALES_ORDER_LINE_FIELDS,
                'name': line.product_id.display_name or f"Sales Item {line.id}",
                'sheetId': f"sheet_sales_{line.id}",
            }
            for line in self.order_id.order_line
        ]