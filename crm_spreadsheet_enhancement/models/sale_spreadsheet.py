# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError
import json
import logging
import re

_logger = logging.getLogger(__name__)

SALES_ORDER_LINE_FIELDS = [
    'product_id',
    'product_uom_qty', 
    'price_unit',
    'width',
    'height',
    'length',
    'thickness',
    'raisin_type_id', 
    'price_total', # ✅ Added for formula support
]
class SaleOrderSpreadsheet(models.Model):
    _name = 'sale.order.spreadsheet'
    _inherit = 'spreadsheet.mixin'
    _description = 'Sales Order Spreadsheet'

    name = fields.Char(required=True)
    order_id = fields.Many2one('sale.order', string="Sales Order", ondelete='cascade')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    raw_spreadsheet_data = fields.Text("Raw Spreadsheet Data")
    is_converted_from_crm = fields.Boolean("Is Converted From CRM", default=False)
    is_saved_in_sale = fields.Boolean("Is Saved In Sale", default=False)

    # ✅ CRITICAL: Override get_list_data for Sales
    @api.model
    def get_list_data(self, model, list_id, field_names):
        """Get data for sale.order.line lists"""
        _logger.info(f"🟢 [Sales] get_list_data: model={model}, list_id={list_id}, fields={field_names}")
        
        if model != 'sale.order.line':
            return super().get_list_data(model, list_id, field_names)
        
        try:
            # Extract line ID
            if list_id.startswith('sales_'):
                line_id = int(list_id.replace('sales_', ''))
            else:
                line_id = int(list_id)
        except (ValueError, TypeError):
            _logger.error(f"❌ Invalid list_id: {list_id}")
            return []

        line = self.env['sale.order.line'].browse(line_id)
        if not line.exists():
            _logger.warning(f"❌ Sale order line {line_id} not found")
            return []

        _logger.info(f"✅ Found sale line {line_id}: {line.product_id.display_name}")
        
        row = {"id": line.id}

        for field in field_names:
            if field in line._fields:
                val = line[field]
                if hasattr(val, "display_name"):
                    row[field] = val.display_name
                else:
                    row[field] = val
                _logger.info(f"✅ Sale field '{field}' = '{row[field]}'")
            else:
                # ✅ Support for Dynamic Attributes from attributes_json
                attrs = getattr(line, 'attributes_json', {}) or {}
                row[field] = attrs.get(field, "")
                _logger.info(f"🔵 Sale Dynamic field '{field}' = '{row[field]}' from attributes_json")

        return [row]

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
                'sale_order_id': self.order_id.id if self.order_id else False,
                'order_display_name': self.order_id.name if self.order_id else False,
            },
        }

    # ✅ CRITICAL FIX: Convert CRM field syncs to Sales field syncs
    def _convert_crm_sheet_to_sales(self):
        """Convert CRM field syncs and lists to Sales format - NON-DESTRUCTIVE"""
        if not self.raw_spreadsheet_data:
            return

        try:
            data = json.loads(self.raw_spreadsheet_data)
        except Exception:
            return

        lists = data.get('lists', {}) or {}
        sheets = data.get('sheets', []) or []

        # ✅ FIELD MAPPING: CRM -> Sales
        FIELD_MAP = {
            'product_template_id': 'product_id',
            'quantity': 'product_uom_qty',
            'price': 'price_unit',
            'price_custom': 'price_unit',
            'width': 'width',
            'height': 'height',
            'length': 'length',
            'thickness': 'thickness',
            'raw_material': 'raw_material',
            'raisin_type_id': 'raisin_type_id',
            'total_price': 'price_total', # ✅ Added for formula conversion
        }

        # ✅ CRITICAL: Get REAL mapping from CRM lead if available
        line_mapping = {}
        if self.order_id and self.order_id.opportunity_id:
            try:
                line_mapping = self.order_id.opportunity_id._create_complete_line_id_mapping(self.order_id)
                _logger.info(f"📊 [DEBUGGER] Conversion Mapping found: {line_mapping}")
            except Exception as e:
                _logger.warning(f"⚠️ [DEBUGGER] Could not get real mapping: {e}")

        # ✅ ROBUST REPLACEMENT: Build a comprehensive ID map (CRM -> SALES)
        # We handle string, numeric, and prefixed IDs
        ID_MAP = {}
        for cml_id, sol_id in line_mapping.items():
            if not cml_id or not sol_id: continue
            ID_MAP[str(cml_id)] = f"sales_{sol_id}"
            ID_MAP[f"crm_{cml_id}"] = f"sales_{sol_id}"
            ID_MAP[f"sheet_{cml_id}"] = f"sheet_sales_{sol_id}"
            ID_MAP[f"sheet_crm_{cml_id}"] = f"sheet_sales_{sol_id}"

        def robust_replace(obj):
            """Recursively replace CRM identifiers and fields in any JSON object"""
            if isinstance(obj, dict):
                new_dict = {}
                for k, v in obj.items():
                    # Replace keys if they match CRM patterns
                    new_key = ID_MAP.get(k, k)
                    # Replace values recursively
                    new_dict[new_key] = robust_replace(v)
                return new_dict
            elif isinstance(obj, list):
                return [robust_replace(x) for x in obj]
            elif isinstance(obj, str):
                # Replace field names
                for old_f, new_f in FIELD_MAP.items():
                    if old_f != new_f:
                        obj = obj.replace(f'"{old_f}"', f'"{new_f}"').replace(f"'{old_f}'", f"'{new_f}'")
                
                # Replace IDs and formula patterns
                for old_id_pat, new_id_val in ID_MAP.items():
                    # Precise replacement for quoted IDs
                    obj = obj.replace(f'"{old_id_pat}"', f'"{new_id_val}"').replace(f"'{old_id_pat}'", f"'{new_id_val}'")
                    # Precise replacement for spreadsheet formulas patterns like (123, or ,123, or ,123)
                    # Note: old_id_pat might be "crm_123" or "123"
                    if old_id_pat.isdigit():
                        obj = obj.replace(f"({old_id_pat},", f'("{new_id_val}",')
                        obj = obj.replace(f", {old_id_pat},", f', "{new_id_val}",')
                        obj = obj.replace(f",{old_id_pat},", f',"{new_id_val}",')
                        obj = obj.replace(f", {old_id_pat})", f', "{new_id_val}")')
                        obj = obj.replace(f",{old_id_pat})", f',"{new_id_val}")')

                return obj
            return obj

        # Process the entire data structure
        data = robust_replace(data)

        # Ensure all lists have the correct model and sheetId
        new_lists = data.get('lists', {})
        for l_id, l_cfg in new_lists.items():
            if not isinstance(l_cfg, dict): continue
            if l_cfg.get('model') == 'crm.material.line':
                l_cfg['model'] = 'sale.order.line'
            # Correct sheetId if missing or wrong
            if l_id.startswith('sales_'):
                sol_id = l_id.replace('sales_', '')
                l_cfg['sheetId'] = f"sheet_sales_{sol_id}"
                l_cfg['domain'] = [['id', '=', int(sol_id)]]

        # Ensure all sheets have correct listId in fieldSyncs
        for sheet in data.get('sheets', []):
            if not isinstance(sheet, dict): continue
            fs = sheet.get('fieldSyncs', {})
            sid = sheet.get('id', '')
            if sid.startswith('sheet_sales_'):
                sol_id = sid.replace('sheet_sales_', '')
                for cell_ref, sync in fs.items():
                    sync['listId'] = f"sales_{sol_id}"
                    fname = sync.get('fieldName')
                    if fname in FIELD_MAP:
                        sync['fieldName'] = FIELD_MAP[fname]

        final_json = json.dumps(data)
        
        # ✅ PERMANENT PURGE: Replace model and old fields globally in the JSON string
        final_json = final_json.replace('crm.material.line', 'sale.order.line')
        final_json = final_json.replace('"price_custom"', '"price_unit"')
        final_json = final_json.replace('"quantity"', '"product_uom_qty"')

        try:
            self.raw_spreadsheet_data = final_json
            # ✅ Odoo 18 COMPATIBILITY: Set spreadsheet_snapshot so Odoo finds the data
            import base64
            self.spreadsheet_snapshot = base64.b64encode(final_json.encode('utf-8'))
            _logger.info("✅ Permanent Lock: CRM markers purged from spreadsheet JSON & Snapshot populated")
        except Exception as e:
            _logger.error(f"❌ Failed to save locked data: {e}")

    def _sync_order_lines_from_crm(self, crm_lead):
        """Sync order lines from CRM material lines"""
        try:
            order = self.order_id
            
            for material_line in crm_lead.material_line_ids:
                if material_line.product_id:
                    existing_line = order.order_line.filtered(
                        lambda l: l.product_id == material_line.product_id
                    )
                    
                    if not existing_line:
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
            _logger.error(f"[ORDER_SYNC] Error: {str(e)}")

    def join_spreadsheet_session(self, access_token=None):
        """Join spreadsheet session with structural logging - RESTORED & FIXED"""
        self.ensure_one()

        _logger.info(f"\n🚀 >>> [START_SESSION] SO Spreadsheet {self.id} | Order: {self.order_id.name if self.order_id else 'None'}")
        
        # 1. Revision Cleaning (Pre-emptive)
        # CRITICAL: If converted from CRM, we MUST delete DB revisions to prevent 
        # "Wrong base spreadsheet revision" errors during save.
        if self.is_converted_from_crm or not self.is_saved_in_sale:
            revisions_to_delete = self.env['spreadsheet.revision'].sudo().search([
                ('res_model', '=', self._name),
                ('res_id', '=', self.id)
            ])
            if revisions_to_delete:
                _logger.info(f"🧹 [DEBUG] Pre-emptive Revision Purge for Spreadsheet {self.id} ({len(revisions_to_delete)} records)")
                revisions_to_delete.unlink()
        
        # 2. Flag Verification
        persistent = self.is_saved_in_sale
        _logger.info(f"📍 [DEBUG] Persistence Flag BEFORE: {persistent}")
        
        self.invalidate_recordset(['raw_spreadsheet_data', 'is_saved_in_sale', 'is_converted_from_crm'])
        raw_len = len(self.raw_spreadsheet_data) if self.raw_spreadsheet_data else 0
        persistent = self.is_saved_in_sale
        _logger.info(f"📍 [DEBUG] Persistence Flag AFTER Invalid: {persistent} | Data Size: {raw_len}")

        if self.raw_spreadsheet_data and '3000' in self.raw_spreadsheet_data:
            _logger.debug("🎯 [FOUND_TRACER] Value '3000' DETECTED in raw_spreadsheet_data.")

        # 2. Conversion/Repair Flow
        if (not self.is_converted_from_crm) and self.raw_spreadsheet_data and any(marker in self.raw_spreadsheet_data for marker in ['"crm_', 'sheet_crm_', 'crm.material.line']):
            _logger.info("⚡ [DEBUG] CRM Markers detected. Repairing...")
            self._convert_crm_sheet_to_sales()
            self.sudo().with_context(skip_persistence_mark=True).write({'is_converted_from_crm': True})
            self.env.cr.commit()

        # 3. Sync Logic (PULL from Odoo for core fields)
        if not persistent:
            _logger.info("🛠️ [DEBUG] Persistence OFF -> Running Smart-Sync pull from Odoo records.")
            try:
                if self._update_spreadsheet_lists_data(check_only=True):
                    _logger.info("🚨 [DEBUG] Core field mismatch! Syncing data from lines...")
                    self._update_spreadsheet_lists_data(check_only=False)
                    self.env.cr.commit()
            except Exception as e:
                _logger.error(f"❌ [DEBUG] Sync fail: {e}")
        else:
            _logger.info("🛡️ [DEBUG] Persistence ON -> Shielding manual edits from Odoo record overwrites.")

        # 4. Standard Load (Odoo base logic)
        data = super().join_spreadsheet_session(access_token)
        
        # 5. Revision Cleaning (Response matching)
        if (persistent or self.is_converted_from_crm):
            # Clear from response data to match our DB purge
            if 'revisions' in data:
                data['revisions'] = []
            # Reset current revision in response
            data['server_revision_id'] = None 

        # 6. Structrual Prep & Snapshot Sync
        if not self.raw_spreadsheet_data and self.spreadsheet_snapshot:
            try:
                import base64
                self.raw_spreadsheet_data = base64.b64decode(self.spreadsheet_snapshot).decode('utf-8')
                _logger.info("🔄 [SNAPSHOT_RECOVERY] Restored raw_spreadsheet_data from Odoo snapshot.")
            except Exception as e:
                _logger.error(f"❌ [SNAPSHOT_RECOVERY] Failed: {e}")

        spreadsheet_json = {}
        if self.raw_spreadsheet_data:
            try:
                spreadsheet_json = json.loads(self.raw_spreadsheet_data)
            except Exception as e:
                _logger.error(f"❌ [DEBUG] JSON Parse error: {e}")
                spreadsheet_json = data.get('data') or {}
        else:
            spreadsheet_json = data.get('data') or {}

        lists = spreadsheet_json.get('lists', {})
        sheets = spreadsheet_json.get('sheets', [])
        
        # 7. Delta Handling (Add/Remove sheets for Sale Order Lines)
        current_line_ids = set(self.order_id.order_line.ids) if self.order_id else set()
        existing_list_ids = {
            int(str(list_id).replace('sales_', '')) 
            for list_id in lists.keys() 
            if str(list_id).startswith('sales_')
        }
        
        missing_ids = current_line_ids - existing_list_ids
        removed_ids = existing_list_ids - current_line_ids
        
        if missing_ids:
            _logger.info(f"➕ [DEBUG] Adding sheets for new lines: {missing_ids}")
            for line_id in missing_ids:
                new_sheet = self._create_sheet_for_order_line(line_id)
                if new_sheet:
                    lists[f"sales_{line_id}"] = new_sheet['list']
                    sheets.append(new_sheet['sheet'])
        
        if removed_ids:
            _logger.info(f"➖ [DEBUG] Removing sheets for deleted lines: {removed_ids}")
            for rid in removed_ids:
                list_key = f"sales_{rid}"
                sheet_key = f"sheet_sales_{rid}"
                if list_key in lists:
                    del lists[list_key]
                sheets = [s for s in sheets if s.get('id') != sheet_key]

        spreadsheet_json['lists'] = lists
        spreadsheet_json['sheets'] = sheets

        # 8. Data Preload (PULL for UI)
        # ✅ REFINEMENT: Even if persistent is False, we should only preload if the list DATA is missing.
        # This prevents overwriting manual edits (like 1000->3000) on re-open.
        for list_id in lists.keys():
            try:
                if not str(list_id).startswith('sales_'):
                    continue
                
                list_config = lists.get(list_id)
                # If data already exists and we are not forcing a refresh, skip.
                if list_config.get('data') and not missing_ids:
                    _logger.info(f"   �️ [DEBUG] List {list_id} already has data, skipping overwrite to protect edits.")
                    continue
                
                # ONLY preload if it's a NEW line (missing_ids) or if data is truly empty
                if list_id in [f"sales_{mid}" for mid in missing_ids] or not list_config.get('data'):
                    _logger.info(f"🛠️ [DEBUG] Preloading list {list_id} (Missing or New).")
                    line_id = int(str(list_id).replace('sales_', ''))
                    line = self.env['sale.order.line'].browse(line_id)
                    if line.exists():
                        columns = list_config.get('columns', [])
                        list_data = self.get_list_data('sale.order.line', list_id, columns)
                        if list_data:
                            spreadsheet_json['lists'][list_id]['data'] = list_data
                            _logger.info(f"   ✅ [DEBUG] Data merged for {list_id}")
            except Exception as e:
                _logger.error(f"❌ [DEBUG] Preload fail for {list_id}: {e}")
        else:
            _logger.info("🛡️ [DEBUG] No new lines to preload (Persistence Shield is Active).")

        data['data'] = spreadsheet_json
        
        # Add metadata context
        data.update({
            'order_id': self.order_id.id if self.order_id else False,
            'sale_order_id': self.order_id.id if self.order_id else False,
            'spreadsheet_id': self.id,
            'sheet_id': self.id
        })

        _logger.info(f"🏁 >>> [END_SESSION] SO Spreadsheet {self.id} Ready.\n")
        return data

    def _validate_list_domains(self, spreadsheet_data):
        """Validate list domains"""
        try:
            lists = spreadsheet_data.get('lists', {})
            
            for list_id, list_config in lists.items():
                domain = list_config.get('domain', [])
                record_id = None
                
                for condition in domain:
                    if (isinstance(condition, list) and len(condition) >= 3 and 
                        condition[0] == 'id' and condition[1] == '='):
                        record_id = condition[2]
                        break
                
                if record_id:
                    record = self.env['sale.order.line'].browse(record_id)
                    if not record.exists():
                        _logger.warning(f"⚠️ Invalid domain: List {list_id} -> Record {record_id}")
                        
        except Exception as e:
            _logger.error(f"❌ Validation error: {e}")

    def _dispatch_insert_list_revision(self):
        """Create and register sheet for sale order line"""
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

        # Build row data
        row_data = []
        for col_meta in columns:
            field_name = col_meta['name']
            val = line[field_name]
            
            if hasattr(val, 'display_name'):
                cell_value = val.display_name
            else:
                cell_value = val if val is not False else ''
                
            row_data.append(cell_value)

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
        ]

        # Insert cell values
        for col_idx, (col_meta, cell_value) in enumerate(zip(columns, row_data)):
            commands.append({
                'type': 'UPDATE_CELL',
                'sheetId': sheet_id,
                'col': col_idx,
                'row': 1,
                'content': str(cell_value) if cell_value not in (None, False, '') else '',
            })

        commands.extend([
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
        ])

        # Check for template and append if exists
        template_data = None
        if line.product_id.product_tmpl_id.categ_id.spreadsheet_data:
            try:
                template_data = json.loads(line.product_id.product_tmpl_id.categ_id.spreadsheet_data)
            except Exception:
                pass

        if template_data:
            # Apply Template Content with OFFSET 4 (Header + Data + 2 Gap)
            template_cmds = self._get_template_commands(sheet_id, template_data, row_offset=4)
            commands.extend(template_cmds)
        
        self._dispatch_commands(commands)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.order_id and rec.order_id.order_line and not rec.raw_spreadsheet_data:
                for line in rec.order_id.order_line:
                    rec.with_context(order_line_id=line.id)._dispatch_insert_list_revision()
        return records

    # Remove duplicate get_list_data method



    def _rebuild_missing_fieldsyncs(self, spreadsheet_data):
        """
        Rebuild missing fieldSyncs for sheets based on their list configuration.
        This fixes converted CRM spreadsheets that lack explicit syncs.
        """
        try:
            lists = spreadsheet_data.get('lists', {})
            sheets = spreadsheet_data.get('sheets', [])
            
            # Map sheetId to sheet object for quick access
            sheet_map = {s.get('id'): s for s in sheets}
            
            updates_made = False
            
            for list_id, list_config in lists.items():
                # Only process Sales lists
                if not str(list_id).startswith('sales_'):
                    continue
                    
                sheet_id = list_config.get('sheetId')
                if not sheet_id or sheet_id not in sheet_map:
                    continue
                    
                sheet = sheet_map[sheet_id]
                columns = list_config.get('columns', [])
                
                if 'fieldSyncs' not in sheet:
                    sheet['fieldSyncs'] = {}
                
                # Assume horizontal layout starting at A2 (Row 1, Col 0)
                # This matches _dispatch_insert_list_revision layout
                row_index = 1 # Row 2 in Excel (0-indexed is 1)
                
                from openpyxl.utils import get_column_letter
                
                for col_index, col_def in enumerate(columns):
                    # Get field name
                    field_name = col_def if isinstance(col_def, str) else col_def.get('name')
                    if not field_name: continue
                    
                    # Calculate Cell Reference (e.g., A2, B2)
                    col_letter = get_column_letter(col_index + 1)
                    cell_ref = f"{col_letter}{row_index + 1}"
                    
                # ✅ PROACTIVE CLEANUP: Remove syncs for Dynamic Attributes AND Product ID
                # User Request: "sirf wahan quantity hi rakhoi" (Keep only quantity/price)
                # We EXCLUDE product_id to prevent "It should be an Id" error.
                valid_fields = {
                    'product_uom_qty', 
                    'price_unit',
                    'quantity', # Alias
                    'price',    # Alias
                    'price_custom' # Alias
                }
                
                # Cleanup existing syncs first
                keys_to_remove = []
                for k, v in sheet['fieldSyncs'].items():
                    fname = v.get('fieldName')
                    if fname not in valid_fields:
                        keys_to_remove.append(k)
                        _logger.info(f"🧹 [REPAIR] Removing allowed sync: {k} -> {fname}")
                
                for k in keys_to_remove:
                    del sheet['fieldSyncs'][k]
                    updates_made = True

                for col_index, col_def in enumerate(columns):
                    # Get field name
                    field_name = col_def if isinstance(col_def, str) else col_def.get('name')
                    if not field_name: continue
                    
                    # ✅ STRICT FILTER: Only sync valid fields (Qty/Price)
                    if field_name not in valid_fields:
                        continue

                    # Calculate Cell Reference (e.g., A2, B2)
                    col_letter = get_column_letter(col_index + 1)
                    cell_ref = f"{col_letter}{row_index + 1}"
                    
                    # Check if sync exists
                    if cell_ref not in sheet['fieldSyncs']:
                        _logger.info(f"🛠️ [REPAIR] Creating missing sync for {cell_ref} -> {field_name}")
                        sheet['fieldSyncs'][cell_ref] = {
                            'listId': list_id,
                            'fieldName': field_name,
                            'indexInList': 0
                        }
                        updates_made = True
            
            return updates_made
            
        except Exception as e:
            _logger.error(f"❌ Repair failed: {e}")
            return False

    def _update_spreadsheet_lists_data(self, check_only=False):
        """
        Synchronize spreadsheet data with Odoo records.
        If check_only=True, return True if ANY core field is out of sync.
        """
        self.ensure_one()
        try:
            if not self.raw_spreadsheet_data:
                return False

            data = json.loads(self.raw_spreadsheet_data)
            lists = data.get('lists', {})
            sheets = data.get('sheets', [])
            modified = False
            
            # Helper for smart numeric comparison
            def is_value_different(v1, v2, field_name="unknown"):
                if v1 is False: v1 = ''
                if v2 is False: v2 = ''
                if str(v1).strip() == str(v2).strip():
                    return False
                try:
                    # Attempt float comparison for numeric strings
                    diff = abs(float(v1) - float(v2)) > 0.0001
                    if diff:
                        _logger.info(f"⚖️ [SYNC-LOG] Numeric Diff in '{field_name}': {v1} vs {v2}")
                    return diff
                except (ValueError, TypeError):
                    diff = str(v1).strip() != str(v2).strip()
                    if diff:
                        _logger.info(f"⚖️ [SYNC-LOG] String Diff in '{field_name}': '{v1}' vs '{v2}'")
                    return diff

            # CRM -> Sale Alias Map for backward compatibility
            FIELD_ALIASES = {
                'quantity': 'product_uom_qty',
                'price': 'price_unit',
                'price_custom': 'price_unit',
                'total_price': 'price_total',
            }

            for sheet in sheets:
                field_syncs = sheet.get('fieldSyncs', {})
                cells = sheet.get('cells', {})
                _logger.info("🔍 [DEBUGGER] Sync check: Sheet '%s' has %d fieldSyncs", sheet.get('name'), len(field_syncs))

                for cell_ref, sync in field_syncs.items():
                    list_id = sync.get('listId', '')
                    base_field_name = sync.get('fieldName')
                    
                    # Resolve record ID from list
                    record_id = None
                    if list_id in lists:
                        domain = lists[list_id].get('domain', [])
                        for cond in domain:
                            if isinstance(cond, list) and len(cond) >= 3 and cond[0] == 'id' and cond[1] == '=':
                                record_id = cond[2]
                                break
                    
                    # ✅ FALLBACK: If record_id is still a CRM ID, resolve to SOL ID using the Glue field
                    if not record_id or not self.env['sale.order.line'].browse(record_id).exists():
                        try:
                            potential_crm_id_str = str(list_id).replace('sales_', '').replace('crm_', '')
                            if potential_crm_id_str.isdigit():
                                potential_crm_id = int(potential_crm_id_str)
                                # Use the Glue Field for deterministic resolution
                                matched_line = self.order_id.order_line.filtered(lambda l: l.material_line_id.id == potential_crm_id)[:1]
                                if matched_line:
                                    record_id = matched_line.id
                                    _logger.info(f"🔗 [SMART-SYNC] GLUE MATCH: Resolved CRM ID {potential_crm_id} to SOL ID {record_id}")
                                else:
                                    # Fallback to scoring if glue fails (for legacy sheets)
                                    mapping = self.order_id.opportunity_id._create_complete_line_id_mapping(self.order_id)
                                    record_id = mapping.get(potential_crm_id)
                                    if record_id:
                                        _logger.info(f"🔗 [SMART-SYNC] SCORE MATCH: Resolved CRM ID {potential_crm_id} to SOL ID {record_id}")
                        except Exception as e:
                            _logger.error(f"⚠️ Resolution error: {e}")

                    if not record_id and str(list_id).replace('sales_', '').isdigit():
                        record_id = int(str(list_id).replace('sales_', ''))

                    if record_id and base_field_name:
                        # Fetch latest from DB
                        line = self.env['sale.order.line'].browse(record_id)
                        
                        # ✅ SCOPE LOCK: Only pull data if line belongs to THIS Sale Order
                        if not line.exists() or (line.order_id and line.order_id != self.order_id):
                            continue

                        # Resolve Field (handle aliases)
                        field_name = base_field_name
                        if field_name not in line._fields and field_name in FIELD_ALIASES:
                            field_name = FIELD_ALIASES[field_name]

                        # ✅ Check both standard fields and dynamic attributes
                        val = None
                        if field_name in line._fields:
                            val = line[field_name]
                        else:
                            attrs = getattr(line, 'attributes_json', {}) or {}
                            val = attrs.get(field_name, None)
                        
                        if val is not None:
                            new_val = val.display_name if hasattr(val, "display_name") else val
                            if new_val is False: new_val = ''
                            
                            # 🎯 Update JSON cell
                            if cell_ref not in cells:
                                cells[cell_ref] = {}
                            
                            current_val = cells[cell_ref].get('content', '')
                            _logger.info(f"   🔎 [SYNC_SCAN] Sheet '{sheet.get('name')}' | Cell {cell_ref} -> Field '{field_name}' | Value: '{current_val}' vs DB: '{new_val}'")
                            
                            # ✅ FORMULA SHIELD: Do not overwrite if it's a formula
                            if str(current_val).startswith('='):
                                _logger.info(f"   🛡️ [SYNC_SHIELD] Skipping formula in {cell_ref}")
                                continue

                            is_diff = is_value_different(current_val, new_val, field_name)
                            if is_diff:
                                if not check_only and current_val and current_val != '':
                                    _logger.info(f"   🛡️ [PROTECT] Cell {cell_ref} has '{current_val}'. Preserving user edit over DB value '{new_val}'.")
                                    continue
                                # ✅ SMART-SYNC CHECK: Only care about core field mismatches
                                if check_only:
                                    # If it's a resin field, we ignore its mismatch during core check
                                    is_resin_field = any(x in str(field_name).lower() for x in ['resin', 'rsign', 'raisin', 'resign'])
                                    if not is_resin_field:
                                        _logger.info(f"🚨 [SMART-SYNC] Mismatch detected in CORE field '{field_name}': Sheet='{current_val}' vs DB='{new_val}'")
                                        return True
                                    _logger.info(f"🟡 [SMART-SYNC] Mismatch in NON-CORE field '{field_name}': Sheet='{current_val}' vs DB='{new_val}'")
                                    continue 

                                cells[cell_ref]['content'] = str(new_val)
                                modified = True
                                _logger.info(f"🔄 [DEBUGGER] PULL Sync: Cell {cell_ref} updated to {new_val} (Old: {current_val})")
                            else:
                                if check_only:
                                    # Reduced logging for in-sync fields to avoid flood
                                    pass
            if check_only:
                return False 

            if modified:
                self.raw_spreadsheet_data = json.dumps(data)
                return True
                
        except Exception as e:
            _logger.error(f"❌ Failed to refresh spreadsheet data: {e}")
            return False
        
        return False

    def _get_template_commands(self, sheet_id, template_data, row_offset=0):
        """
        Generate commands to recreate the template sheet.
        """
        commands = []
        
        # 1. Cells
        if 'sheets' in template_data and template_data['sheets']:
            template_sheet = template_data['sheets'][0]
            
            # Merges
            from openpyxl.utils.cell import range_boundaries, get_column_letter
            for merge in template_sheet.get('merges', []):
                try:
                    min_col, min_row, max_col, max_row = range_boundaries(merge)
                    min_row += row_offset
                    max_row += row_offset
                    new_range = f"{get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{max_row}"
                    commands.append({
                        'type': 'ADD_MERGE',
                        'sheetId': sheet_id,
                        'target': [new_range]
                    })
                except Exception:
                    pass
                
            # Columns
            for col_idx, col_data in template_sheet.get('cols', {}).items():
                commands.append({
                    'type': 'RESIZE_COLUMNS_ROWS',
                    'sheetId': sheet_id,
                    'dimension': 'COL',
                    'elements': [int(col_idx)],
                    'size': col_data.get('width', 100) * 7 
                })
                
            # Rows
            for row_idx, row_data in template_sheet.get('rows', {}).items():
                commands.append({
                    'type': 'RESIZE_COLUMNS_ROWS',
                    'sheetId': sheet_id,
                    'dimension': 'ROW',
                    'elements': [int(row_idx) + row_offset],
                    'size': row_data.get('size', 21)
                })

            # Cells
            for cell_ref, cell_data in template_sheet.get('cells', {}).items():
                # Convert A1 to col/row
                col_letter = "".join(filter(str.isalpha, cell_ref))
                row_num = int("".join(filter(str.isdigit, cell_ref))) - 1
                from openpyxl.utils import column_index_from_string
                col_num = column_index_from_string(col_letter) - 1
                
                commands.append({
                    'type': 'UPDATE_CELL',
                    'sheetId': sheet_id,
                    'col': col_num,
                    'row': row_num + row_offset,
                    'content': str(cell_data.get('content', '')) if cell_data.get('content') is not None else '',
                    # 'format': cell_data.get('format'), 
                })
                
        return commands

    def _empty_spreadsheet_data(self):
        """Return sales spreadsheet structure"""
        data = super()._empty_spreadsheet_data() or {}
        data.setdefault('lists', {})
        data['sheets'] = []
        
        if not self.order_id or not self.order_id.order_line:
            return data

        for line in self.order_id.order_line:
            sheet_id = f"sheet_sales_{line.id}"
            list_id = f"sales_{line.id}"
            product_name = (line.product_id.display_name or "Untitled")[:31]

            # Check for template
            template_data = None
            if line.product_id.product_tmpl_id.categ_id.spreadsheet_data:
                try:
                    template_data = json.loads(line.product_id.product_tmpl_id.categ_id.spreadsheet_data)
                except Exception:
                    pass

            if template_data and template_data.get('sheets'):
                # Use template sheet
                template_sheet = template_data['sheets'][0]
                import copy
                sheet_json = copy.deepcopy(template_sheet)
                sheet_json['id'] = sheet_id
                sheet_json['name'] = product_name
                
                # ✅ SANITIZE: Ensure all cell content is string AND remove invalid format
                if 'cells' in sheet_json:
                    for cell_key, cell_val in sheet_json['cells'].items():
                        if 'content' in cell_val:
                            cell_val['content'] = str(cell_val['content']) if cell_val['content'] is not None else ""
                        if 'format' in cell_val:
                            del cell_val['format']

                data['sheets'].append(sheet_json)
            else:
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

    def _sync_sheets_with_order_lines(self):
        """Sync sheets with order lines"""
        self.ensure_one()
        
        if not self.order_id or self.raw_spreadsheet_data:
            return

        current_data = json.loads(self.raw_spreadsheet_data) if self.raw_spreadsheet_data else {}
        current_line_ids = set(self.order_id.order_line.ids)
        
        for line in self.order_id.order_line:
            self.with_context(order_line_id=line.id)._dispatch_insert_list_revision()
                
    def _create_sheet_for_order_line(self, order_line_id):
        """Create sheet for order line"""
        self.ensure_one()

        line = self.env['sale.order.line'].browse(order_line_id)
        if not line.exists():
            return None

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

    def write(self, vals):
        """✅ Defeat Reversion: Push to records on EVERY save and mark as saved in Sale"""
        # ✅ SYNC: If Odoo 18 saves to 'spreadsheet_snapshot', update our 'raw_spreadsheet_data'
        if 'spreadsheet_snapshot' in vals and 'raw_spreadsheet_data' not in vals:
            try:
                # spreadsheet_snapshot is usually a base64 string or bytes in some contexts
                # We need to ensure we can read it as JSON for our logic
                snapshot = vals['spreadsheet_snapshot']
                if snapshot:
                    # If it's bytes, decode it. If it's already a string, keep it.
                    # Note: In Odoo 18, it might be base64.
                    import base64
                    try:
                        decoded = base64.b64decode(snapshot).decode('utf-8')
                        vals['raw_spreadsheet_data'] = decoded
                        _logger.info("🔄 [SNAPSHOT_SYNC] Synchronized spreadsheet_snapshot to raw_spreadsheet_data (Base64)")
                    except Exception:
                        # If not base64, maybe it's raw JSON string
                        vals['raw_spreadsheet_data'] = str(snapshot)
                        _logger.info("🔄 [SNAPSHOT_SYNC] Synchronized spreadsheet_snapshot to raw_spreadsheet_data (Raw)")
            except Exception as e:
                _logger.warning(f"⚠️ Failed to sync snapshot: {e}")

        if 'raw_spreadsheet_data' in vals:
            data_len = len(vals['raw_spreadsheet_data'])
            _logger.info(f"\n💾 >>> [SAVE_ATTEMPT] Spreadsheet {self.id} | Data Size: {data_len} chars")
            
            # --- CELL DELTA LOGGING ---
            try:
                old_raw = self.raw_spreadsheet_data or '{}'
                new_raw = vals['raw_spreadsheet_data']
                
                old_data = json.loads(old_raw)
                new_data = json.loads(new_raw)
                
                old_sheets = {s.get('name'): s for s in old_data.get('sheets', [])}
                for new_sheet in new_data.get('sheets', []):
                    sheet_name = new_sheet.get('name')
                    old_sheet = old_sheets.get(sheet_name)
                    
                    if old_sheet:
                        new_cells = new_sheet.get('cells', {})
                        old_cells = old_sheet.get('cells', {})
                        all_refs = set(new_cells.keys()) | set(old_cells.keys())
                        
                        changes_count = 0
                        for ref in all_refs:
                            nc = new_cells.get(ref, {}).get('content', '')
                            oc = old_cells.get(ref, {}).get('content', '')
                            if str(nc) != str(oc):
                                _logger.info(f"📝 [CELL_CHANGE] Sheet '{sheet_name}' | Cell {ref}: '{oc}' -> '{nc}'")
                                changes_count += 1
                        
                        if not changes_count:
                            _logger.info(f"   ⚪ [NO_CHANGES] No cell content changed in sheet '{sheet_name}'.")
                    else:
                        _logger.info(f"   🆕 [NEW_SHEET] Sheet '{sheet_name}' was added/created.")
            except Exception as e:
                _logger.warning(f"   ⚠️ Could not compute cell delta: {e}")
            # --------------------------

            if not self.env.context.get('skip_persistence_mark'):
                vals['is_saved_in_sale'] = True
                _logger.info(f"🛡️ PERSISTENCE ACTIVATED for Spreadsheet {self.id}")
            
        res = super().write(vals)
        
        if 'raw_spreadsheet_data' in vals:
            for record in self:
                _logger.info(f"📍 [DEBUG] Triggering data push to Odoo records for Spreadsheet {record.id}")
                record._push_spreadsheet_data_to_records()
        return res

    def _push_spreadsheet_data_to_records(self):
        """
        Push data from spreadsheet cells back to Sales Order Lines.
        Uses fieldSyncs metadata for precise mapping.
        """
        self.ensure_one()
        _logger.info(f"📍 >>> [DEBUG_PUSH] Start for Spreadsheet {self.id}")
        
        if not self.raw_spreadsheet_data:
            _logger.warning("   - No raw_spreadsheet_data found, canceling push.")
            return
        if not self.order_id:
            _logger.warning("   - No order_id linked, canceling push.")
            return

        try:
            data = json.loads(self.raw_spreadsheet_data)
            lists = data.get('lists', {})
            sheets = data.get('sheets', [])
            
            # Map of record_id -> {field: value}
            updates = {}

            for sheet in sheets:
                field_syncs = sheet.get('fieldSyncs', {})
                cells = sheet.get('cells', {})
                
                for cell_ref, sync in field_syncs.items():
                    list_id = sync.get('listId', '')
                    field_name = sync.get('fieldName')
                    
                    # Resolve record ID
                    record_id = None
                    if list_id in lists:
                        domain = lists[list_id].get('domain', [])
                        for cond in domain:
                            if isinstance(cond, list) and len(cond) >= 3 and cond[0] == 'id' and cond[1] == '=':
                                record_id = cond[2]
                                break
                    if not record_id and str(list_id).replace('sales_', '').isdigit():
                        record_id = int(str(list_id).replace('sales_', ''))

                    if record_id and field_name:
                        # ✅ RESOLVE Field (handle aliases like quantity -> product_uom_qty)
                        FIELD_ALIASES = {
                            'quantity': 'product_uom_qty',
                            'price': 'price_unit',
                            'price_custom': 'price_unit',
                            'total_price': 'price_total',
                        }
                        if field_name not in self.env['sale.order.line']._fields and field_name in FIELD_ALIASES:
                            field_name = FIELD_ALIASES[field_name]
                        # Extract value from cell
                        # ✅ Try to get the evaluated value (pushed by our JS plugin)
                        # This allows syncing the RESULT of a formula
                        raw_value = sync.get('value')
                        
                        if raw_value is None:
                            # Fallback to cell content if value is not in metadata
                            cell = cells.get(cell_ref, {})
                            raw_value = cell.get('content', '')
                            
                            # ✅ FORMULA SHIELD (Fallback only): Skip formulas strings
                            if str(raw_value).startswith('='):
                                _logger.info(f"🛡️ [DEBUGGER] PUSH Sync: Skipping formula string in {cell_ref}")
                                continue

                        _logger.info(f"� [DATA_SYNC] Sheet '{sheet.get('name')}' | Cell {cell_ref} -> Field '{field_name}' | Value: {raw_value}")
                        
                        if record_id not in updates:
                            updates[record_id] = {}
                        
                        updates[record_id][field_name] = raw_value

            # Apply updates to Odoo records
            _logger.info(f"📍 [DEBUG_PUSH] Summary: {len(updates)} records to update.")
            for record_id, vals in updates.items():
                line = self.env['sale.order.line'].browse(record_id)
                if not line.exists():
                    _logger.warning(f"   - Line {record_id} does not exist.")
                    continue
                if line.order_id != self.order_id:
                    _logger.warning(f"   - Line {record_id} belongs to Order {line.order_id.id}, but spreadsheet is for Order {self.order_id.id}. Skipping.")
                    continue
                
                # Convert values - ALLOW dynamic attributes
                processed_vals = {}
                for f, v in vals.items():
                    if f in line._fields:
                        field = line._fields[f]
                        
                        # 🚫 SKIP Computed/Readonly fields on PUSH
                        if field.compute and not field.inverse:
                            _logger.info(f"⏭️ Skipping computed field {f} on push")
                            continue
                        if field.readonly:
                            _logger.info(f"⏭️ Skipping readonly field {f} on push")
                            continue

                        field_type = field.type
                        try:
                            # Clean up value: remove currency symbols, spaces, and handle grouping separators
                            clean_v = str(v).replace('$', '').replace('€', '').replace('£', '').replace('₹', '').replace(',', '').strip() if v not in (None, False, '') else '0'
                            
                            if field_type in ['float', 'monetary']:
                                processed_vals[f] = float(clean_v) if clean_v else 0.0
                            elif field_type == 'integer':
                                processed_vals[f] = int(float(clean_v)) if clean_v else 0
                            elif field_type == 'boolean':
                                processed_vals[f] = str(v).lower() in ('true', '1', 'yes')
                            elif field_type == 'many2one':
                                # ✅ RESOLVE Many2one names to IDs
                                if v and not str(v).isdigit():
                                    comodel = field.comodel_name
                                    target = self.env[comodel].search([('display_name', '=', v)], limit=1)
                                    if target:
                                        processed_vals[f] = target.id
                                        _logger.info(f"🔗 Resolved {f}: '{v}' -> ID {target.id}")
                                    else:
                                        _logger.warning(f"❓ Could not resolve {f} name: '{v}'")
                                else:
                                    processed_vals[f] = int(v) if v and str(v).isdigit() else False
                            else:
                                processed_vals[f] = v
                        except:
                            continue
                    else:
                        # ✅ Keep as is if it's potentially a dynamic attribute
                        processed_vals[f] = v
                
                if processed_vals:
                    # check if actually changed to avoid unnecessary writes
                    final_vals = {}
                    for f, nv in processed_vals.items():
                        ov = line[f]
                        if hasattr(ov, 'id'): ov = ov.id
                        
                        # Compare as strings to be safe
                        if str(ov) != str(nv):
                            final_vals[f] = nv
                            _logger.info(f"   ⚖️  [CHANGE_DETECTED] Field '{f}': '{ov}' -> '{nv}'")
                        else:
                            _logger.info(f"   ⚪ [NO_CHANGE] Field '{f}' is already '{nv}'")
                    
                    if final_vals:
                        line.sudo().write(final_vals)
                        _logger.info(f"✅ Synced SO Line {line.id}: {final_vals}")

        except Exception as e:
            _logger.error(f"❌ Failed to push spreadsheet data: {e}")

    def write_spreadsheet_data(self, data_json):
        """Legacy compatibility method"""
        return self.write({'raw_spreadsheet_data': data_json})

    @api.model
    def _get_spreadsheet_selector(self):
        return {
            'model': self._name,
            'display_name': _("Sales Order Spreadsheets"),
            'sequence': 30,
            'allow_create': False,
        }

    def getMainSalesOrderLineLists(self):
        """Return sales order line lists"""
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

    def _update_json_with_new_line_ids(self, line_mapping):
        """Update all JSON references (lists, fieldSyncs, sheets) to use new line IDs"""
        self.ensure_one()
        if not self.raw_spreadsheet_data or not line_mapping:
            return False

        try:
            data = json.loads(self.raw_spreadsheet_data)
            
            # Map of old IDs to new IDs as strings for JSON replacement
            ID_MAP = {}
            for old_id, new_id in line_mapping.items():
                ID_MAP[str(old_id)] = str(new_id)
                ID_MAP[f"sales_{old_id}"] = f"sales_{new_id}"
                ID_MAP[f"sheet_sales_{old_id}"] = f"sheet_sales_{new_id}"

            def deep_replace(obj):
                if isinstance(obj, dict):
                    new_dict = {}
                    for k, v in obj.items():
                        new_key = ID_MAP.get(k, k)
                        new_dict[new_key] = deep_replace(v)
                    return new_dict
                elif isinstance(obj, list):
                    return [deep_replace(x) for x in obj]
                elif isinstance(obj, str):
                    # Direct ID replacement
                    if obj in ID_MAP:
                        return ID_MAP[obj]
                    # Partial replacement in sheet IDs or list IDs
                    for old_pat, new_pat in ID_MAP.items():
                        if old_pat in obj:
                            obj = obj.replace(old_pat, new_pat)
                    return obj
                return obj

            # Update the entire JSON
            data = deep_replace(data)
            
            # Additional cleanup for list domains
            for l_id, l_cfg in data.get('lists', {}).items():
                if l_id.startswith('sales_'):
                    sol_id = l_id.replace('sales_', '')
                    l_cfg['domain'] = [['id', '=', int(sol_id)]]

            final_json = json.dumps(data)
            self.raw_spreadsheet_data = final_json
            
            # ✅ Odoo 18 COMPATIBILITY: Update snapshot too
            import base64
            self.spreadsheet_snapshot = base64.b64encode(final_json.encode('utf-8'))
            
            _logger.info(f"✅ [CLONE] Updated line IDs in spreadsheet {self.id} (Raw & Snapshot) for {len(line_mapping)} lines.")
            return True
            
        except Exception as e:
            _logger.error(f"❌ [CLONE] Static repair failed: {e}")
            return False

        