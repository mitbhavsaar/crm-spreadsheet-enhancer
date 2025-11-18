# -*- coding: utf-8 -*-

from odoo import api, fields, models
import logging
_logger = logging.getLogger(__name__)

class CrmLead(models.Model):
    _inherit = "crm.lead"
    
    
    template_id = fields.Many2one('crm.quotation.template', string='Quotation Template') 
    
    quote_calculator_id = fields.Many2one(
        'crm.lead.spreadsheet',
        string="Quote Calculator",
        compute='_compute_quote_calculator_id',
    )
    spreadsheet_template_id = fields.Many2one(
        'crm.lead.spreadsheet',
        string="Spreadsheet Template",
        help="Default spreadsheet template linked to this CRM type, if any."
    )

    spreadsheet_ids = fields.One2many(
        'crm.lead.spreadsheet',
        'lead_id',
        string="Spreadsheets",
        export_string_translation=False,
    )

    spreadsheet_id = fields.Many2one(
        'crm.lead.spreadsheet',
        compute='_compute_spreadsheet_id',
        store=False,
        export_string_translation=False,
    )
    
    @api.depends('template_id')
    def _compute_quote_calculator_id(self):
        for lead in self:
            lead.quote_calculator_id = lead.template_id.quote_calculator_id or False

    
    
    @api.model
    def default_get(self, fields_list):
        """Pre-fill the template_id field with the one set in CRM Settings"""
        res = super().default_get(fields_list)
        IrConfig = self.env['ir.config_parameter'].sudo()

        enable_templates = IrConfig.get_param('crm_spreadsheet_enhancement.enable_crm_quotation_templates', 'False')
        if enable_templates in ['True', True, '1', 1]:
            template_id_str = IrConfig.get_param('crm_spreadsheet_enhancement.crm_quotation_template_id', False)
            if template_id_str and template_id_str.isdigit():
                res['template_id'] = int(template_id_str)
        return res

    @api.depends('spreadsheet_ids')
    def _compute_spreadsheet_id(self):
        for lead in self:
            lead.spreadsheet_id = lead.spreadsheet_ids[:1]
    
    def action_open_lead_spreadsheet(self):
        """Open the quote calculator spreadsheet."""
        self.ensure_one()

        # Reuse existing spreadsheet or create new
        spreadsheet = self.env['crm.lead.spreadsheet'].search([
            ('lead_id', '=', self.id)
        ], limit=1)

        if not spreadsheet:
            spreadsheet = self.env['crm.lead.spreadsheet'].create({
                'name': f"{self.name or 'Quote'} - Calculator",
                'lead_id': self.id,
            })

        return spreadsheet.action_open_spreadsheet()
    
    def unlink(self):
        """Delete all related spreadsheets when lead is deleted."""
        for lead in self:
            if lead.spreadsheet_ids:
                lead.spreadsheet_ids.unlink()
        return super().unlink()   

