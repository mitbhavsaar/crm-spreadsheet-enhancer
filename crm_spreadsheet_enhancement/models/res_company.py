from odoo import models, fields, api

class ResCompany(models.Model):
    _inherit = 'res.company'
    
    crm_quotation_template_id = fields.Many2one(
        'crm.quotation.template',
        string="CRM Quotation Template",
    )